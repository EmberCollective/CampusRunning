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

from experiments.keep_device.exporter import B5Exporter
from experiments.keep_device.files import WorkoutFiles


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
