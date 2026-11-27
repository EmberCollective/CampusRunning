"""Editable paths, bounded private diagnostics and shared-device ownership."""

import os
import subprocess
import sys

import pytest

from experiments.keep_device.dashboard import ROOT, Watch, create_app
from experiments.keep_device.state import BindingState, device_state_lock


@pytest.fixture
def watch(tmp_path):
    return Watch(tmp_path / "panel", tmp_path / "old.json", tmp_path / "netsim.ini")


def test_state_paths_are_editable_persistent_and_preserve_existing_files(watch, tmp_path):
    before = watch.state.read_bytes()
    replacement = tmp_path / "existing.json"
    BindingState(replacement, "C2:00:00:00:00:02").reply(b"\x01\x05")
    replacement_before = replacement.read_bytes()
    windows = tmp_path / "existing-windows.json"
    watch.configure({"netsim_state": str(replacement), "windows_state": str(windows)})
    assert watch.mac == "C2:00:00:00:00:02"
    assert replacement.read_bytes() == replacement_before
    assert (tmp_path / "old.json").read_bytes() == before
    restored = Watch(watch.lab, tmp_path / "old.json", windows_state=tmp_path / "old-windows.json")
    assert restored.netsim_state == replacement and restored.windows_state == windows
    assert restored.configuration()["config_file"] == str(watch.config_path)
    assert restored.configuration()["data_dir"] == str(watch.lab)


@pytest.mark.parametrize("target", ["same", "config", "temporary", "selection", "directory", "invalid"])
def test_state_path_validation_preserves_configuration(watch, tmp_path, target):
    watch.configure({})
    before = watch.config_path.read_bytes()
    value = {"same": str(watch.windows_state),
             "config": str(watch.config_path), "temporary": str(watch.config_path.with_suffix(".tmp")), "selection": str(watch.selection),
             "directory": str(tmp_path), "invalid": ""}[target]
    with pytest.raises(ValueError):
        watch.configure({"netsim_state": value})
    assert watch.config_path.read_bytes() == before


def test_log_endpoint_requires_token_and_filters_raw_traffic(watch):
    app = create_app(watch)
    client = app.test_client()
    assert client.get("/api/watch/logs").status_code == 403
    (watch.lab / "run.log").write_text(
        "DEBUG raw_payload=private-raw-value\n"
        "{\"user_info\":\"private-user-value\"}\n"
        "CONNECTED; persistent_binding=True\n"
        "2026-11-17T12:00:00+08:00 DISCONNECTED reason=19\n"
        "DEVICE_REPLY_SENT sid=01 cid=05 token=secret-value\n", encoding="utf-8")
    response = client.get("/api/watch/logs", headers={"X-Watch-Token": app.config["WATCH_TOKEN"]})
    assert response.status_code == 200 and response.headers["Cache-Control"] == "no-store"
    text = response.json["text"]
    assert "CONNECTED;" in text and "DISCONNECTED reason=19" in text and "cid=05" in text
    assert all(secret not in text for secret in ("private-raw-value", "private-user-value", "secret-value"))
    assert response.json["files"] == 1


def test_log_history_is_bounded_and_survives_panel_restart(watch):
    for index in range(4):
        path = watch.lab / f"{index}.log"
        path.write_text(f"CONNECTED; session={index}\n" * 1000, encoding="utf-8")
        os.utime(path, (100 + index, 100 + index))
    for index in range(110):
        watch._note(f"panel-event-{index}")
    log = watch.logs()
    assert log["files"] == 3 and "session=0" not in log["text"]
    assert log["text"].count("session=") <= 900
    assert "panel-event-0\n" not in log["text"] and "panel-event-109" in log["text"]
    restored = Watch(watch.lab, watch.state, watch.netsim_ini)
    assert "session=3" in restored.logs()["text"]


def test_device_lock_blocks_another_process_and_is_released(watch):
    command = [sys.executable, "-c",
               "import sys; from experiments.keep_device.state import device_state_lock; "
               "lock=device_state_lock(sys.argv[1]); lock.__enter__(); print('acquired'); lock.__exit__(None,None,None)",
               str(watch.state)]
    before = watch.state.read_bytes()
    with device_state_lock(watch.state):
        blocked = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, encoding="utf-8")
        assert blocked.returncode and "ValueError" in blocked.stderr
        with pytest.raises(ValueError, match="另一个广播"):
            watch.reset_binding({"keep_unbound": True, "transport": "netsim"})
    released = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, encoding="utf-8")
    assert released.returncode == 0 and released.stdout.strip() == "acquired"
    assert watch.state.read_bytes() == before
