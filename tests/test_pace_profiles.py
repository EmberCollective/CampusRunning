"""Pace continuity, physical weighting, local extensions and the read-only preview API."""

import datetime
import math
import random

import pytest

from src.config_manager import ConfigManager
from src.core import pace_fluctuator as pace
from src.core.models import GenerationConfig, GeoPoint
from src.core.track_analyzer import TrackAnalyzer
from src.core.track_generator import TrackGenerator
from src.template_manager import TemplateManager
from web import routes


@pytest.mark.parametrize("algorithm", ["natural", "steady", "progressive"])
@pytest.mark.parametrize("intensity", [0, .15, 1])
def test_actual_distances_control_total_time(algorithm, intensity):
    distances = [0, .001, .02, 1, .0005, .4]
    model = pace.PaceFluctuator(7.5, intensity, 42, algorithm=algorithm)
    profile = model.generate_pace_profile(len(distances)+1, distances)
    assert len(profile) == len(distances)+1
    assert all(math.isfinite(p) and p > 0 for p in profile)
    assert profile[-1] == profile[-2]
    assert sum(model.generate_segment_times(profile[:-1], distances)) == pytest.approx(sum(distances)*7.5*60)
    if intensity == 0:
        assert profile == pytest.approx([7.5]*len(profile))


def test_seed_is_local_and_repeatable():
    before = random.getstate()
    a = pace.PaceFluctuator(7.5, random_seed=42).generate_pace_profile(251)
    b = pace.PaceFluctuator(7.5, random_seed=42).generate_pace_profile(251)
    assert a == b
    assert random.getstate() == before
    assert a != pace.PaceFluctuator(7.5, random_seed=43).generate_pace_profile(251)


def test_continuity_and_short_term_correlation():
    for seed in range(20):
        profile = pace.PaceFluctuator(7.5, random_seed=seed).generate_pace_profile(501)
        assert max(abs(a-b) for a, b in zip(profile, profile[1:])) < .6
    profile = pace.PaceFluctuator(7.5, random_seed=42, algorithm="steady").generate_pace_profile(2001)
    mean = sum(profile)/len(profile)
    correlation = sum((a-mean)*(b-mean) for a,b in zip(profile, profile[1:])) / sum((p-mean)**2 for p in profile)
    assert .65 < correlation < .95


@pytest.mark.parametrize("options", [
    {"base_pace_min_per_km":0}, {"base_pace_min_per_km":True}, {"base_pace_min_per_km":float("nan")},
    {"fluctuation_intensity":-1}, {"fluctuation_intensity":float("inf")}, {"fluctuation_intensity":True},
    {"algorithm":"missing"}, {"algorithm":[]},
])
def test_invalid_model_options_are_rejected(options):
    with pytest.raises(ValueError):
        pace.PaceFluctuator(**({"base_pace_min_per_km":7.5} | options))


def test_empty_single_and_invalid_distances():
    model = pace.PaceFluctuator(7.5)
    assert model.generate_pace_profile(0) == []
    assert model.generate_pace_profile(1) == [7.5]
    for distances in ([0], [-1], [float("nan")], [float("inf")], [True], []):
        with pytest.raises(ValueError):
            model.generate_pace_profile(2, distances)
    with pytest.raises(ValueError):
        model.generate_segment_times([-1], [-1])


def test_extension_context_normalization_and_duplicate_guard(monkeypatch):
    monkeypatch.setattr(pace, "_ALGORITHMS", dict(pace._ALGORITHMS))
    def custom(context, rng):
        assert context.distances_km == (0, .1, 1)
        assert context.base_pace_min_per_km == 7.5 and context.intensity == .15
        assert isinstance(rng, random.Random)
        return [6, 9, 9]
    algorithm = pace.PaceAlgorithm("test_custom", "Sample", "Test only", custom)
    pace.register_pace_algorithm(algorithm)
    with pytest.raises(ValueError):
        pace.register_pace_algorithm(algorithm)
    profile = pace.PaceFluctuator(7.5, algorithm="test_custom").generate_pace_profile(3, [.1,.9])
    assert profile[0]*.1 + profile[1]*.9 == pytest.approx(7.5)
    assert any(a["id"] == "test_custom" for a in pace.list_pace_algorithms())


@pytest.mark.parametrize("output", [[7.5], [7.5, 0], [7.5, float("nan")], [7.5, float("inf")], [True, 7.5]])
def test_extension_output_is_validated(monkeypatch, output):
    monkeypatch.setattr(pace, "_ALGORITHMS", dict(pace._ALGORITHMS))
    pace.register_pace_algorithm(pace.PaceAlgorithm("invalid", "Invalid", "Test", lambda c,r: output))
    with pytest.raises(ValueError):
        pace.PaceFluctuator(7.5, algorithm="invalid").generate_pace_profile(2)


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(routes.paths, "get_config_dir", lambda: str(tmp_path))
    return routes.create_app().test_client()


def test_preview_repeatability_and_disabled_fluctuation(client):
    assert {a["id"] for a in client.get('/api/pace/algorithms').json} >= {"natural", "steady", "progressive"}
    payload = {"distance_km":3.24, "pace":7.5, "seed":42, "pace_algorithm":"progressive"}
    before = random.getstate()
    response = client.post('/api/pace/preview', json=payload)
    assert response.status_code == 200
    assert response.json == client.post('/api/pace/preview', json=payload).json
    assert response.json['times_seconds'][-1] == pytest.approx(3.24*7.5*60)
    assert random.getstate() == before
    disabled = client.post('/api/pace/preview', json=payload | {"enable_pace_fluctuation":False}).json
    assert set(disabled['paces_min_per_km']) == {7.5}


@pytest.mark.parametrize("payload", [[], {"distance_km":0}, {"distance_km":101}, {"distance_km":True},
    {"pace":float("nan")}, {"pace":31}, {"pace_algorithm":"missing"}, {"pace_algorithm":{}},
    {"pace_intensity":2}, {"seed":True}, {"seed":1.5}, {"enable_pace_fluctuation":"false"}])
def test_preview_rejects_invalid_requests(client, payload):
    assert client.post('/api/pace/preview', json=payload).status_code == 400


def test_config_and_template_preserve_pace_options(tmp_path):
    manager = TemplateManager(ConfigManager(str(tmp_path)))
    saved = manager.save_template("Pace", "Test", {"pace_algorithm":"steady", "pace_intensity":.3})
    config = manager.apply_template(saved["id"])
    assert (config.pace_algorithm, config.pace_intensity) == ("steady", .3)
    assert manager.apply_template().pace_algorithm == "natural"
    with pytest.raises(ValueError):
        GenerationConfig(pace_algorithm="missing")


def test_uniform_timing_follows_unequal_geometry():
    track = ConfigManager("config").load_track("campus_default")
    analyzer = TrackAnalyzer(track.base_coordinates)
    gen = TrackGenerator(analyzer.analyze_track(), analyzer)
    points = [GeoPoint(0, 0), GeoPoint(.001, 0), GeoPoint(.003, 0), GeoPoint(.0031, 0)]
    start = datetime.datetime(2026, 11, 17, 7)
    result = gen.generate_tcx_trackpoints(points, start, 900, enable_pace_fluctuation=False)
    for point in result:
        seconds = (datetime.datetime.fromisoformat(point.time)-start).total_seconds()
        assert seconds == pytest.approx(900*point.distance_meters/result[-1].distance_meters, abs=1)
