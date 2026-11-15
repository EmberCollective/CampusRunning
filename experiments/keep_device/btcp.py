"""Recovered B3 frames and shared B3/B5 business replies."""

import binascii
import re
from dataclasses import dataclass

from google.protobuf import descriptor_pb2, descriptor_pool, message_factory


SERVICE_UUID = "0000190a-0000-1000-8000-00805f9b34fb"
CHARACTERISTIC_UUIDS = (
    "00000001-0000-1000-8000-00805f9b34fb",
    "00000002-0000-1000-8000-00805f9b34fb",
)


# The observed Android frame merger reads the wire length as a signed short.
MAX_PAYLOAD = 0x7FFF
DEVICE_INFO_REQUEST = bytes.fromhex("01 02 03 03")
DEVICE_NAMES = {"B3": "Keep B3 Lab", "B5": "KeepB5 Lab"}


class UnsupportedRequest(ValueError):
    """A valid frame uses an unimplemented control mode or application request."""


@dataclass(frozen=True)
class Frame:
    fsn: int
    payload: bytes


def encode_frame(payload: bytes, fsn: int) -> bytes:
    """Encode one complete application frame without requesting transport ACK."""
    if type(fsn) is not int or not 0 <= fsn <= 255:
        raise ValueError("FSN must be an integer from 0 to 255")
    if not isinstance(payload, bytes) or not 1 <= len(payload) <= MAX_PAYLOAD:
        raise ValueError("Payload must contain 1 to 32767 bytes")
    body = b"\xa5\xa5\xa0" + bytes([fsn]) + len(payload).to_bytes(2, "little") + payload
    return body + binascii.crc_hqx(body, 0).to_bytes(2, "little")


def decode_frame(data: bytes) -> Frame:
    """Validate a complete frame; reject trailing bytes and unsupported modes."""
    if not isinstance(data, bytes) or len(data) < 9:
        raise ValueError("Incomplete frame")
    if data[:2] != b"\xa5\xa5":
        raise ValueError("Invalid frame magic")
    size = int.from_bytes(data[4:6], "little")
    if not 1 <= size <= MAX_PAYLOAD or len(data) != size + 8:
        raise ValueError("Invalid frame length")
    if binascii.crc_hqx(data[:-2], 0) != int.from_bytes(data[-2:], "little"):
        raise ValueError("Invalid frame CRC")
    if data[2] != 0xA0:
        raise UnsupportedRequest("Only complete application frames without ACK are supported")
    return Frame(data[3], data[6:-2])


def _device_info_class():
    # Field numbers/types come from the APK's device_info.proto resource.
    schema = descriptor_pb2.FileDescriptorProto(name="keep_lab_device_info.proto", syntax="proto3")
    message = schema.message_type.add(name="DeviceInfo")
    for number, name in enumerate(("manu_name", "mac", "sn", "hd_version", "fm_version", "has_bind"), 1):
        message.field.add(
            name=name,
            number=number,
            label=descriptor_pb2.FieldDescriptorProto.LABEL_OPTIONAL,
            type=(descriptor_pb2.FieldDescriptorProto.TYPE_UINT32 if number == 6
                  else descriptor_pb2.FieldDescriptorProto.TYPE_STRING),
        )
    pool = descriptor_pool.DescriptorPool()
    pool.Add(schema)
    return message_factory.GetMessageClass(pool.FindMessageTypeByName("DeviceInfo"))


_DeviceInfo = _device_info_class()


class DeviceInfoSession:
    """Create once per BLE connection to keep the outgoing FSN independent."""

    def __init__(self, mac: str, state=None, model: str = "B3", workout=None):
        if model not in DEVICE_NAMES:
            raise ValueError("Unsupported device model")
        if workout is not None and model != "B5":
            raise ValueError("Workout transfer requires B5")
        self.model = model
        self._workout = workout
        if not isinstance(mac, str) or re.fullmatch(r"(?:[0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}", mac) is None:
            raise ValueError("MAC must contain six colon-separated hexadecimal octets")
        identity = mac.replace(":", "").upper()
        if state is not None and state.mac != mac.upper():
            raise ValueError("Binding state belongs to another device")
        self._state = state
        self._info = _DeviceInfo(
            manu_name=DEVICE_NAMES[model],
            mac=identity,
            sn="LAB" + identity,
            hd_version="LAB",
            fm_version="0.0.1",
            # Current runtime maps 2 to unbound; the bundled proto comment is stale.
            has_bind=2,
        )
        self._fsn = 0

    def reply_payload(self, payload: bytes) -> bytes:
        """Shared protobuf business commands, independent of B3/B5 packet framing."""
        if payload == DEVICE_INFO_REQUEST:
            self._info.has_bind = 1 if self._state is not None and self._state.bound else 2
            return b"\x01\x02" + self._info.SerializeToString()
        if self._workout is not None and self._workout.accepts(payload):
            return self._workout.reply(payload)
        if self._state is not None:
            return self._state.reply(payload)
        raise UnsupportedRequest("Binding requires an explicit persistent state file")

    def reply(self, request: bytes) -> bytes:
        if self.model != "B3":
            raise UnsupportedRequest("B5 uses SIMPLE packets, not A5A5 frames")
        payload = self.reply_payload(decode_frame(request).payload)
        response = encode_frame(payload, self._fsn)
        self._fsn = (self._fsn + 1) % 256
        return response

    def reply_packets(self, request: bytes, limit: int) -> list[bytes]:
        if type(limit) is not int or limit < 8:
            raise ValueError("Invalid notification limit")
        if self.model == "B5":
            from .simple import decode_request, encode_response
            request_id, payload = decode_request(request)
            # Keep's B5 connection strategy caps its protocol payload at min(MTU, 247) - 3.
            return encode_response(self.reply_payload(payload), request_id, min(limit, 244))
        response = self.reply(request)
        return [response[offset:offset + limit] for offset in range(0, len(response), limit)]


def request_payload(request: bytes, model: str) -> bytes:
    if model == "B5":
        from .simple import decode_request
        return decode_request(request)[1]
    if model == "B3":
        return decode_frame(request).payload
    raise ValueError("Unsupported device model")


def request_metadata(request: bytes, model: str) -> str:
    """Describe fixed header fields only, even when frame validation rejects it.

    These are unverified wire fields, not decoded application data. Never include
    the body, CRC, or exception text; configuration bodies contain personal data.
    """
    metadata = f"bytes={len(request)}"
    if model == "B5" and len(request) >= 7:
        flags = request[2]
        return (f"{metadata} sid={request[5]:02x} cid={request[6]:02x} flags={flags:02x} "
                f"packet_type={flags & 7} ack={int(bool(flags & 8))} status={flags >> 4} "
                f"last={request[3]} current={request[4]}")
    if (model == "B3" and len(request) >= 10 and request[:2] == b"\xa5\xa5"
            and int.from_bytes(request[4:6], "little") >= 2):
        return (f"{metadata} sid={request[6]:02x} cid={request[7]:02x} "
                f"flags={request[2]:02x} fsn={request[3]}")
    return metadata + " header=unavailable"
