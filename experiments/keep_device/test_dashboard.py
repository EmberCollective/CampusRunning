"""Native generation and panel state without opening BLE or uploading activities."""

from pathlib import Path
import io
import json
import subprocess
import sys
import threading
import time
from unittest.mock import Mock

import pytest

from web import routes
from experiments.keep_device import dashboard
from experiments.keep_device.dashboard import Watch, create_app
from experiments.keep_device.files import WorkoutFiles
from experiments.keep_device.test_files import source, wire


@pytest.fixture
def watch(tmp_path):
    return Watch(tmp_path / "panel", tmp_path / "state.json", tmp_path / "netsim.ini")


@pytest.fixture
def app(watch):
    routes._generation_jobs.clear()
    app = create_app(watch)
    app.config["TESTING"] = True
    return app


@pytest.mark.parametrize("mode,details,count", [
    ("single", {"date": "2026-11-10", "distance": 3.01, "pace": 7.5}, 1),
    ("daily", {"start_date": "2026-11-10", "end_date": "2026-11-11", "min_km": 3.24, "max_km": 3.24}, 2),
    ("total", {"start_date": "2026-11-10", "end_date": "2026-11-11", "total_km": 8.1,
               "min_daily_km": 4.05, "max_daily_km": 4.05, "rest_days_per_week": 0, "weekend_factor": 1}, 2),
    ("dates", {"dates": ["2026-11-10", "2026-11-11"], "min_km": 4.12, "max_km": 4.12}, 2),
])
def test_old_four_modes_generate_native_b5(app, watch, mode, details, count):
    request = dict(track_id="campus_default", output_format="b5", min_pace=7.5, max_pace=7.5,
                   start_time_min="07:00", start_time_max="07:00", **details)
    client = app.test_client()
    response = client.post("/api/generate/" + mode, json=request,
                           headers={"X-Watch-Token": app.config["WATCH_TOKEN"]})
    assert response.status_code == 200, response.json
    assert response.json["total_files"] == count
    results = routes._generation_jobs[response.json["job_id"]]
    for result in results:
        path = Path(result.filepath)
        assert path.is_relative_to(watch.lab) and path.suffix == ".sport44"
        record, = WorkoutFiles(path).inventory()
        assert record["distance_km"] == pytest.approx(result.distance_km, abs=.001)
        assert record["duration_seconds"] == result.duration_seconds
    page = client.get("/watch?job=" + response.json["job_id"])
    assert page.status_code == 200 and b"candidate" in page.data
    assert watch.process is None  # Generating or viewing never uploads.


def test_watch_actions_require_token_and_validate_input(app):
    client = app.test_client()
    assert client.post("/api/watch/start").status_code == 403
    assert client.post("/api/generate/single", json={"output_format": "b5"}).status_code == 403
    headers = {"X-Watch-Token": app.config["WATCH_TOKEN"]}
    for data in ([1], {"job_id": []}, {"job_id": "missing"}):
        assert client.post("/api/watch/load", json=data, headers=headers).status_code == 400
    assert client.post("/api/generate/single", json={"output_format": "b5", "enable_cadence": False}, headers=headers).status_code == 400
    assert client.get("/watch", headers={"Host": "untrusted.example"}).status_code == 400


def test_panel_uses_loaded_snapshot_receipts_and_live_process(tmp_path, source, wire):
    watch = Watch(tmp_path / "panel", tmp_path / "state.json", tmp_path / "netsim.ini", source.parent)
    watch.process = Mock()
    watch.process.poll.return_value = None
    watch.ready = watch.connected = True
    before = watch.snapshot()
    assert before["connected"] and before["pending"] == 1
    assert before["binding_address"] == {"value": watch.mac, "medium": "virtual"}
    assert before["total_km"] == .238  # Wire distance is rounded to whole meters.
    source.with_name("unloaded.sport44").write_bytes(b"not a workout")
    assert len(watch.snapshot()["records"]) == 1
    WorkoutFiles(source).reply(bytes.fromhex("06 03 08 2c"))
    after = watch.snapshot()
    assert after["received"] == 1 and after["pending"] == 0
    watch.process.poll.return_value = 1
    assert not watch.snapshot()["connected"] and not watch.snapshot()["running"]
    assert watch.snapshot()["binding_address"]["value"] is None


def test_binding_address_requires_confirmed_advertisement(watch):
    watch.process = Mock()
    watch.process.poll.return_value = None
    assert watch.snapshot()["binding_address"]["value"] is None
    watch.ready = True
    assert watch.snapshot()["binding_address"]["value"] == watch.mac
    watch.ready = False
    assert watch.snapshot()["binding_address"]["value"] is None


def test_start_rejects_corrupt_files_before_launch(tmp_path, source, monkeypatch):
    watch = Watch(tmp_path / "panel", tmp_path / "state.json", tmp_path / "netsim.ini", source.parent)
    source.write_bytes(b"broken")
    launch = Mock()
    monkeypatch.setattr("experiments.keep_device.dashboard.subprocess.Popen", launch)
    with pytest.raises(ValueError):
        watch.start()
    launch.assert_not_called()


def test_single_form_pace_is_used(app):
    with app.test_request_context():
        config = routes._parse_generate_request({"pace": 6.25})
        assert config.min_pace == config.max_pace == 6.25


def test_reset_binding_requires_token_confirmation_and_matching_transport(app, watch):
    client = app.test_client()
    before = watch.state.read_bytes()
    body = {"keep_unbound": True, "transport": "netsim"}
    assert client.post("/api/watch/reset-binding", json=body).status_code == 403
    for invalid in ({}, [], {**body, "keep_unbound": 1}, {**body, "keep_unbound": "true"},
                    {**body, "transport": "windows"}):
        response = client.post("/api/watch/reset-binding", json=invalid,
                               headers={"X-Watch-Token": app.config["WATCH_TOKEN"]})
        assert response.status_code == 400
        assert watch.state.read_bytes() == before


@pytest.mark.parametrize("guard", ["running", "operation", "stopping"])
def test_reset_binding_rejects_active_work(watch, guard):
    before = watch.state.read_bytes()
    if guard == "running":
        watch.process = Mock()
        watch.process.poll.return_value = None
    else:
        setattr(watch, guard, "start" if guard == "operation" else True)
    with pytest.raises(ValueError, match="停止广播"):
        watch.reset_binding({"keep_unbound": True, "transport": "netsim"})
    assert watch.state.read_bytes() == before


@pytest.mark.parametrize("transport", ["netsim", "windows"])
def test_reset_binding_preserves_identity_configuration_and_workouts(watch, source, transport):
    for state in (watch.netsim_state, watch.windows_state):
        binding = dashboard.BindingState(state, watch.mac)
        binding.reply(b"\x01\x05")
        binding.reply(b"\x01\x04\x08\x01")
    watch.config["transport"] = transport
    watch.directory = source.parent
    watch.queue = watch._queue()
    watch.queue.reply(bytes.fromhex("06 03 08 2c"))
    watch.selection.write_text(json.dumps({"directory": str(source.parent)}), encoding="utf-8")
    untouched = {p: p.read_bytes() for p in source.parent.iterdir() if p.is_file() and p != watch.state}
    untouched[watch.selection] = watch.selection.read_bytes()
    before = json.loads(watch.state.read_text(encoding="utf-8"))
    app = create_app(watch)
    response = app.test_client().post("/api/watch/reset-binding",
        json={"keep_unbound": True, "transport": transport},
        headers={"X-Watch-Token": app.config["WATCH_TOKEN"]})
    assert response.status_code == 200
    assert json.loads(watch.state.read_text(encoding="utf-8")) == {**before, "bound": False}
    assert all(p.read_bytes() == content for p, content in untouched.items())
    assert response.json["received"] == 1 and response.json["pending"] == 0
    assert watch.process is None


@pytest.mark.parametrize("content", [None, "[]", "broken", '{"mac":"invalid"}',
                                      '{"mac":"C2:00:00:00:00:01","bound":true}'])
def test_reset_binding_does_not_create_or_replace_invalid_state(watch, content):
    if content is None:
        watch.state.unlink()
    else:
        watch.state.write_text(content, encoding="utf-8")
    with pytest.raises(ValueError):
        watch.reset_binding({"keep_unbound": True, "transport": "netsim"})
    if content is None:
        assert not watch.state.exists()
    else:
        assert watch.state.read_text(encoding="utf-8") == content


@pytest.fixture
def physical(tmp_path, monkeypatch):
    monkeypatch.setattr(dashboard.sys, "platform", "win32")
    return Watch(tmp_path / "physical", tmp_path / "netsim-state.json", transport="windows",
                 windows_python=sys.executable, btvs=sys.executable, tshark=sys.executable)


def test_connection_configuration_persists_separately_without_starting(physical, monkeypatch):
    launch = Mock()
    monkeypatch.setattr(dashboard.subprocess, "Popen", launch)
    physical.configure({"transport": "windows"})
    assert physical.state != physical.netsim_state
    assert not physical.state.exists() and not physical.netsim_state.exists()
    restored = Watch(physical.lab, physical.netsim_state)
    assert restored.configuration() == physical.configuration()
    launch.assert_not_called()
    assert physical.snapshot()["binding_address"] == dict(value=None, medium="physical")
    for invalid in ({"transport": []}, {"python": None}, {"args": "--reset-binding"}, {"btvs": "missing-tool-876.exe"}):
        before = physical.config_path.read_bytes()
        with pytest.raises(ValueError):
            physical.configure(invalid)
        assert physical.config_path.read_bytes() == before


def test_probe_is_token_protected_and_only_invokes_read_only_check(physical, monkeypatch):
    app = create_app(physical)
    client = app.test_client()
    headers = {"X-Watch-Token": app.config["WATCH_TOKEN"]}
    run = Mock(return_value=subprocess.CompletedProcess([], 0, '{"ready":true,"checks":{"python":true}}', ""))
    monkeypatch.setattr(dashboard.subprocess, "run", run)
    assert client.post("/api/watch/check", json={}).status_code == 403
    result = client.post("/api/watch/check", json={}, headers=headers)
    assert result.json["ready"] and result.headers["Cache-Control"] == "no-store"
    assert "--check" in run.call_args.args[0] and "--reset-binding" not in run.call_args.args[0]
    assert "shell" not in run.call_args.kwargs
    assert client.post("/api/watch/check", json=[], headers=headers).status_code == 400
    assert client.get("/api/watch/config").headers["Cache-Control"] == "no-store"


def test_windows_start_uses_existing_launcher_and_fixed_batch(physical, source, monkeypatch):
    physical.directory = source.parent
    process = Mock()
    process.poll.return_value = None
    launch = Mock(return_value=process)
    monkeypatch.setattr(dashboard.subprocess, "Popen", launch)
    monkeypatch.setattr(dashboard.threading, "Thread", Mock())
    monkeypatch.setattr(dashboard.threading, "Timer", Mock())
    monkeypatch.setattr(physical, "check", lambda: dict(ready=True))
    physical.start()
    argv = launch.call_args.args[0]
    assert "experiments.keep_device.launcher" in argv and "--events-json" in argv
    assert argv[argv.index("--workout-dir") + 1] == str(source.parent)
    assert argv[argv.index("--state") + 1] == str(physical.windows_state)
    assert not physical.snapshot()["ready"] and physical.snapshot()["pending"] == 1
    with pytest.raises(ValueError, match="停止广播"):
        physical.configure({"transport": "windows"})


def test_background_start_remains_pollable_and_rejects_duplicate_actions(physical, monkeypatch):
    entered, release = threading.Event(), threading.Event()
    def check():
        entered.set()
        release.wait(3)
        raise ValueError("probe failed")
    monkeypatch.setattr(physical, "check", check)
    physical.control("start")
    assert entered.wait(1)
    started = time.monotonic()
    assert physical.snapshot()["operation"] == "start"
    assert time.monotonic() - started < .5
    with pytest.raises(ValueError, match="上一项"):
        physical.control("start")
    with pytest.raises(ValueError, match="停止广播"):
        physical.configure({})
    release.set()
    deadline = time.monotonic() + 2
    while physical.operation and time.monotonic() < deadline:
        time.sleep(.01)
    assert physical.operation is None and physical.error == "probe failed"


def test_physical_address_requires_live_evidence_and_ignores_previous_process(physical):
    current, previous = Mock(), Mock()
    current.poll.return_value = None
    physical.process = current
    physical._event(previous, dict(type="advertising", identity="11:22:33:44:55:66"))
    assert not physical.ready
    physical._event(current, dict(type="advertising", identity="11:22:33:44:55:66"))
    assert physical.snapshot()["binding_address"]["value"] is None
    physical._event(current, dict(type="address", value="42:23:45:67:89:AB"))
    assert physical.snapshot()["binding_address"]["value"] == "42:23:45:67:89:AB"
    physical._event(current, dict(type="link", connected=False, ambiguous=True))
    assert not physical.connected and physical.error
    physical._event(current, dict(type="stopped"))
    assert physical.snapshot()["stopping"] and physical.snapshot()["binding_address"]["value"] is None
    physical._event(current, dict(type="address", value="42:23:45:67:89:AB"))
    assert physical.air_mac is None


def test_malformed_windows_event_requests_shutdown_and_clears_address(physical):
    process = Mock(stdout=io.StringIO('WATCH_EVENT broken-json\n'))
    process.poll.return_value = None
    process.wait.return_value = 1
    physical.process, physical.stop_path = process, physical.lab / "stop"
    physical.ready, physical.air_mac = True, "42:23:45:67:89:AB"
    physical._read(process, physical.lab / "test.log")
    assert physical.stop_path.exists() and "状态无效" in physical.error
    assert not physical.ready and physical.air_mac is None


def test_windows_stop_timeout_does_not_kill_name_restoration(physical):
    physical.process = Mock()
    physical.process.poll.return_value = None
    physical.process.wait.side_effect = subprocess.TimeoutExpired("launcher", 100)
    physical.stop_path = physical.lab / "stop"
    physical.ready, physical.air_mac = True, "42:23:45:67:89:AB"
    with pytest.raises(RuntimeError, match="清理超时"):
        physical.stop()
    assert physical.stop_path.exists() and physical.stopping and physical.running()
    assert physical.snapshot()["binding_address"]["value"] is None
    physical.process.kill.assert_not_called()
    physical.process.terminate.assert_not_called()
    with pytest.raises(ValueError, match="退出清理"):
        physical.control("start")


def test_previous_startup_timeout_cannot_stop_new_process(physical):
    old, current = Mock(), Mock()
    old.poll.return_value = current.poll.return_value = None
    physical.process, physical.stop_path = current, physical.lab / "new.stop"
    physical._startup_timeout(old, physical.lab / "old.stop")
    physical.stop(expected_process=old)
    assert not physical.stop_path.exists()
    current.wait.assert_not_called()


def test_invalid_binding_state_does_not_commit_configuration(physical):
    physical.configure({})
    before = physical.config_path.read_bytes()
    physical.windows_state.write_text('[]', encoding="utf-8")
    with pytest.raises(ValueError, match="状态文件无效"):
        physical.configure({"transport": "windows"})
    assert physical.config_path.read_bytes() == before
    assert physical.windows_state.read_text(encoding="utf-8") == '[]'


def test_fast_launcher_exit_keeps_specific_error_message(physical):
    process = Mock()
    process.poll.return_value = 1
    physical.process = process
    physical._event(process, dict(type="error", message="capture unavailable"))
    assert physical.snapshot()["error"] == "capture unavailable"


def test_loaded_batch_is_retained_when_windows_preflight_fails(physical, source, monkeypatch):
    monkeypatch.setattr(physical, "check", lambda: dict(ready=False))
    physical.control("load", source.parent, "selected-job")
    deadline = time.monotonic() + 2
    while physical.operation and time.monotonic() < deadline:
        time.sleep(.01)
    state = physical.snapshot()
    assert state["loaded_job"] == "selected-job" and state["pending"] == 1
    assert not state["running"] and "本机检查" in state["error"]
    assert physical.selection.exists() and source.exists()
