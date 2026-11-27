"""Native B5 generation and atomic publication; no radio or cloud access."""

import datetime
import random
import struct
from dataclasses import replace
from pathlib import Path

import pytest

from src.config_manager import ConfigManager
from src.core.models import GenerationConfig
from src.generation_engine import GenerationEngine
from src.core.cadence_generator import compute_lap_cadence_metrics

from experiments.keep_device.exporter import B5Exporter
from experiments.keep_device.files import WorkoutFiles
from experiments.keep_device.test_history import _segments


class CaptureExporter(B5Exporter):
    def export(self, data, output_path):
        self.data = data
        return super().export(data, output_path)


@pytest.fixture
def native(tmp_path):
    exporter = CaptureExporter()
    engine = GenerationEngine(ConfigManager("config"), {"b5": exporter}, strict=True)
    config = GenerationConfig(output_format="b5", output_dir=str(tmp_path),
                              min_pace=7.5, max_pace=7.5,
                              start_time_min="07:00", start_time_max="07:00")
    return exporter, engine, config


@pytest.mark.parametrize("distance", [1.0, 3.01, 3.24, 4.05, 4.12])
@pytest.mark.parametrize("seed", [1, 42, 20261116])
def test_native_generation_has_consistent_summary(native, distance, seed):
    exporter, engine, config = native
    random.seed(seed)
    result = engine.generate_single(datetime.date(2026, 11, 16), distance, config)
    data = exporter.data
    elapsed = (datetime.datetime.fromisoformat(data.trackpoints[-1].time)
               - datetime.datetime.fromisoformat(data.trackpoints[0].time)).total_seconds()
    assert result.duration_seconds == data.duration_seconds == elapsed
    assert result.pace_min_per_km == elapsed / (60 * distance)
    assert data.trackpoints[-1].distance_meters == pytest.approx(distance * 1000, abs=.001)
    assert config.min_pace == config.max_pace == 7.5
    assert Path(result.filepath).suffix == ".sport44"
    WorkoutFiles(Path(result.filepath))


@pytest.mark.parametrize("local_time, expected_utc", [
    ("20:00", "2026-11-16T12:00:00+00:00"),
    ("21:00", "2026-11-16T13:00:00+00:00"),
    ("00:05", "2026-11-15T16:05:00+00:00"),
])
def test_native_local_time_is_utc_on_wire_and_local_in_inventory(native, local_time, expected_utc):
    exporter, engine, config = native
    config.start_time_min = config.start_time_max = local_time
    result = engine.generate_single(datetime.date(2026, 11, 16), 1.0, config)
    path = Path(result.filepath)
    encoded = path.read_bytes()
    description_length = struct.unpack_from("<h", encoded, len(encoded) - 14)[0]
    _, duration, start, end = struct.unpack_from("<4i", encoded, len(encoded) - 14 - description_length)
    # The shared generator randomizes seconds even for a single selected minute.
    seconds = exporter.data.start_time.second
    expected = datetime.datetime.fromisoformat(expected_utc).replace(second=seconds)
    assert start == int(expected.timestamp())
    assert end - start == duration == result.duration_seconds
    # Check point timestamps as well as the summary; shifting only one corrupts the activity.
    for index, point in enumerate(exporter.data.trackpoints):
        elapsed = (datetime.datetime.fromisoformat(point.time) - exporter.data.start_time).total_seconds()
        assert struct.unpack_from("<i", encoded, 3 + index * 65 + 40)[0] == start + elapsed
    record, = WorkoutFiles(path).inventory()
    assert record["date"] == f"2026-11-16T{local_time}:{seconds:02d}+08:00"
    assert datetime.datetime.fromisoformat(record["date"]).astimezone(datetime.timezone.utc) == expected


def test_invalid_data_and_existing_output_are_preserved(native, tmp_path, monkeypatch):
    exporter, engine, config = native
    random.seed(42)
    result = engine.generate_single(datetime.date(2026, 11, 16), 3.01, config)
    data = exporter.data
    existing = Path(result.filepath)
    before = existing.read_bytes()
    with pytest.raises(FileExistsError):
        exporter.export(data, str(existing))
    assert existing.read_bytes() == before
    bad = tmp_path / "invalid.sport44"
    with pytest.raises(ValueError, match="endpoint"):
        exporter.export(replace(data, distance_km=4), str(bad))
    assert not bad.exists()
    with pytest.raises(ValueError, match="duration"):
        exporter.export(replace(data, duration_seconds=1), str(bad))
    def fail_publish(*args):
        raise OSError("publish failed")
    monkeypatch.setattr("experiments.keep_device.exporter.os.link", fail_publish)
    with pytest.raises(OSError, match="publish failed"):
        exporter.export(data, str(bad))
    assert not bad.exists()
    assert not list(tmp_path.glob(".b5-*"))


def test_strict_batch_propagates_export_failure(native, monkeypatch):
    exporter, engine, config = native
    def fail(*args):
        raise ValueError("invalid workout")
    monkeypatch.setattr(exporter, "export", fail)
    with pytest.raises(ValueError, match="invalid workout"):
        engine.generate_dates([datetime.date(2026, 11, 16)], 3.01, 3.01, config)


@pytest.mark.parametrize("algorithm", ["natural", "steady", "progressive", "uniform"])
@pytest.mark.parametrize("intensity", [0, .15, 1])
@pytest.mark.parametrize("distance", [1.0, 3.01, 4.12])
def test_pace_models_preserve_b5_contract(native, algorithm, intensity, distance):
    exporter, engine, config = native
    config.pace_algorithm, config.pace_intensity = ("natural" if algorithm == "uniform" else algorithm), intensity
    config.enable_pace_fluctuation = algorithm != "uniform"
    result = engine.generate_single(datetime.date(2026, 11, 17), distance, config)
    data = exporter.data
    assert round(abs(result.duration_seconds - distance*7.5*60), 6) <= 1
    points = data.trackpoints
    for km in range(1, int(distance)+1):
        crossing = next(p for p in points if round(p.distance_meters) >= km*1000)
        assert round(crossing.distance_meters) == km*1000
    encoded = Path(result.filepath).read_bytes()
    description = encoded[-92:-14]
    kind, duration, start, end, meters, steps, calories = struct.unpack_from('<7i', description)
    assert kind == 2 and duration == end-start == result.duration_seconds
    assert meters == round(distance*1000)
    assert steps == compute_lap_cadence_metrics(points)[2]
    segments = _segments(encoded, len(points))
    assert sum(segments[40]) == duration and segments[40] == segments[43]
    assert sum(segments[20]) == meters
    assert segments[44] == tuple(round(s*1000/m) for s,m in zip(segments[40], segments[20]))
    previous = points[0]
    for index, point in enumerate(points):
        offset = 3 + index*65
        assert struct.unpack_from('<f', encoded, offset)[0] == pytest.approx(point.speed*3.6)
        assert struct.unpack_from('<f', encoded, offset+44)[0] == pytest.approx(1000/point.speed)
        if index:
            seconds = (datetime.datetime.fromisoformat(point.time)-datetime.datetime.fromisoformat(previous.time)).total_seconds()
            predicted = (point.distance_meters-previous.distance_meters)/previous.speed
            assert seconds == pytest.approx(predicted, abs=1.1)
        previous = point
    assert WorkoutFiles(Path(result.filepath)).inventory()[0]['received'] is False
