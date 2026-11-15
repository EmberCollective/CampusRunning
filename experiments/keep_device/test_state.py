"""Persistent business-state checks, without Bluetooth or account access."""

import json
import subprocess
import sys

import pytest
from google.protobuf import descriptor_pb2, descriptor_pool, message_factory, text_format

from experiments.keep_device.btcp import UnsupportedRequest
from experiments.keep_device.state import BindingState


MAC = "C1:23:45:67:89:AB"
BIND = b"\x01\x05"
UNBIND = b"\x01\x06"
USER = bytes.fromhex("02 01 08 af 01 10 46 18 1e")  # 175cm, 70kg, 30 years.


def test_bind_restart_unbind_rebind_preserves_configuration_and_history(tmp_path):
    path = tmp_path / "state.json"
    history = tmp_path / "history.json"
    history.write_text('[{"record": 1}]')
    state = BindingState(path, MAC.lower())
    assert state.mac == MAC and not state.bound
    assert state.reply(USER) == bytes.fromhex("02 01 08 02")
    config = json.loads(path.read_text())["config"]
    assert config["user_info"]["height"] == 175
    assert state.reply(BIND) == BIND + b"\x08\x02"
    restarted = BindingState(path, MAC)
    assert restarted.bound
    assert restarted.reply(BIND) == BIND + b"\x08\x01"
    assert restarted.reply(UNBIND) == UNBIND + b"\x08\x02"
    assert not BindingState(path, MAC).bound
    assert json.loads(path.read_text())["config"] == config
    assert history.read_text() == '[{"record": 1}]'
    assert restarted.reply(BIND) == BIND + b"\x08\x02"


def test_time_echo_and_storage_use_signed_minutes(tmp_path):
    schema = text_format.Parse('''
        name: "time_fixture.proto" syntax: "proto3"
        message_type { name: "Clock"
          field { name: "utc" number: 1 label: LABEL_OPTIONAL type: TYPE_UINT32 }
          field { name: "offset" number: 2 label: LABEL_OPTIONAL type: TYPE_INT32 }
          field { name: "display" number: 3 label: LABEL_OPTIONAL type: TYPE_UINT32 }
        }
    ''', descriptor_pb2.FileDescriptorProto())
    pool = descriptor_pool.DescriptorPool()
    pool.Add(schema)
    clock_type = message_factory.GetMessageClass(pool.FindMessageTypeByName("Clock"))
    clock = clock_type(utc=1700000000, offset=-60, display=1)
    path = tmp_path / "state.json"
    response = BindingState(path, MAC).reply(b"\x01\x04" + clock.SerializeToString())
    assert response[:2] == b"\x01\x04"
    assert clock_type.FromString(response[2:]) == clock
    assert json.loads(path.read_text())["config"]["sys_time"] == {
        "utc": 1700000000, "time_zone": -60, "display_type": 1,
    }
    assert not BindingState(path, MAC).bound


@pytest.mark.parametrize("bound,payload", [(False, BIND), (True, UNBIND), (False, USER),
                                         (False, bytes.fromhex("02 02 0a 04 18 01 20 01"))])
def test_write_failure_never_reports_success_or_changes_state(tmp_path, monkeypatch, bound, payload):
    path = tmp_path / "state.json"
    state = BindingState(path, MAC)
    if bound:
        state.reply(BIND)
    before = path.read_bytes()

    def fail_replace(*args):
        raise PermissionError("simulated write failure")

    monkeypatch.setattr("experiments.keep_device.state.os.replace", fail_replace)
    with pytest.raises(PermissionError):
        state.reply(payload)
    assert state.bound is bound
    assert path.read_bytes() == before
    assert not list(tmp_path.glob("*.tmp"))


@pytest.mark.parametrize("body", [b"\x08", b"\x00", b"\x0a\x01\x01", b"\x78\x01"])
@pytest.mark.parametrize("command", [b"\x01\x04", b"\x02\x01"])
def test_malformed_or_unknown_protobuf_does_not_change_state(tmp_path, command, body):
    path = tmp_path / "state.json"
    state = BindingState(path, MAC)
    before = path.read_bytes()
    assert state.accepts(command + body)
    with pytest.raises(ValueError):
        state.reply(command + body)
    assert path.read_bytes() == before and not state.bound


@pytest.mark.parametrize("payload", [b"", b"\x01", BIND + b"\x00", UNBIND + b"\x00",
                                     b"\x02\x05", b"\x01\x04" + bytes(255),
                                     b"\x01\x03\x00", b"\x03\x07\x00"])
def test_accepts_is_side_effect_free_and_rejects_unsupported_shapes(tmp_path, payload):
    path = tmp_path / "state.json"
    state = BindingState(path, MAC)
    before = path.read_bytes()
    assert state.accepts(BIND) and state.accepts(UNBIND)
    assert state.accepts(b"\x01\x04" + bytes(254))
    assert not state.accepts(payload)
    with pytest.raises(UnsupportedRequest):
        state.reply(payload)
    assert path.read_bytes() == before and not state.bound


@pytest.mark.parametrize("content", ["{", "[]", '{"schema_version": 1}',
    json.dumps({"schema_version": True, "mac": MAC, "bound": False, "config": {}}),
    json.dumps({"schema_version": 1, "mac": MAC, "bound": 1, "config": {}}),
    json.dumps({"schema_version": 1, "mac": MAC, "bound": False,
                "config": {"user_info": {"height": -1}}}),
    json.dumps({"schema_version": 1, "mac": MAC, "bound": False,
                "config": {"sys_time": {"time_zone": True}}}),
])
def test_corrupt_state_is_rejected_without_overwrite(tmp_path, content):
    path = tmp_path / "state.json"
    path.write_text(content)
    with pytest.raises(ValueError):
        BindingState(path, MAC)
    assert path.read_text() == content


def test_mismatched_or_invalid_mac_is_rejected(tmp_path):
    path = tmp_path / "state.json"
    BindingState(path, MAC).reply(BIND)
    before = path.read_bytes()
    for mac in ("C1:23:45:67:89:AC", "not-a-mac"):
        with pytest.raises(ValueError):
            BindingState(path, mac)
    assert path.read_bytes() == before


@pytest.fixture
def initialization_messages():
    schema = text_format.Parse('''
        name: "initialization_fixture.proto" syntax: "proto3"
        message_type { name: "Mode"
          field { name: "begin" number: 1 label: LABEL_OPTIONAL type: TYPE_UINT32 }
          field { name: "end" number: 2 label: LABEL_OPTIONAL type: TYPE_UINT32 }
          field { name: "enabled" number: 3 label: LABEL_OPTIONAL type: TYPE_UINT32 }
          field { name: "kind" number: 4 label: LABEL_OPTIONAL type: TYPE_UINT32 }
        }
        message_type { name: "Modes"
          field { name: "entries" number: 1 label: LABEL_REPEATED type: TYPE_MESSAGE type_name: "Mode" }
        }
        message_type { name: "Battery"
          field { name: "millivolts" number: 1 label: LABEL_OPTIONAL type: TYPE_UINT32 }
          field { name: "percent" number: 2 label: LABEL_OPTIONAL type: TYPE_UINT32 }
          field { name: "celsius" number: 3 label: LABEL_OPTIONAL type: TYPE_INT32 }
        }
        message_type { name: "LatestHeartRate"
          field { name: "bpm" number: 1 label: LABEL_OPTIONAL type: TYPE_UINT32 }
        }
    ''', descriptor_pb2.FileDescriptorProto())
    pool = descriptor_pool.DescriptorPool()
    pool.Add(schema)
    return {name: message_factory.GetMessageClass(pool.FindMessageTypeByName(name))
            for name in ("Modes", "Battery", "LatestHeartRate")}


def test_mode_configuration_echo_is_typed_persistent_and_survives_unbind(tmp_path, initialization_messages):
    path = tmp_path / "state.json"
    modes = initialization_messages["Modes"]()
    modes.entries.add(begin=1700000000, end=1700003600, enabled=1, kind=4)
    modes.entries.add(enabled=0, kind=1)
    body = modes.SerializeToString()
    state = BindingState(path, MAC)
    state.reply(BIND)
    reply = state.reply(b"\x02\x02" + body)
    assert reply[:2] == b"\x02\x02"
    assert initialization_messages["Modes"].FromString(reply[2:]) == modes
    saved = json.loads(path.read_text())["config"]["mode_set"]
    assert initialization_messages["Modes"].FromString(bytes.fromhex(saved["protobuf_hex"])) == modes
    restarted = BindingState(path, MAC)
    assert restarted.bound
    restarted.reply(UNBIND)
    assert json.loads(path.read_text())["config"]["mode_set"] == saved
    assert restarted.reply(b"\x02\x02") == b"\x02\x02"
    assert json.loads(path.read_text())["config"]["mode_set"] == {"protobuf_hex": ""}


@pytest.mark.parametrize("body", [b"\x0a", b"\x08\x01", b"\x0a\x02\x08\x80",
                                  b"\x78\x01", b"\x0a\x02\x78\x01", b"\x0a\x03\x0a\x01\x01"])
def test_mode_configuration_rejects_bad_nested_fields_without_write(tmp_path, body):
    path = tmp_path / "state.json"
    state = BindingState(path, MAC)
    before = path.read_bytes()
    with pytest.raises(ValueError):
        state.reply(b"\x02\x02" + body)
    assert path.read_bytes() == before


@pytest.mark.parametrize("stored", [
    {"protobuf_hex": 1}, {"protobuf_hex": "xx"}, {"protobuf_hex": "0a"},
    {"protobuf_hex": "0a027801"}, {"protobuf_hex": "0801"},
    {"protobuf_hex": "", "unknown": 1}, {"mode_conf": []},
])
def test_invalid_saved_modes_are_rejected_without_overwrite(tmp_path, stored):
    path = tmp_path / "state.json"
    path.write_text(json.dumps({"schema_version": 1, "mac": MAC, "bound": True,
                                "config": {"mode_set": stored}}))
    before = path.read_bytes()
    with pytest.raises(ValueError):
        BindingState(path, MAC)
    assert path.read_bytes() == before


def test_battery_is_explicit_lab_model_and_latest_hr_has_no_sample(tmp_path, initialization_messages, monkeypatch):
    path = tmp_path / "state.json"
    state = BindingState(path, MAC)
    state.reply(BIND)
    before = path.read_bytes()
    monkeypatch.setattr(state, "_save", lambda _: pytest.fail("Queries must not write state"))
    battery = state.reply(b"\x01\x03")
    assert battery[:2] == b"\x01\x03"
    model = initialization_messages["Battery"].FromString(battery[2:])
    assert (model.millivolts, model.percent, model.celsius) == (4000, 80, 25)
    heart_rate = state.reply(b"\x03\x07")
    assert heart_rate == b"\x03\x07"
    assert initialization_messages["LatestHeartRate"].FromString(heart_rate[2:]).bpm == 0
    assert path.read_bytes() == before and state.bound


CONFIG_FIXTURES = (
    ("02 03", "remind_type", "0a040801100112040864100118012001", True),
    ("02 04", "exercise_goal", "0a0508ac02100112050801108827188403220608011002181e2801", True),
    ("02 0b", "auto_config", "08011005180a", False),
    ("02 11", "morning_notify", "080110980318d80422026869", False),
    ("02 13", "double_ring", "080110021803200428053006380740084809500a", False),
    ("02 15", "fatburning_notify", "0801", False),
    ("02 19", "spo2_enable", "", False),
    ("02 1b", "workout_ab", "08011001", False),
    ("02 21", "auto_pause", "0a08080110021803200412080805100618072008", True),
    ("02 23", "auto_start", "0a08080110021803200412080805100618072008", True),
    ("03 10", "monthly_mileage", "", False),
    ("03 11", "hr_levels", "080110021803200428053006", False),
    ("13 01", "ab_test", "080112020001", False),
)


@pytest.mark.parametrize("command,key,body,echo", CONFIG_FIXTURES)
def test_confirmed_initialization_config_is_parsed_persisted_and_replied(tmp_path, command, key, body, echo):
    path = tmp_path / "state.json"
    state = BindingState(path, MAC)
    state.reply(USER)
    state.reply(BIND)
    command, body = bytes.fromhex(command), bytes.fromhex(body)
    assert state.reply(command + body) == command + (body if echo else b"\x08\x02")
    assert json.loads(path.read_text())["config"][key] == {"protobuf_hex": body.hex()}
    restarted = BindingState(path, MAC)
    assert restarted.bound
    restarted.reply(UNBIND)
    saved = json.loads(path.read_text())["config"]
    assert saved[key] == {"protobuf_hex": body.hex()}
    assert saved["user_info"]["height"] == 175


@pytest.mark.parametrize("command,key,body,echo", CONFIG_FIXTURES)
def test_new_config_rejects_unknown_fields_and_does_not_acknowledge_failed_save(tmp_path, monkeypatch, command, key, body, echo):
    path = tmp_path / "state.json"
    state = BindingState(path, MAC)
    before = path.read_bytes()
    payload = bytes.fromhex(command + " " + body)
    for suffix in (b"\x78\x01", b"\x78"):
        with pytest.raises(ValueError):
            state.reply(payload + suffix)
        assert path.read_bytes() == before

    def fail_replace(*args):
        raise PermissionError("simulated configuration write failure")

    monkeypatch.setattr("experiments.keep_device.state.os.replace", fail_replace)
    with pytest.raises(PermissionError):
        state.reply(payload)
    assert path.read_bytes() == before
    assert not list(tmp_path.glob("*.tmp"))


@pytest.mark.parametrize("command", ["03 01", "03 02", "03 03", "03 04", "03 05", "03 06", "03 07",
                                     "03 08", "03 0a", "03 0b", "03 0c", "03 0d", "03 0e", "08 01"])
def test_confirmed_empty_queries_return_no_samples_without_state_write(tmp_path, monkeypatch, command):
    path = tmp_path / "state.json"
    state = BindingState(path, MAC)
    before = path.read_bytes()
    monkeypatch.setattr(state, "_save", lambda _: pytest.fail("Query must not write state"))
    command = bytes.fromhex(command)
    assert state.reply(command) == command
    with pytest.raises(UnsupportedRequest):
        state.reply(command + b"\x08\x01")
    assert path.read_bytes() == before


def test_morning_notify_rejects_text_above_recovered_45_byte_limit(tmp_path):
    path = tmp_path / "state.json"
    state = BindingState(path, MAC)
    before = path.read_bytes()
    with pytest.raises(ValueError, match="protocol limit"):
        state.reply(b"\x02\x11\x22\x2e" + b"x" * 46)
    assert path.read_bytes() == before


def test_explicit_reset_cli_preserves_configuration(tmp_path):
    path = tmp_path / "state.json"
    state = BindingState(path, MAC)
    state.reply(USER)
    state.reply(BIND)
    config = json.loads(path.read_text())["config"]
    result = subprocess.run(
        [sys.executable, "-X", "utf8", "-m", "experiments.keep_device.state",
         "--state", str(path), "--address", MAC, "--reset-binding"],
        capture_output=True, text=True, encoding="utf-8", check=False,
    )
    assert result.returncode == 0 and result.stderr == ""
    assert result.stdout.strip() == "本地设备绑定状态已重置；云端未修改。"
    assert not BindingState(path, MAC).bound
    assert json.loads(path.read_text())["config"] == config


@pytest.mark.parametrize("omitted", ["--reset-binding", "--state", "--address", "all"])
def test_reset_cli_requires_every_explicit_parameter(tmp_path, monkeypatch, omitted):
    from experiments.keep_device.state import main

    path = tmp_path / "state.json"
    BindingState(path, MAC).reply(BIND)
    before = path.read_bytes()
    args = {"--reset-binding": [], "--state": [str(path)], "--address": [MAC]}
    argv = ["state"]
    for option, values in args.items():
        if omitted not in (option, "all"):
            argv.extend([option, *values])
    monkeypatch.setattr(sys, "argv", argv)
    with pytest.raises(SystemExit) as raised:
        main()
    assert raised.value.code == 2
    assert path.read_bytes() == before
