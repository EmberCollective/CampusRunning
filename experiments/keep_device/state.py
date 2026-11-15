"""Single-process B3/B5 state and bounded queries; cloud binding remains unknown."""

import argparse
import json
import os
import re
import tempfile
from pathlib import Path

from google.protobuf import descriptor_pb2, descriptor_pool, message_factory
from google.protobuf.message import DecodeError

from .btcp import UnsupportedRequest


def _configuration_classes():
    # Recovered packaged schemas: device_sys_time, user_userinfo, mode_conf,
    # device_info (battery), and daily_data (last heart rate).
    schema = descriptor_pb2.FileDescriptorProto(name="keep_lab_config.proto", syntax="proto3")
    for name, fields in (
        ("SysTime", ("utc", "time_zone", "display_type")),
        ("UserInfo", ("height", "weight", "age", "sex", "run_step_len",
                      "walk_step_len", "max_hr", "rest_hr", "is_vip", "wear_hand",
                      "run_step_len_source", "walk_step_len_source")),
        ("ModeConfig", ("start_utc", "end_utc", "mode_switch", "mode_type")),
        ("BatteryInfo", ("voltage", "level", "temp")),
        ("LastHr", ("hr",)),
        ("MsgRemindSwitch", ("msg_type", "msg_switch")),
        ("HrRemindSwitch", ("hr_warn_value", "hr_warn_switch")),
        ("StepsGoal", ("step_remind_switch", "step_goal")),
        ("ExerciseTimeGoal", ("exercise_time_remind_switch", "exercise_time_goal_class", "exercise_time_goal")),
        ("AutoMotionRecogCfg", ("enable", "interval_min", "time_threshold")),
        ("MorningNotify", ("enable", "time_start", "time_end", "notify_str")),
        ("DoubleRingNotify", ("enable", "calories_goal", "time_goal", "back_start_time", "back_end_time",
                              "limit_step", "limit_both_goal_good", "limit_both_goal_better",
                              "afternoon_remind_time", "evening_remind_time")),
        ("FatburningNotifyControl", ("enable",)),
        ("DailySpo2Enable", ("enable",)),
        ("WorkoutAbConfig", ("virtual_hr_enable", "aee_sync_enable")),
        ("ABTestInfo", ("sport_act_switch", "reserved_switch")),
        ("HRLevelsInfo", ("hr_max_lv1", "hr_max_lv2", "hr_max_lv3", "hr_max_lv4", "hr_max_lv5", "hr_max_lv6")),
        ("MonthlyMileageInfo", ("distance",)),
        ("SportAutoPauseItem", ("period", "threshold", "cycle", "count")),
    ):
        message = schema.message_type.add(name=name)
        for number, field in enumerate(fields, 1):
            message.field.add(
                name=field, number=number,
                label=descriptor_pb2.FieldDescriptorProto.LABEL_OPTIONAL,
                type=(descriptor_pb2.FieldDescriptorProto.TYPE_BYTES if field in ("notify_str", "reserved_switch")
                      else descriptor_pb2.FieldDescriptorProto.TYPE_INT32 if field in ("time_zone", "temp")
                      else descriptor_pb2.FieldDescriptorProto.TYPE_UINT32),
            )
    field = descriptor_pb2.FieldDescriptorProto
    for name, fields in (
        ("ModeSet", (("mode_conf", 1, "ModeConfig", True),)),
        ("RemindType", (("msg_remind_switch", 1, "MsgRemindSwitch", True),
                        ("hr_remind_switch", 2, "HrRemindSwitch", False),
                        ("sync_data_remind_switch", 3, None, False), ("sport_suggest_switch", 4, None, False))),
        ("CaloriesGoal", (("calories_default_goal", 1, None, False), ("calories_remind_switch", 2, None, False),
                          ("calorie_remind_goal_class", 4, None, False), ("calorie_remind_goal_coming_switch", 5, None, False),
                          ("calorie_remind_base_goal", 6, None, False))),
        ("ExerciseGoal", (("calories", 1, "CaloriesGoal", False), ("steps", 2, "StepsGoal", False),
                          ("sleep", 3, None, False), ("exercise_time", 4, "ExerciseTimeGoal", False),
                          ("health_remind_switch", 5, None, False))),
        ("SportAutoPauseItems", (("sport_walk", 1, "SportAutoPauseItem", False),
                                 ("sport_running", 2, "SportAutoPauseItem", False),
                                 ("sport_count", 3, "SportAutoPauseItem", False),
                                 ("sport_activity", 4, "SportAutoPauseItem", False))),
    ):
        message = schema.message_type.add(name=name)
        for field_name, number, nested, repeated in fields:
            descriptor = message.field.add(
                name=field_name, number=number,
                label=field.LABEL_REPEATED if repeated else field.LABEL_OPTIONAL,
                type=field.TYPE_MESSAGE if nested else field.TYPE_UINT32,
            )
            if nested:
                descriptor.type_name = "." + nested
    pool = descriptor_pool.DescriptorPool()
    pool.Add(schema)
    return {message.name: message_factory.GetMessageClass(pool.FindMessageTypeByName(message.name))
            for message in schema.message_type}


_MESSAGES = _configuration_classes()
_CONFIG = {
    bytes.fromhex(command): (key, _MESSAGES[name]) for command, key, name in (
        ("01 04", "sys_time", "SysTime"), ("02 01", "user_info", "UserInfo"),
        ("02 02", "mode_set", "ModeSet"), ("02 03", "remind_type", "RemindType"),
        ("02 04", "exercise_goal", "ExerciseGoal"), ("02 0b", "auto_config", "AutoMotionRecogCfg"),
        ("02 11", "morning_notify", "MorningNotify"), ("02 13", "double_ring", "DoubleRingNotify"),
        ("02 15", "fatburning_notify", "FatburningNotifyControl"), ("02 19", "spo2_enable", "DailySpo2Enable"),
        ("02 1b", "workout_ab", "WorkoutAbConfig"), ("02 21", "auto_pause", "SportAutoPauseItems"),
        ("02 23", "auto_start", "SportAutoPauseItems"), ("03 10", "monthly_mileage", "MonthlyMileageInfo"),
        ("03 11", "hr_levels", "HRLevelsInfo"), ("13 01", "ab_test", "ABTestInfo"),
    )
}
_ECHO_COMMANDS = {bytes.fromhex(command) for command in ("01 04", "02 02", "02 03", "02 04", "02 21", "02 23")}
# Explicit lab battery model, not a measurement. No heart-rate sample is invented:
# LastHr's default 0 is also the recovered client's null-response fallback.
_QUERIES = {
    b"\x01\x03": _MESSAGES["BatteryInfo"](voltage=4000, level=80, temp=25).SerializeToString(),
    # Empty proto3 messages represent no samples/totals and no installed watchfaces.
    **{bytes.fromhex(command): b"" for command in (
        "03 01", "03 02", "03 03", "03 04", "03 05", "03 06", "03 07", "03 08",
        "03 0a", "03 0b", "03 0c", "03 0d", "03 0e", "08 01",
    )},
}


def _parse_config(message_type, body):
    try:
        message = message_type.FromString(body)
    except DecodeError:
        raise ValueError("Invalid configuration protobuf") from None
    serialized = message.SerializeToString()
    message.DiscardUnknownFields()
    if serialized != message.SerializeToString():
        raise ValueError("Unsupported configuration protobuf fields")
    if message.DESCRIPTOR.name == "MorningNotify" and len(message.notify_str) > 45:
        raise ValueError("Morning notification exceeds the protocol limit")
    return message, serialized


class BindingState:
    """Use one instance per explicitly selected file, shared across connections.

    Duplicate bind reports HAS_BIND as an experiment policy, not a verified
    firmware retry rule. Unbind preserves configuration and does not touch history.
    Concurrent processes must not share a state file.
    """

    def __init__(self, path: str | Path, mac: str):
        if not isinstance(mac, str) or re.fullmatch(r"(?:[0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}", mac) is None:
            raise ValueError("MAC must contain six colon-separated hexadecimal octets")
        self._mac = mac.upper()
        self._path = Path(path)
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            data = {"schema_version": 1, "mac": self._mac, "bound": False, "config": {}}
            self._save(data)
        except (UnicodeError, json.JSONDecodeError):
            raise ValueError("Invalid binding state file") from None
        self._validate(data)
        self._data = data

    @property
    def mac(self) -> str:
        return self._mac

    @property
    def bound(self) -> bool:
        return self._data["bound"]

    def accepts(self, payload: bytes) -> bool:
        """Check shape only, without parsing, writing or changing binding state."""
        return isinstance(payload, bytes) and (
            payload in (b"\x01\x05", b"\x01\x06")
            or payload in _QUERIES
            or (2 <= len(payload) <= 256 and payload[:2] in _CONFIG)
        )

    def reply(self, payload: bytes) -> bytes:
        if not self.accepts(payload):
            raise UnsupportedRequest("Unsupported binding or configuration request")
        command = payload[:2]
        if command in _QUERIES:
            return command + _QUERIES[command]
        if command == b"\x01\x05" and self.bound:
            return command + b"\x08\x01"
        data = {**self._data, "config": dict(self._data["config"])}
        if command in _CONFIG:
            key, message_type = _CONFIG[command]
            message, serialized = _parse_config(message_type, payload[2:])
            if command in (b"\x01\x04", b"\x02\x01"):
                data["config"][key] = {
                    field.name: getattr(message, field.name) for field in message.DESCRIPTOR.fields
                }
            else:
                # Preserve nested/bytes fields without changing the legacy scalar JSON schema.
                data["config"][key] = {"protobuf_hex": serialized.hex()}
            response = command + (serialized if command in _ECHO_COMMANDS else b"\x08\x02")
        else:
            data["bound"] = command == b"\x01\x05"
            response = command + b"\x08\x02"
        self._save(data)
        self._data = data
        return response

    def _validate(self, data):
        if (not isinstance(data, dict)
                or set(data) != {"schema_version", "mac", "bound", "config"}
                or type(data["schema_version"]) is not int or data["schema_version"] != 1
                or type(data["bound"]) is not bool or not isinstance(data["config"], dict)):
            raise ValueError("Invalid binding state schema")
        if data["mac"] != self._mac:
            raise ValueError("Binding state belongs to a different device")
        config_types = {key: message_type for key, message_type in _CONFIG.values()}
        try:
            for key, values in data["config"].items():
                if key not in config_types or not isinstance(values, dict):
                    raise ValueError
                if key not in ("sys_time", "user_info"):
                    if set(values) != {"protobuf_hex"} or not isinstance(values["protobuf_hex"], str):
                        raise ValueError
                    body = bytes.fromhex(values["protobuf_hex"])
                    if len(body) > 254:
                        raise ValueError
                    _parse_config(config_types[key], body)
                else:
                    if any(type(value) is not int for value in values.values()):
                        raise ValueError
                    config_types[key](**values)
        except (ValueError, TypeError, OverflowError):
            raise ValueError("Invalid stored configuration") from None

    def _save(self, data):
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", dir=self._path.parent,
                prefix=f".{self._path.name}.", suffix=".tmp", delete=False,
            ) as output:
                temporary = Path(output.name)
                json.dump(data, output, sort_keys=True, indent=2)
                output.write("\n")
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary, self._path)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description="Explicitly reset local device binding; stop the prototype first.")
    parser.add_argument("--state", required=True, help="Private JSON state file")
    parser.add_argument("--address", required=True, help="MAC belonging to this experiment")
    parser.add_argument("--reset-binding", action="store_true", required=True)
    args = parser.parse_args()
    try:
        BindingState(args.state, args.address).reply(b"\x01\x06")
    except (ValueError, OSError) as error:
        parser.exit(1, f"Local binding reset failed ({type(error).__name__}).\n")
    print("本地设备绑定状态已重置；云端未修改。")


if __name__ == "__main__":
    main()
