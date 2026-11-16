"""File RPC and durable receipt tests; no device or cloud access."""

import hashlib
import json
import logging
import struct
import zlib
from datetime import datetime, timedelta

import pytest
from google.protobuf import descriptor_pb2, descriptor_pool, message_factory, text_format

from experiments.keep_device.btcp import UnsupportedRequest
from experiments.keep_device.files import WorkoutFiles
from experiments.keep_device.history import encode_workout
from experiments.keep_device.simple import encode_response
from src.core.models import ExportData, TrackpointData


@pytest.fixture
def wire():
    # Independent names and fields verify the packaged file_transfer.proto numbers.
    schema = text_format.Parse('''
      name: "file_client_fixture.proto" syntax: "proto3"
      message_type { name: "Entry"
        field { name: "id" number: 1 label: LABEL_OPTIONAL type: TYPE_UINT64 }
        field { name: "size" number: 2 label: LABEL_OPTIONAL type: TYPE_UINT32 }
        field { name: "state" number: 3 label: LABEL_OPTIONAL type: TYPE_UINT32 }
      }
      message_type { name: "Directory"
        field { name: "entries" number: 1 label: LABEL_REPEATED type: TYPE_MESSAGE type_name: "Entry" }
      }
      message_type { name: "Read"
        field { name: "id" number: 1 label: LABEL_OPTIONAL type: TYPE_UINT64 }
        field { name: "count" number: 2 label: LABEL_OPTIONAL type: TYPE_UINT32 }
        field { name: "offset" number: 3 label: LABEL_OPTIONAL type: TYPE_UINT32 }
      }
      message_type { name: "Chunk"
        field { name: "state" number: 1 label: LABEL_OPTIONAL type: TYPE_UINT32 }
        field { name: "data" number: 2 label: LABEL_OPTIONAL type: TYPE_BYTES }
      }
      message_type { name: "Delete"
        field { name: "kind" number: 1 label: LABEL_OPTIONAL type: TYPE_UINT32 }
        field { name: "id" number: 2 label: LABEL_OPTIONAL type: TYPE_UINT64 }
      }
      message_type { name: "Status"
        field { name: "state" number: 1 label: LABEL_OPTIONAL type: TYPE_UINT32 }
      }
    ''', descriptor_pb2.FileDescriptorProto())
    pool = descriptor_pool.DescriptorPool()
    pool.Add(schema)
    return {name: message_factory.GetMessageClass(pool.FindMessageTypeByName(name))
            for name in ("Directory", "Read", "Chunk", "Delete", "Status")}


@pytest.fixture
def source(tmp_path):
    start = datetime(2026, 9, 4, 7)
    points = [TrackpointData(
        (start + timedelta(seconds=index * 5)).isoformat(), 26.44 + index * .0001,
        106.67, 100, index * 12.5, 80, 2.5,
    ) for index in range(20)]
    data = ExportData(start.date(), start, .2375, 95, 20, points)
    path = tmp_path / "activity.sport44"
    path.write_bytes(encode_workout(data))
    return path


def _entry(files, wire):
    response = files.reply(bytes.fromhex("06 01 08 2c"))
    assert response[:2] == b"\x06\x01"
    entries = wire["Directory"].FromString(response[2:]).entries
    assert len(entries) == 1
    return entries[0]


def test_no_workout_answers_empty_sync_without_touching_files(tmp_path, monkeypatch, wire):
    monkeypatch.chdir(tmp_path)
    files = WorkoutFiles(None)
    for kind in (1, 2, 3, 4, 5, 6, 35, 36, 37, 41, 42, 43, 44, 45, 47):
        for _ in range(2):
            assert files.reply(b"\x06\x01\x08" + bytes([kind])) == b"\x06\x01"
            assert files.reply(b"\x06\x03\x08" + bytes([kind])) == b"\x06\x03"
        for file_id in (0, 1, 2**64 - 1):
            request = wire["Delete"](kind=kind, id=file_id)
            response = files.reply(b"\x06\x07" + request.SerializeToString())
            assert wire["Status"].FromString(response[2:]).state == 2
            request = wire["Read"](id=file_id, count=512)
            response = files.reply(b"\x06\x02" + request.SerializeToString())
            chunk = wire["Chunk"].FromString(response[2:])
            assert chunk.state == 2 and chunk.data == b""
    with pytest.raises(UnsupportedRequest):
        files.reply(bytes.fromhex("06 01 08 7f"))
    with pytest.raises(ValueError):
        files.reply(bytes.fromhex("06 01 08"))
    assert list(tmp_path.iterdir()) == []


def test_directory_and_chunked_read_reassemble_exact_source(source, wire):
    files = WorkoutFiles(source)
    assert files.reply(bytes.fromhex("06 01 08 06")) == b"\x06\x01"
    entry = _entry(files, wire)
    original = source.read_bytes()
    assert entry.size == len(original)
    assert entry.id == int.from_bytes(hashlib.sha256(original).digest()[:8], "big")
    assert _entry(WorkoutFiles(source), wire).id == entry.id
    received = bytearray()
    lengths = []
    while len(received) < entry.size:
        request = wire["Read"](id=entry.id, count=2048, offset=len(received))
        reply = files.reply(b"\x06\x02" + request.SerializeToString())
        assert reply[:2] == b"\x06\x02"
        chunk = wire["Chunk"].FromString(reply[2:])
        assert chunk.state == 0 and 0 < len(chunk.data) <= 512
        packets = encode_response(reply, request_id=63, limit=20)
        assert len(packets) <= 128 and all(len(packet) <= 20 for packet in packets)
        received.extend(chunk.data)
        lengths.append(len(chunk.data))
    assert received == original
    assert lengths[:2] == [512, 512] and lengths[-1] < 512
    assert not source.with_name(source.name + ".received.json").exists()


def test_small_requested_length_is_respected(source, wire):
    files = WorkoutFiles(source)
    entry = _entry(files, wire)
    request = wire["Read"](id=entry.id, count=3, offset=2)
    chunk = wire["Chunk"].FromString(files.reply(b"\x06\x02" + request.SerializeToString())[2:])
    assert chunk.state == 0 and chunk.data == source.read_bytes()[2:5]


@pytest.mark.parametrize("single", [False, True])
def test_diagnostics_only_log_safe_metadata(source, wire, caplog, single):
    files = WorkoutFiles(source)
    caplog.set_level(logging.INFO, logger="experiments.keep_device.files")
    entry = _entry(files, wire)
    request = b"\x06\x02" + wire["Read"](id=entry.id, count=2048, offset=512).SerializeToString()
    files.reply(request)
    files.reply(bytes.fromhex("06 03 08 03"))
    command = (b"\x06\x07" + wire["Delete"](kind=44, id=entry.id).SerializeToString()
               if single else bytes.fromhex("06 03 08 2c"))
    files.reply(command)
    with pytest.raises(UnsupportedRequest):
        files.reply(bytes.fromhex("06 01 08 7f"))
    messages = [record.getMessage() for record in caplog.records]
    assert messages == [
        "file_transfer command=6/1 type=44 entries=1",
        "file_transfer command=6/2 offset=512 requested_length=2048 returned_length=512 status=0",
        "file_transfer command=6/3 type=3 entries=0",
        "workout_receipt received=true",
        ("file_transfer command=6/7 type=44 status=1" if single
         else "file_transfer command=6/3 type=44 entries=1"),
        "file_transfer command=6/1 type=127 unsupported=true",
    ]
    # Check both formatted logs and captured arguments, which handlers may serialize.
    captured = "\n".join(messages) + repr([record.args for record in caplog.records])
    for private in (str(source), source.name, str(entry.id), format(entry.id, "x"),
                    request.hex(), repr(request), "26.44", "106.67"):
        assert private not in captured


@pytest.mark.parametrize("single", [False, True])
def test_delete_marks_receipt_restart_hides_queue_and_keeps_source(source, wire, single):
    original = source.read_bytes()
    files = WorkoutFiles(source)
    entry = _entry(files, wire)
    command = (b"\x06\x07" + wire["Delete"](kind=44, id=entry.id).SerializeToString()
               if single else bytes.fromhex("06 03 08 2c"))
    response = files.reply(command)
    if single:
        assert wire["Status"].FromString(response[2:]).state == 1
    else:
        deleted, = wire["Directory"].FromString(response[2:]).entries
        assert (deleted.id, deleted.size, deleted.state) == (entry.id, len(original), 1)
    assert response[:2] == command[:2]
    marker_path = source.with_name(source.name + ".received.json")
    marker = json.loads(marker_path.read_text())
    assert marker == {"schema_version": 1, "sha256": hashlib.sha256(original).hexdigest(),
                      "uuid": entry.id, "received": True}
    assert source.read_bytes() == original
    restarted = WorkoutFiles(source)
    assert restarted.reply(bytes.fromhex("06 01 08 2c")) == b"\x06\x01"
    assert restarted.reply(command) == response
    request = wire["Read"](id=entry.id, count=512)
    chunk = wire["Chunk"].FromString(restarted.reply(b"\x06\x02" + request.SerializeToString())[2:])
    assert chunk.state == 2 and chunk.data == b""


@pytest.mark.parametrize("kind", [1, 2, 3, 4, 5, 6, 35, 36, 37, 41, 42, 43, 45, 47])
def test_empty_directories_do_not_receive_plus_file(source, wire, kind):
    files = WorkoutFiles(source)
    entry = _entry(files, wire)
    original = source.read_bytes()
    assert files.reply(b"\x06\x01\x08" + bytes([kind])) == b"\x06\x01"
    # No files means an empty FileStatusSum, not a fictitious deleted entry.
    assert files.reply(b"\x06\x03\x08" + bytes([kind])) == b"\x06\x03"
    request = wire["Delete"](kind=kind, id=entry.id)
    response = files.reply(b"\x06\x07" + request.SerializeToString())
    assert wire["Status"].FromString(response[2:]).state == 2
    assert _entry(files, wire).id == entry.id
    assert source.read_bytes() == original
    assert not source.with_name(source.name + ".received.json").exists()


@pytest.mark.parametrize("case", ["uuid", "eof", "past_eof", "zero_length"])
def test_invalid_read_has_failure_status_and_no_data(source, wire, case):
    files = WorkoutFiles(source)
    entry = _entry(files, wire)
    request = wire["Read"](id=entry.id, count=2048)
    if case == "uuid":
        request.id ^= 1
    elif case == "zero_length":
        request.count = 0
    else:
        request.offset = entry.size + (case == "past_eof")
    chunk = wire["Chunk"].FromString(files.reply(b"\x06\x02" + request.SerializeToString())[2:])
    assert chunk.state != 0 and chunk.data == b""


@pytest.mark.parametrize("kind, wrong_id", [(6, False), (44, True)])
def test_wrong_delete_never_hides_file(source, wire, kind, wrong_id):
    files = WorkoutFiles(source)
    entry = _entry(files, wire)
    request = wire["Delete"](kind=kind, id=entry.id ^ wrong_id)
    response = files.reply(b"\x06\x07" + request.SerializeToString())
    assert wire["Status"].FromString(response[2:]).state == 2
    assert _entry(files, wire).id == entry.id
    assert not source.with_name(source.name + ".received.json").exists()


@pytest.mark.parametrize("command", [b"\x06\x01", b"\x06\x02", b"\x06\x03", b"\x06\x07"])
@pytest.mark.parametrize("body", [b"\x08", b"\x00", b"\x0a\x01\x2c", b"\x78\x01"])
def test_malformed_or_unknown_fields_are_rejected_without_receipt(source, command, body):
    files = WorkoutFiles(source)
    assert files.accepts(command + body)
    with pytest.raises(ValueError):
        files.reply(command + body)
    assert not source.with_name(source.name + ".received.json").exists()


@pytest.mark.parametrize("payload", [b"", b"\x06", b"\x06\x04", b"\x01\x05",
                                     b"\x06\x01" + bytes(63), "not bytes"])
def test_unknown_shapes_are_not_accepted(source, payload):
    files = WorkoutFiles(source)
    assert not files.accepts(payload)
    with pytest.raises(UnsupportedRequest):
        files.reply(payload)


@pytest.mark.parametrize("command", [b"\x06\x01", b"\x06\x03", b"\x06\x07"])
@pytest.mark.parametrize("kind", [0, 7, 34, 46, 127])
def test_unknown_file_type_is_not_reported_as_empty_success(source, command, kind):
    files = WorkoutFiles(source)
    with pytest.raises(UnsupportedRequest):
        files.reply(command + b"\x08" + bytes([kind]))
    assert not source.with_name(source.name + ".received.json").exists()


def test_invalid_crc_and_outer_length_are_rejected_without_marker(source):
    original = source.read_bytes()
    source.write_bytes(b"\xff" + original[1:])
    with pytest.raises(ValueError, match="CRC32"):
        WorkoutFiles(source)
    malformed = bytearray(original[:-4])
    struct.pack_into("<h", malformed, len(malformed) - 10, 32767)
    source.write_bytes(malformed + struct.pack("<I", zlib.crc32(malformed)))
    with pytest.raises(ValueError, match="description length"):
        WorkoutFiles(source)
    assert not source.with_name(source.name + ".received.json").exists()


@pytest.mark.parametrize("content", ["{", "[]", "{}", '{"schema_version":true}',
                                      '{"schema_version":1,"sha256":"x","uuid":1,"received":false}'])
def test_corrupt_marker_is_not_overwritten(source, content):
    marker = source.with_name(source.name + ".received.json")
    marker.write_text(content)
    with pytest.raises(ValueError, match="marker"):
        WorkoutFiles(source)
    assert marker.read_text() == content


def test_changed_file_cannot_be_hidden_by_old_marker(source):
    WorkoutFiles(source).reply(bytes.fromhex("06 03 08 2c"))
    marker = source.with_name(source.name + ".received.json")
    before = marker.read_bytes()
    changed = bytearray(source.read_bytes()[:-4])
    changed[4] ^= 1
    source.write_bytes(changed + struct.pack("<I", zlib.crc32(changed)))
    with pytest.raises(ValueError, match="different file contents"):
        WorkoutFiles(source)
    assert marker.read_bytes() == before


@pytest.mark.parametrize("single", [False, True])
def test_marker_write_failure_never_acknowledges_or_hides_file(source, wire, monkeypatch, caplog, single):
    files = WorkoutFiles(source)
    entry = _entry(files, wire)
    before = source.read_bytes()
    command = (b"\x06\x07" + wire["Delete"](kind=44, id=entry.id).SerializeToString()
               if single else bytes.fromhex("06 03 08 2c"))

    def fail_replace(*args):
        raise PermissionError("simulated marker failure")

    monkeypatch.setattr("experiments.keep_device.files.os.replace", fail_replace)
    caplog.set_level(logging.INFO, logger="experiments.keep_device.files")
    with pytest.raises(PermissionError):
        files.reply(command)
    assert caplog.records == []  # No successful receipt/deletion before durable storage.
    assert source.read_bytes() == before
    assert not source.with_name(source.name + ".received.json").exists()
    assert not list(source.parent.glob("*.tmp"))
    assert _entry(files, wire).id == entry.id
    assert _entry(WorkoutFiles(source), wire).id == entry.id
