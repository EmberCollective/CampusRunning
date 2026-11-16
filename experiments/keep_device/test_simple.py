"""Independent SIMPLE wire fixtures; these are computed examples, not captures."""

import struct

import pytest

from experiments.keep_device.btcp import DeviceInfoSession, UnsupportedRequest
from experiments.keep_device.simple import decode_request, encode_response


def reference_crc(data):
    """Bitwise polynomial calculation, independent of production crc_hqx."""
    crc = 0
    for byte in data:
        crc ^= byte << 8
        for _ in range(8):
            crc = ((crc << 1) ^ (0x1021 if crc & 0x8000 else 0)) & 0xFFFF
    return struct.pack("<H", crc)


def request_packet(request_id, payload):
    sid, cid = payload[:2]
    body = payload[2:]
    crc_header = struct.pack("<HBHBB", request_id, 0, len(body), sid, cid)
    wire_header = struct.pack("<HBBBBB", request_id, 0, 0, 0, sid, cid)
    return wire_header + body + reference_crc(crc_header + body)


def test_fixed_examples_and_known_crc_vector():
    assert reference_crc(b"123456789") == bytes.fromhex("c3 31")
    # ID 0x1234, request 1/2 body 03 03; CRC input uses body length 02 00.
    packet = bytes.fromhex("34 12 00 00 00 01 02 03 03 5b 2c")
    assert reference_crc(bytes.fromhex("34 12 00 02 00 01 02 03 03")) == b"\x5b\x2c"
    assert decode_request(packet) == (0x1234, b"\x01\x02\x03\x03")
    assert decode_request(bytes.fromhex("ef be 00 00 00 01 05 91 8a")) == (0xBEEF, b"\x01\x05")
    # ID is echoed; RESPONSE type 1 changes the CRC domain.
    assert encode_response(b"\x01\x05\x08\x02", 0x1234, 20) == [
        bytes.fromhex("34 12 01 00 00 01 05 08 02 71 dd")
    ]
    assert encode_response(b"\x01\x02", 0, 9) == [bytes.fromhex("00 00 01 00 00 01 02 22 b9")]


def test_b5_device_info_query_without_body_returns_the_same_identity():
    session = DeviceInfoSession("C1:23:45:67:89:AB", model="B5")
    full = session.reply_packets(request_packet(0x1234, b"\x01\x02\x03\x03"), 244)
    empty = session.reply_packets(request_packet(0x1234, b"\x01\x02"), 244)
    assert empty == full
    assert b"KeepB5 Lab" in empty[0] and b"LABC123456789AB" in empty[0]


@pytest.mark.parametrize("body", [b"\x03", b"\x03\x04", b"\x03\x03\x00"])
def test_b5_device_info_query_rejects_unknown_bodies(body):
    session = DeviceInfoSession("C1:23:45:67:89:AB", model="B5")
    with pytest.raises(UnsupportedRequest):
        session.reply_packets(request_packet(0x1234, b"\x01\x02" + body), 244)


@pytest.mark.parametrize("request_id", [0, 32767, 32768, 65535])
def test_request_id_full_16_bit_range(request_id):
    assert decode_request(request_packet(request_id, b"\x02\x01\x08\x01")) == (
        request_id, b"\x02\x01\x08\x01",
    )


@pytest.mark.parametrize("offset", [0, 1, 5, 6, 7, 9, 10])
def test_changed_identity_command_body_or_crc_is_rejected(offset):
    packet = bytearray.fromhex("34 12 00 00 00 01 02 03 03 5b 2c")
    packet[offset] ^= 1
    with pytest.raises(ValueError, match="CRC"):
        decode_request(bytes(packet))


@pytest.mark.parametrize("header", [b"\x01\x00\x00", b"\x02\x00\x00", b"\x03\x00\x00",
                                    b"\x08\x00\x00", b"\x10\x00\x00", b"\x80\x00\x00",
                                    b"\x00\x01\x00", b"\x00\x00\x01", b"\x00\x80\x80"])
def test_response_push_ack_status_and_fragmented_requests_are_unsupported(header):
    packet = bytes.fromhex("34 12 00 00 00 01 02 03 03 5b 2c")
    with pytest.raises(UnsupportedRequest):
        decode_request(packet[:2] + header + packet[5:])


@pytest.mark.parametrize("packet", [b"", bytes(8), bytes(65545), "not-bytes"],
                         ids=["empty", "short", "oversize", "wrong-type"])
def test_invalid_request_size_or_type(packet):
    with pytest.raises(ValueError):
        decode_request(packet)


@pytest.mark.parametrize("limit,size", [(8, 0), (9, 0), (20, 11), (20, 12), (244, 2048), (1024, 65535)])
def test_response_fragments_reassemble_to_one_checksum(limit, size):
    body = bytes(index % 256 for index in range(size))
    packets = encode_response(b"\x01\x0a" + body, 0xFEDC, limit)
    for index, packet in enumerate(packets):
        assert 8 <= len(packet) <= limit
        assert struct.unpack("<HBBBBB", packet[:7]) == (
            0xFEDC, 1, len(packets) - 1, index, 1, 10,
        )
    data = b"".join(packet[7:] for packet in packets)
    assert data[:-2] == body
    assert data[-2:] == reference_crc(struct.pack("<HBHBB", 0xFEDC, 1, size, 1, 10) + body)
    assert len(packets) == (size + 2 + limit - 8) // (limit - 7)


def test_signed_fragment_index_boundary():
    packets = encode_response(b"\x01\x0a" + bytes(126), 65535, 8)
    assert len(packets) == 128 and packets[-1][3:5] == b"\x7f\x7f"
    with pytest.raises(ValueError, match="128 fragments"):
        encode_response(b"\x01\x0a" + bytes(127), 0, 8)


@pytest.mark.parametrize("peer_limit", [20, 244, 512, 514])
def test_b5_file_response_uses_client_protocol_limit_and_reassembles(peer_limit):
    # File.file_data tag 2, length 512; status 0 is omitted by proto3.
    body = b"\x12\x80\x04" + bytes(index % 256 for index in range(512))

    class FileReply:
        def accepts(self, payload):
            return payload == b"\x06\x02"

        def reply(self, payload):
            return payload + body

    request_id = 0x1234
    session = DeviceInfoSession("C1:23:45:67:89:AB", model="B5", workout=FileReply())
    packets = session.reply_packets(request_packet(request_id, b"\x06\x02"), peer_limit)
    assert all(len(packet) <= min(peer_limit, 244) for packet in packets)
    if peer_limit >= 244:
        assert [len(packet) for packet in packets] == [244, 244, 50]
    # Mirror only the recovered receiver's rules: identity match, index slots,
    # callback on last index, whole-message CRC, then remove the final two bytes.
    slots = {}
    for packet in packets:
        identity, flags, last, current, sid, cid = struct.unpack("<HBBBBB", packet[:7])
        assert (identity, flags, sid, cid) == (request_id, 1, 6, 2)
        slots[current] = packet[7:]
        if current == last:
            assert set(slots) == set(range(last + 1))
            received = b"".join(slots[index] for index in range(last + 1))
            assert received[:-2] == body
            assert received[-2:] == reference_crc(struct.pack("<HBHBB", request_id, 1, len(body), 6, 2) + body)


@pytest.mark.parametrize("request_id", [-1, 65536, True, 1.0, None])
def test_invalid_response_request_id(request_id):
    with pytest.raises(ValueError, match="request ID"):
        encode_response(b"\x01\x02", request_id, 20)


@pytest.mark.parametrize("limit", [-1, 0, 7, True, 20.0, None])
def test_invalid_packet_limit(limit):
    with pytest.raises(ValueError, match="packet limit"):
        encode_response(b"\x01\x02", 0, limit)


@pytest.mark.parametrize("payload", [b"", b"\x01", bytes(65538), "not-bytes"],
                         ids=["empty", "missing-cid", "oversize", "wrong-type"])
def test_invalid_response_payload(payload):
    with pytest.raises(ValueError, match="SID/CID"):
        encode_response(payload, 0, 244)
