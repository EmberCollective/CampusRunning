import math
import datetime
import json
import xml.etree.ElementTree as ET

import pytest

from src.core.coordinate_corrector import CoordinateCorrector
from src.core.models import GeoPoint, GenerationConfig
from src.config_manager import ConfigManager
from src.generation_engine import GenerationEngine


def distance_meters(first: GeoPoint, second: GeoPoint) -> float:
    latitude = (first.latitude + second.latitude) / 2
    return math.hypot(
        (first.longitude - second.longitude)
        * 111320
        * math.cos(math.radians(latitude)),
        (first.latitude - second.latitude) * 110540,
    )


def test_converts_guizhou_university_coordinates_to_wgs84():
    point = GeoPoint(longitude=106.65941053, latitude=26.45182472)

    corrected = CoordinateCorrector().correct_coordinate(point)

    assert corrected.longitude == pytest.approx(106.65578316, abs=1e-8)
    assert corrected.latitude == pytest.approx(26.45541253, abs=1e-8)
    assert distance_meters(point, corrected) == pytest.approx(536.6, abs=0.2)


def test_converts_beijing_normal_university_coordinates_to_wgs84():
    point = GeoPoint(longitude=116.38391733, latitude=39.93620032)

    corrected = CoordinateCorrector().correct_coordinate(point)

    assert corrected.longitude == pytest.approx(116.37767772, abs=1e-8)
    assert corrected.latitude == pytest.approx(39.93480247, abs=1e-8)
    assert distance_meters(point, corrected) == pytest.approx(554.5, abs=0.2)


def test_keeps_coordinates_outside_china_unchanged():
    point = GeoPoint(longitude=2.2945, latitude=48.8584)

    assert CoordinateCorrector().correct_coordinate(point) is point


def test_generation_ignores_legacy_correction_and_converts_by_coordinate(tmp_path):
    config_dir = tmp_path / "config"
    tracks_dir = config_dir / "tracks"
    tracks_dir.mkdir(parents=True)
    track = {
        "id": "bnu",
        "name": "北师大测试轨迹",
        "description": "test",
        "base_coordinates": [
            {"longitude": 116.3835, "latitude": 39.9360},
            {"longitude": 116.3845, "latitude": 39.9360},
            {"longitude": 116.3845, "latitude": 39.9365},
            {"longitude": 116.3835, "latitude": 39.9365},
        ],
        "coordinate_correction": {
            "current_center": {"longitude": 106.671, "latitude": 26.444},
            "target_center": {"longitude": 106.674613, "latitude": 26.440410},
        },
    }
    (tracks_dir / "bnu.json").write_text(
        json.dumps(track, ensure_ascii=False), encoding="utf-8"
    )
    output_dir = tmp_path / "output"
    config = GenerationConfig(
        track_id="bnu",
        min_pace=7.0,
        max_pace=7.0,
        start_time_min="07:00",
        start_time_max="07:00",
        output_dir=str(output_dir),
        include_track=True,
        apply_correction=True,
        enable_pace_fluctuation=False,
        enable_cadence=False,
        output_format="tcx",
        points_per_km=10,
        max_deviation_meters=0.0,
        smooth_factor=0.0,
        calories_per_km=35.0,
    )
    result = GenerationEngine(ConfigManager(str(config_dir))).generate_single(
        datetime.date(2026, 11, 3), 0.4, config
    )

    tree = ET.parse(result.filepath)
    namespace = {"tcx": "http://www.garmin.com/xmlschemas/TrainingCenterDatabase/v2"}
    first = tree.find(".//tcx:Trackpoint/tcx:Position", namespace)
    latitude = float(first.find("tcx:LatitudeDegrees", namespace).text)
    longitude = float(first.find("tcx:LongitudeDegrees", namespace).text)
    source_center = GeoPoint(
        longitude=sum(point['longitude'] for point in track['base_coordinates']) / 4,
        latitude=sum(point['latitude'] for point in track['base_coordinates']) / 4,
    )
    expected_center = CoordinateCorrector().correct_coordinate(source_center)
    assert abs(longitude - expected_center.longitude) < 0.001
    assert abs(latitude - expected_center.latitude) < 0.001
