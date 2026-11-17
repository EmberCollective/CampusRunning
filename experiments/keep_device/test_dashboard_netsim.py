"""Recover Netsim settings from a Windows panel without touching real Bluetooth."""

import json
import sys
from unittest.mock import Mock

import pytest

from experiments.keep_device import dashboard
from experiments.keep_device.dashboard import Watch, create_app
from experiments.keep_device.state import BindingState
from experiments.keep_device.test_files import source


@pytest.fixture
def panel(tmp_path, monkeypatch):
    monkeypatch.setattr(dashboard.sys, "platform", "win32")
    watch = Watch(tmp_path / "panel", tmp_path / "netsim-state.json", transport="windows",
                  windows_python=sys.executable, btvs=sys.executable, tshark=sys.executable)
    watch.configure({})
    return watch


def test_missing_netsim_can_be_checked_and_saved_from_panel(panel, tmp_path, monkeypatch):
    launch = Mock()
    monkeypatch.setattr(dashboard.subprocess, "Popen", launch)
    app = create_app(panel)
    client = app.test_client()
    headers = {"X-Watch-Token": app.config["WATCH_TOKEN"]}
    before = panel.config_path.read_bytes()
    assert client.get("/api/watch/config").json["netsim_configured"] is False
    assert client.post("/api/watch/config", json={"transport": "netsim"}, headers=headers).status_code == 400
    ini = tmp_path / "模拟器配置" / "netsim.ini"
    body = {"transport": "netsim", "netsim_ini": str(ini)}
    assert client.post("/api/watch/check", json=body).status_code == 403
    assert client.post("/api/watch/check", json=body, headers=headers).json == {
        "ready": False, "checks": {"netsim_ini": False}}
    ini.parent.mkdir()
    ini.write_text("grpc.port=12345\n", encoding="utf-8")
    assert client.post("/api/watch/check", json=body, headers=headers).json["ready"] is True
    assert panel.config_path.read_bytes() == before
    assert not panel.netsim_state.exists()
    saved = client.post("/api/watch/config", json=body, headers=headers)
    assert saved.status_code == 200 and saved.json["netsim_configured"] is True
    assert panel.netsim_ini == ini.resolve()
    assert panel.check()["ready"] is True
    restored = Watch(panel.lab, panel.netsim_state)
    assert restored.configuration() == panel.configuration()
    assert restored.mac == panel.mac
    launch.assert_not_called()


def test_switching_preserves_both_identities_binding_and_selection(panel, tmp_path, source):
    for state, mac in ((panel.netsim_state, "C2:00:00:00:00:01"),
                       (panel.windows_state, "50:00:00:00:00:01")):
        binding = BindingState(state, mac)
        binding.reply(b"\x01\x05")
        binding.reply(b"\x01\x04\x08\x01")
    original = {state: state.read_bytes() for state in (panel.netsim_state, panel.windows_state)}
    panel.directory = source.parent
    panel.queue = panel._queue()
    panel.queue.reply(bytes.fromhex("06 03 08 2c"))
    workouts = {p: p.read_bytes() for p in source.parent.iterdir() if p.suffix in (".sport44", ".json")}
    selection = {"directory": str(source.parent)}
    panel.selection.write_text(json.dumps(selection), encoding="utf-8")
    panel.configure({"transport": "netsim", "netsim_ini": str(tmp_path / "netsim.ini")})
    assert panel.mac == "C2:00:00:00:00:01" and panel.state == panel.netsim_state
    panel.configure({"transport": "windows"})
    assert panel.mac == "50:00:00:00:00:01" and panel.state == panel.windows_state
    assert all(state.read_bytes() == content for state, content in original.items())
    assert all(p.read_bytes() == content for p, content in workouts.items())
    assert json.loads(panel.selection.read_text(encoding="utf-8")) == selection
    restored = Watch(panel.lab, panel.netsim_state)
    assert restored.transport == "windows" and restored.netsim_ini == tmp_path / "netsim.ini"
    assert restored.snapshot()["received"] == 1


def test_legacy_windows_configuration_and_explicit_cli_override(panel, tmp_path):
    legacy = {key: value for key, value in panel.config.items() if key != "netsim_ini"}
    panel.config_path.write_text(json.dumps(legacy), encoding="utf-8")
    legacy_panel = Watch(panel.lab, panel.netsim_state)
    assert legacy_panel.transport == "windows" and legacy_panel.netsim_ini is None
    legacy_panel.configure({"netsim_ini": str(tmp_path / "saved.ini")})
    overridden = Watch(panel.lab, panel.netsim_state, tmp_path / "cli.ini")
    assert overridden.transport == "windows" and overridden.netsim_ini == tmp_path / "cli.ini"


@pytest.mark.parametrize("value", [None, [], 1, "", "x" * 4097])
def test_invalid_netsim_input_does_not_replace_configuration(panel, value):
    before = panel.config_path.read_bytes()
    with pytest.raises(ValueError):
        panel.configure({"transport": "netsim", "netsim_ini": value})
    assert panel.config_path.read_bytes() == before and panel.transport == "windows"


@pytest.mark.parametrize("active", ["running", "operation"])
def test_netsim_settings_remain_locked_during_broadcast_operations(panel, tmp_path, active):
    before = panel.config_path.read_bytes()
    if active == "running":
        panel.process = Mock()
        panel.process.poll.return_value = None
    else:
        panel.operation = "stop"
    with pytest.raises(ValueError, match="停止广播"):
        panel.configure({"transport": "netsim", "netsim_ini": str(tmp_path / "netsim.ini")})
    assert panel.config_path.read_bytes() == before


def test_netsim_start_reads_current_port_from_saved_path(panel, tmp_path, monkeypatch):
    ini = tmp_path / "netsim.ini"
    ini.write_text("grpc.port=12345\n", encoding="utf-8")
    panel.configure({"transport": "netsim", "netsim_ini": str(ini)})
    ini.write_text("grpc.port=23456\n", encoding="utf-8")
    process = Mock()
    process.poll.return_value = None
    launch = Mock(return_value=process)
    monkeypatch.setattr(dashboard.subprocess, "Popen", launch)
    monkeypatch.setattr(dashboard.threading, "Thread", Mock())
    monkeypatch.setattr(dashboard.threading, "Timer", Mock())
    panel.start()
    argv = launch.call_args.args[0]
    assert "android-netsim:127.0.0.1:23456" in argv
    assert argv[argv.index("--state") + 1] == str(panel.netsim_state)
    assert argv[argv.index("--address") + 1] == panel.mac
    assert "experiments.keep_device.emulator" in argv
