"""Single-file SPORT44 RPC candidate; receipt is not proof of cloud upload.

Keep the selected file and its .received.json marker in a private LAB directory.
Use one process per file. Deletion commands persist receipt and hide the queue
entry, while preserving the source bytes. The UUID is an experimental SHA-256
identifier, not the hardware timestamp/type/battery encoding.
Known daily-data and telemetry directories are empty; no records are made up.
"""

import hashlib
import json
import logging
import os
import struct
import tempfile
import zlib
from pathlib import Path

from google.protobuf import descriptor_pb2, descriptor_pool, message_factory
from google.protobuf.message import DecodeError

from .btcp import UnsupportedRequest


_LOGGER = logging.getLogger(__name__)


def _file_classes():
    field = descriptor_pb2.FieldDescriptorProto
    uint32, uint64, byte_string = field.TYPE_UINT32, field.TYPE_UINT64, field.TYPE_BYTES
    definitions = (
        ("FileType", (("type", 1, uint32),)),
        ("FileTable", (("uuid", 1, uint64), ("file_size", 2, uint32))),
        ("FileSum", (("file_table", 1, "FileTable"),)),
        ("GetFileReq", (("uuid", 1, uint64), ("len", 2, uint32), ("offset", 3, uint32))),
        ("File", (("status", 1, uint32), ("file_data", 2, byte_string))),
        ("FileStatusTable", (("uuid", 1, uint64), ("file_size", 2, uint32), ("status", 3, uint32))),
        ("FileStatusSum", (("file_status_table", 1, "FileStatusTable"),)),
        ("DelOneFile", (("type", 1, uint32), ("uuid", 2, uint64))),
        ("DelOneFileStatus", (("status", 1, uint32),)),
    )
    schema = descriptor_pb2.FileDescriptorProto(
        name="keep_lab_files.proto", package="keep_lab_files", syntax="proto3",
    )
    for name, fields in definitions:
        message = schema.message_type.add(name=name)
        for field_name, number, kind in fields:
            repeated_message = isinstance(kind, str)
            descriptor = message.field.add(
                name=field_name, number=number,
                label=field.LABEL_REPEATED if repeated_message else field.LABEL_OPTIONAL,
                type=field.TYPE_MESSAGE if repeated_message else kind,
            )
            if repeated_message:
                descriptor.type_name = f".keep_lab_files.{kind}"
    pool = descriptor_pool.DescriptorPool()
    pool.Add(schema)
    return {
        name: message_factory.GetMessageClass(pool.FindMessageTypeByName(f"keep_lab_files.{name}"))
        for name, _ in definitions
    }


_MESSAGES = _file_classes()
_REQUESTS = {
    b"\x06\x01": _MESSAGES["FileType"],
    b"\x06\x02": _MESSAGES["GetFileReq"],
    b"\x06\x03": _MESSAGES["FileType"],
    b"\x06\x07": _MESSAGES["DelOneFile"],
}
# KitbitCommonDataService's date-based reads use these GetFileType values.
# Kitbit3FileHelper accepts an empty FileSum as "no data for this day".
_DAILY_FILE_TYPES = frozenset((1, 2, 3, 4, 5, 35, 36, 41, 42, 43, 45, 47))
# B3BuriedPointSyncHandler also accepts an empty BURIED_POINT (37) directory.
_DIRECTORY_TYPES = _DAILY_FILE_TYPES | {6, 37, 44}


class WorkoutFiles:
    """Serve an optional immutable snapshot; None exposes empty directories."""

    def __init__(self, path: Path | None):
        self._uuid = None
        self._file = b""
        self._received = False
        if path is None:
            return
        path = Path(path)
        if not 14 <= path.stat().st_size <= (1 << 31) - 1:
            raise ValueError("Unsupported workout file size")
        self._file = path.read_bytes()
        if zlib.crc32(self._file[:-4]) != struct.unpack_from("<I", self._file, len(self._file) - 4)[0]:
            raise ValueError("Invalid workout file CRC32")
        description_length = struct.unpack_from("<h", self._file, len(self._file) - 14)[0]
        if not 28 <= description_length < len(self._file) - 14:
            raise ValueError("Invalid SPORT44 description length")
        digest = hashlib.sha256(self._file)
        self._digest = digest.hexdigest()
        self._uuid = int.from_bytes(digest.digest()[:8], "big")
        self._marker = path.with_name(path.name + ".received.json")
        try:
            marker = json.loads(self._marker.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return
        except (UnicodeError, json.JSONDecodeError):
            raise ValueError("Invalid workout receipt marker") from None
        if (not isinstance(marker, dict)
                or set(marker) != {"schema_version", "sha256", "uuid", "received"}
                or type(marker["schema_version"]) is not int or marker["schema_version"] != 1
                or marker["received"] is not True or type(marker["uuid"]) is not int):
            raise ValueError("Invalid workout receipt marker schema")
        if marker["sha256"] != self._digest or marker["uuid"] != self._uuid:
            raise ValueError("Workout receipt marker belongs to different file contents")
        self._received = True

    def accepts(self, payload: bytes) -> bool:
        """Route supported command shapes without parsing or changing the queue."""
        return isinstance(payload, bytes) and 2 <= len(payload) <= 64 and payload[:2] in _REQUESTS

    def reply(self, payload: bytes) -> bytes:
        if not self.accepts(payload):
            raise UnsupportedRequest("Unsupported file-transfer request")
        command = payload[:2]
        try:
            request = _REQUESTS[command].FromString(payload[2:])
        except DecodeError:
            raise ValueError("Invalid file-transfer protobuf") from None
        serialized = request.SerializeToString()
        request.DiscardUnknownFields()
        if serialized != request.SerializeToString():
            raise ValueError("Unsupported file-transfer protobuf fields")
        if command != b"\x06\x02" and request.type not in _DIRECTORY_TYPES:
            _LOGGER.info("file_transfer command=6/%d type=%d unsupported=true", command[1], request.type)
            raise UnsupportedRequest("Unsupported file directory type")

        if command == b"\x06\x02":
            response = _MESSAGES["File"]()
            if request.uuid != self._uuid or self._received:
                response.status = 2  # File does not exist in the pending queue.
            elif request.len == 0 or request.offset >= len(self._file):
                response.status = 1
            else:
                # 512 data bytes fit comfortably under 128 SIMPLE fragments at MTU 23.
                end = request.offset + min(request.len, 512)
                response.file_data = self._file[request.offset:end]
            _LOGGER.info(
                "file_transfer command=6/2 offset=%d requested_length=%d returned_length=%d status=%d",
                request.offset, request.len, len(response.file_data), response.status,
            )
        elif command == b"\x06\x07":
            response = _MESSAGES["DelOneFileStatus"](status=2)
            if request.type == 44 and request.uuid == self._uuid:
                self._receive()
                response.status = 1
            _LOGGER.info("file_transfer command=6/7 type=%d status=%d", request.type, response.status)
        else:
            if command == b"\x06\x01":
                response = _MESSAGES["FileSum"]()
                if request.type == 44 and self._uuid is not None and not self._received:
                    response.file_table.add(uuid=self._uuid, file_size=len(self._file))
                _LOGGER.info("file_transfer command=6/1 type=%d entries=%d", request.type, len(response.file_table))
            else:
                response = _MESSAGES["FileStatusSum"]()
                if request.type == 44 and self._uuid is not None:
                    self._receive()
                    response.file_status_table.add(uuid=self._uuid, file_size=len(self._file), status=1)
                _LOGGER.info(
                    "file_transfer command=6/3 type=%d entries=%d",
                    request.type, len(response.file_status_table),
                )
        return command + response.SerializeToString()

    def _receive(self):
        if self._received:
            return
        marker = {"schema_version": 1, "sha256": self._digest, "uuid": self._uuid, "received": True}
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", dir=self._marker.parent,
                prefix=f".{self._marker.name}.", suffix=".tmp", delete=False,
            ) as output:
                temporary = Path(output.name)
                json.dump(marker, output, sort_keys=True, indent=2)
                output.write("\n")
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary, self._marker)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
        self._received = True
        _LOGGER.info("workout_receipt received=true")
