"""Wire fixtures and independent protobuf checks, without connecting a device."""

import binascii

import pytest
from google.protobuf import descriptor_pb2, descriptor_pool, message_factory, text_format

from experiments.keep_device.btcp import (
    DeviceInfoSession,
    Frame,
    UnsupportedRequest,
    decode_frame,
    encode_frame,
)


CAPTURED_REQUEST = bytes.fromhex("a5 a5 a0 00 04 00 01 02 03 03 67 8d")
LAB_MAC = "C1:23:45:67:89:AB"


def with_crc(body):
    return body + binascii.crc_hqx(body, 0).to_bytes(2, "little")


def test_captured_request_matches_crc_and_length_contract():
    assert decode_frame(CAPTURED_REQUEST) == Frame(0, b"\x01\x02\x03\x03")
    assert encode_frame(b"\x01\x02\x03\x03", 0) == CAPTURED_REQUEST


@pytest.mark.parametrize("data", [
    b"", CAPTURED_REQUEST[:7], CAPTURED_REQUEST[:-1], CAPTURED_REQUEST + b"\x00",
    with_crc(b"\x00\xa5" + CAPTURED_REQUEST[2:-2]),
    with_crc(CAPTURED_REQUEST[:4] + b"\x03\x00" + CAPTURED_REQUEST[6:-2]),
    with_crc(CAPTURED_REQUEST[:4] + b"\x00\x00"),
    with_crc(CAPTURED_REQUEST[:4] + b"\x00\x80" + bytes(32768)),
    CAPTURED_REQUEST[:-1] + b"\x00",
], ids=["empty", "short-header", "truncated", "trailing-byte", "bad-magic", "wrong-length", "empty-payload", "signed-length-overflow", "bad-crc"])
def test_malformed_frames_are_rejected(data):
    with pytest.raises(ValueError) as raised:
        decode_frame(data)
    assert not isinstance(raised.value, UnsupportedRequest)


@pytest.mark.parametrize("control", [0xB0, 0xA1, 0xA2, 0xA3, 0xA4, 0xA8, 0x00])
def test_ack_fragmented_and_other_control_modes_are_explicitly_unsupported(control):
    request = with_crc(CAPTURED_REQUEST[:2] + bytes([control]) + CAPTURED_REQUEST[3:-2])
    with pytest.raises(UnsupportedRequest):
        DeviceInfoSession(LAB_MAC).reply(request)


@pytest.mark.parametrize("fsn", [-1, 256, True, 1.5])
def test_invalid_outgoing_fsn_is_rejected(fsn):
    with pytest.raises(ValueError):
        encode_frame(b"\x01", fsn)


@pytest.mark.parametrize("payload", [b"", bytes(32768)], ids=["empty", "too-large"])
def test_invalid_outgoing_length_is_rejected(payload):
    with pytest.raises(ValueError):
        encode_frame(payload, 0)


def test_largest_supported_payload_round_trips():
    payload = bytes(32767)
    assert decode_frame(encode_frame(payload, 255)) == Frame(255, payload)


def test_identity_fields_decoded_with_independent_schema():
    schema = text_format.Parse('''
        name: "independent_device_info.proto"
        syntax: "proto3"
        message_type {
          name: "ExpectedInfo"
          field { name: "manufacturer" number: 1 label: LABEL_OPTIONAL type: TYPE_STRING }
          field { name: "mac" number: 2 label: LABEL_OPTIONAL type: TYPE_STRING }
          field { name: "serial" number: 3 label: LABEL_OPTIONAL type: TYPE_STRING }
          field { name: "hardware" number: 4 label: LABEL_OPTIONAL type: TYPE_STRING }
          field { name: "firmware" number: 5 label: LABEL_OPTIONAL type: TYPE_STRING }
          field { name: "binding" number: 6 label: LABEL_OPTIONAL type: TYPE_UINT32 }
        }
    ''', descriptor_pb2.FileDescriptorProto())
    pool = descriptor_pool.DescriptorPool()
    pool.Add(schema)
    info_type = message_factory.GetMessageClass(pool.FindMessageTypeByName("ExpectedInfo"))
    response = DeviceInfoSession(LAB_MAC.lower()).reply(CAPTURED_REQUEST)
    assert response[:6] == b"\xa5\xa5\xa0\x00" + (len(response) - 8).to_bytes(2, "little")
    assert int.from_bytes(response[-2:], "little") == binascii.crc_hqx(response[:-2], 0)
    assert response[6:8] == b"\x01\x02"
    info = info_type.FromString(response[8:-2])
    assert info.manufacturer == "Keep B3 Lab"
    assert info.mac == "C123456789AB"
    assert info.serial == "LABC123456789AB"
    assert info.hardware == "LAB"
    assert info.firmware == "0.0.1"
    assert info.binding == 2


def test_sequence_is_independent_wraps_and_resets_on_new_connection():
    session = DeviceInfoSession(LAB_MAC)
    request = encode_frame(b"\x01\x02\x03\x03", 123)
    for expected in range(257):
        assert decode_frame(session.reply(request)).fsn == expected % 256
    assert decode_frame(DeviceInfoSession(LAB_MAC).reply(request)).fsn == 0


@pytest.mark.parametrize("payload", [b"\x01\x05", b"\x01\x02", b"\x01\x02\x03\x04", b"\x01"])
def test_unknown_requests_are_rejected_without_consuming_sequence(payload):
    session = DeviceInfoSession(LAB_MAC)
    with pytest.raises(UnsupportedRequest):
        session.reply(encode_frame(payload, 0))
    with pytest.raises(ValueError):
        session.reply(CAPTURED_REQUEST[:-1])
    assert decode_frame(session.reply(CAPTURED_REQUEST)).fsn == 0


@pytest.mark.parametrize("mac", ["C123456789AB", "C1:23:45:67:89", "C1:23:45:67:89:XX", " C1:23:45:67:89:AB"])
def test_malformed_identity_is_rejected(mac):
    with pytest.raises(ValueError):
        DeviceInfoSession(mac)
