"""Minimal Keep B5 SIMPLE framing, recovered from Android 9.1.120.

Only complete single-packet requests are accepted. Request reassembly, fragment
ACKs, PUSH and nonzero statuses are unsupported; no hardware compatibility claim.
"""

import binascii

from .btcp import UnsupportedRequest


def _crc(payload: bytes, request_id: int, packet_type: int) -> bytes:
    # ny1.d uses full body length here, NOT the on-air fragment index bytes.
    checksum_input = (request_id.to_bytes(2, "little") + bytes([packet_type])
                      + (len(payload) - 2).to_bytes(2, "little") + payload)
    return binascii.crc_hqx(checksum_input, 0).to_bytes(2, "little")


def decode_request(packet: bytes) -> tuple[int, bytes]:
    """Return request ID and SID/CID/body after validating one complete request."""
    if not isinstance(packet, bytes) or not 9 <= len(packet) <= 65544:
        raise ValueError("Invalid SIMPLE request length")
    if packet[2:5] != b"\x00\x00\x00":
        raise UnsupportedRequest("Only single-packet SIMPLE REQUEST with status 0 and no ACK is supported")
    request_id = int.from_bytes(packet[:2], "little")
    payload = packet[5:-2]
    if packet[-2:] != _crc(payload, request_id, 0):
        raise ValueError("Invalid SIMPLE request CRC")
    return request_id, payload


def encode_response(payload: bytes, request_id: int, limit: int) -> list[bytes]:
    """Echo the request ID in ordered RESPONSE packets, each at most limit bytes.

    CRC covers the full body before fragmentation. Every packet has status 0
    and ACK disabled. Indices stay within the client's signed-byte range.
    """
    if not isinstance(payload, bytes) or not 2 <= len(payload) <= 65537:
        raise ValueError("SIMPLE response requires SID/CID and at most 65535 body bytes")
    if type(request_id) is not int or not 0 <= request_id <= 65535:
        raise ValueError("SIMPLE request ID must be an integer from 0 to 65535")
    if type(limit) is not int or limit < 8:
        raise ValueError("SIMPLE packet limit must be an integer of at least 8")
    capacity = limit - 7
    data_length = len(payload)  # body + CRC has the same size as SID/CID + body.
    count = (data_length + capacity - 1) // capacity
    if count > 128:
        raise ValueError("SIMPLE response exceeds 128 fragments at this packet limit")
    data = payload[2:] + _crc(payload, request_id, 1)
    prefix = request_id.to_bytes(2, "little") + b"\x01"
    return [prefix + bytes([count - 1, index]) + payload[:2]
            + data[index * capacity:(index + 1) * capacity]
            for index in range(count)]
