"""Native generation and panel state without opening BLE or uploading activities."""

from pathlib import Path
from unittest.mock import Mock

import pytest

from web import routes
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
