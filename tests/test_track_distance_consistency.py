"""Regression checks for geometric endpoints and the last interpolation segment."""

import datetime
import random

import pytest

from src.config_manager import ConfigManager
from src.core.models import GeoPoint
from src.core.track_analyzer import TrackAnalyzer
from src.core.track_generator import TrackGenerator


def generator():
    track = ConfigManager("config").load_track("campus_default")
    analyzer = TrackAnalyzer(track.base_coordinates)
    return TrackGenerator(analyzer.analyze_track(), analyzer)


@pytest.mark.parametrize("distance", [0.01, 1.0, 3.01, 3.24, 4.05, 4.12])
@pytest.mark.parametrize("seed", [1, 42, 20261116])
def test_smoothed_geometry_reaches_requested_distance(distance, seed):
    random.seed(seed)
    gen = generator()
    points = gen.generate_smooth_track(distance)
    measured = sum(gen.analyzer.calculate_distance(a, b) for a, b in zip(points, points[1:]))
    assert measured == pytest.approx(distance * 1000, abs=0.001)
    assert len(points) >= 2
    start = datetime.datetime(2026, 11, 16, 7)
    timed = gen.generate_tcx_trackpoints(points, start, 600, enable_pace_fluctuation=False)
    assert timed[-1].distance_meters == pytest.approx(measured)
    assert datetime.datetime.fromisoformat(timed[-1].time) - start == datetime.timedelta(seconds=600)


def test_interpolation_includes_final_closing_segment():
    points = [GeoPoint(0, 0), GeoPoint(0, .01), GeoPoint(.01, .01), GeoPoint(.01, 0)]
    analyzer = TrackAnalyzer(points)
    gen = TrackGenerator(analyzer.analyze_track(), analyzer)
    gen.is_clockwise = True
    interpolated = gen._generate_interpolated_track(40)
    assert interpolated[-1].latitude == pytest.approx(0)
    assert 0 < interpolated[-1].longitude < .002
