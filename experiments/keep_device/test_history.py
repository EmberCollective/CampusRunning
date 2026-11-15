"""Independent byte checks for the candidate; no Keep compatibility claim."""

import random
import struct
import zlib
from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from experiments.keep_device.history import encode_workout
from src.core.cadence_generator import compute_lap_cadence_metrics
from src.core.coordinate_corrector import CoordinateCorrector
from src.core.models import ExportData, GeoPoint
from src.core.track_analyzer import TrackAnalyzer
from src.core.track_generator import TrackGenerator


@pytest.fixture
def workout():
    """Use the actual project generator and its WGS-84 conversion."""
    analyzer = TrackAnalyzer([
        GeoPoint(106.670, 26.440), GeoPoint(106.675, 26.440),
        GeoPoint(106.675, 26.444), GeoPoint(106.670, 26.444),
    ])
    generator = TrackGenerator(analyzer.analyze_track(), analyzer, CoordinateCorrector())
    geometry = generator.generate_smooth_track(3.0, 20, enable_randomness=False)
    start = datetime(2026, 9, 4, 7)
    random_state = random.getstate()
    try:
        random.seed(63)
        points = generator.generate_tcx_trackpoints(geometry, start, 1350.0)
    finally:
        random.setstate(random_state)
    # This generated geometry exceeds 3 km; use a summary with a valid tail.
    return ExportData(start.date(), start, 3.5, 1350.0, 180, points)


def _segments(encoded, point_count):
    """Independently inspect the four sections after the GPS sections."""
    offset = point_count * 65 + ((point_count + 32766) // 32767) * 3
    result = {}
    for expected_tag, code in ((40, "i"), (43, "i"), (20, "h"), (44, "i")):
        tag, count = struct.unpack_from("<Bh", encoded, offset)
        assert tag == expected_tag and count > 0
        offset += 3
        result[tag] = struct.unpack_from(f"<{count}{code}", encoded, offset)
        offset += count * struct.calcsize(code)
    assert offset == len(encoded) - 92
    assert len({len(values) for values in result.values()}) == 1
    return result


def _sample_workout(workout, summary_meters, samples):
    points = [replace(
        workout.trackpoints[0], time=(workout.start_time + timedelta(seconds=seconds)).isoformat(),
        distance_meters=meters, run_cadence=80, speed=2.0,
    ) for seconds, meters in samples]
    return replace(workout, distance_km=summary_meters / 1000,
                   duration_seconds=samples[-1][0], trackpoints=points)


def test_generated_track_round_trips_independently(workout):
    encoded = encode_workout(workout)
    assert struct.unpack_from("<h", encoded, len(encoded) - 14) == (78,)
    assert encoded[-12:-4] == bytes(8)
    assert struct.unpack_from("<I", encoded, len(encoded) - 4)[0] == zlib.crc32(encoded[:-4])
    description = encoded[-92:-14]
    kind, duration, start, end, distance, steps, calories = struct.unpack_from("<7i", description)
    assert kind == 2
    assert datetime.fromtimestamp(start, timezone.utc) == datetime(2026, 9, 3, 23, tzinfo=timezone.utc)
    assert duration == end - start
    assert distance == 3500
    assert calories == 180000
    average_cadence, _, expected_steps = compute_lap_cadence_metrics(workout.trackpoints)
    assert steps == expected_steps
    assert description[76] == average_cadence * 2
    assert description[77] == round(350000 / expected_steps)
    assert description[28:76] == bytes(48)
    assert struct.unpack_from("<Bh", encoded) == (8, len(workout.trackpoints))
    assert len(encoded) == 3 + 65 * len(workout.trackpoints) + 78 + 14 + 12 + 4 * 14
    segments = _segments(encoded, len(workout.trackpoints))
    assert sum(segments[40]) == duration
    assert sum(segments[20]) == distance

    total_steps = 0.0
    previous_time = workout.start_time
    for index, point in enumerate(workout.trackpoints):
        offset = 3 + 65 * index
        point_time = datetime.fromisoformat(point.time)
        elapsed = int((point_time - workout.start_time).total_seconds())
        if index:
            total_steps += point.run_cadence * 2 / 60 * (point_time - previous_time).total_seconds()
        previous_time = point_time
        assert struct.unpack_from("<f", encoded, offset)[0] == pytest.approx(point.speed * 3.6)
        assert encoded[offset + 4:offset + 12] == bytes(8)
        assert struct.unpack_from("<i", encoded, offset + 12) == (elapsed,)
        # Exact doubles catch an accidental second GCJ-02/WGS-84 conversion.
        assert struct.unpack_from("<dd", encoded, offset + 16) == (point.longitude, point.latitude)
        assert struct.unpack_from("<i", encoded, offset + 32) == (elapsed,)
        assert encoded[offset + 36:offset + 40] == bytes(4)
        assert struct.unpack_from("<i", encoded, offset + 40) == (start + elapsed,)
        assert struct.unpack_from("<f", encoded, offset + 44)[0] == pytest.approx(1000 / point.speed)
        assert struct.unpack_from("<f", encoded, offset + 48)[0] == pytest.approx(point.altitude)
        assert struct.unpack_from("<ii", encoded, offset + 52) == (round(point.distance_meters), round(total_steps))
        assert struct.unpack_from("<i", encoded, offset + 60) == (0,)
        assert encoded[offset + 64] == 1
    assert round(total_steps) == steps
    assert start + elapsed == end


@pytest.mark.parametrize("speed, expected_pace", [(2.5, 400.0), (2.0, 500.0), (0.0, 0.0)])
def test_point_pace_is_seconds_per_kilometer_from_source_speed(workout, speed, expected_pace):
    points = [replace(workout.trackpoints[0], speed=speed), *workout.trackpoints[1:]]
    encoded = encode_workout(replace(workout, trackpoints=points))
    assert struct.unpack_from("<f", encoded, 3)[0] == pytest.approx(speed * 3.6)
    assert struct.unpack_from("<f", encoded, 3 + 44) == (expected_pace,)
    assert struct.unpack_from("<7i", encoded, len(encoded) - 92) == struct.unpack_from(
        "<7i", encode_workout(workout), len(encoded) - 92,
    )


def test_point_pace_overflow_is_rejected(workout):
    points = [replace(workout.trackpoints[0], speed=1e-320), *workout.trackpoints[1:]]
    with pytest.raises(ValueError, match="currentPace"):
        encode_workout(replace(workout, trackpoints=points))


def test_duplicate_seconds_use_zero_duration_step_interval(workout):
    points = [workout.trackpoints[0], workout.trackpoints[0], *workout.trackpoints[1:]]
    encoded = encode_workout(replace(workout, trackpoints=points))
    assert struct.unpack_from("<i", encoded, 3 + 65 + 56) == (0,)
    assert struct.unpack_from("<i", encoded, len(encoded) - 92 + 20)[0] == compute_lap_cadence_metrics(points)[2]


def test_large_track_splits_signed_counts_without_dropping_points(workout):
    points = [workout.trackpoints[0]] * 32767 + [replace(workout.trackpoints[-1], distance_meters=915)]
    encoded = encode_workout(replace(workout, trackpoints=points, distance_km=1))
    second = 3 + 32767 * 65
    assert struct.unpack_from("<Bh", encoded) == (8, 32767)
    assert struct.unpack_from("<Bh", encoded, second) == (8, 1)
    assert struct.unpack_from("<dd", encoded, second + 3 + 16) == (
        points[-1].longitude, points[-1].latitude,
    )
    assert len(encoded) == 6 + 32768 * 65 + 92 + 26
    assert _segments(encoded, len(points))[20] == (1000,)


@pytest.mark.parametrize("changes, message", [
    ({"latitude": float("nan")}, "latitude"),
    ({"longitude": 181}, "coordinates"),
    ({"altitude": float("inf")}, "altitude"),
    ({"altitude": 1e40}, "wire field"),
    ({"speed": None}, "speed"),
    ({"speed": -1}, "speed"),
    ({"speed": 1e308}, "speed"),
    ({"run_cadence": None}, "run_cadence"),
    ({"run_cadence": 128}, "run_cadence"),
    ({"run_cadence": 80.5}, "run_cadence"),
    ({"distance_meters": -1}, "distance"),
    ({"distance_meters": 2 ** 31}, "distance_meters"),
    ({"time": "2026-09-04T07:00:00Z"}, "local"),
])
def test_invalid_point_values_are_rejected(workout, changes, message):
    points = [*workout.trackpoints[:-1], replace(workout.trackpoints[-1], **changes)]
    with pytest.raises(ValueError, match=message):
        encode_workout(replace(workout, trackpoints=points))


@pytest.mark.parametrize("changes, message", [
    ({"trackpoints": []}, "two GPS"),
    ({"trackpoints": None}, "two GPS"),
    ({"distance_km": None}, "distance_km"),
    ({"distance_km": True}, "distance_km"),
    ({"distance_km": 0}, "distance_km"),
    ({"distance_km": float("nan")}, "distance_km"),
    ({"distance_km": 2 ** 31}, "distance_km"),
    ({"distance_km": 10 ** 400}, "distance_km"),
    ({"distance_km": 32768}, "Segment count"),
    ({"distance_km": 100}, "stride length"),
    ({"calories": -1}, "calories"),
    ({"calories": 2 ** 31}, "calories"),
    ({"duration_seconds": 0}, "duration_seconds"),
    ({"duration_seconds": float("inf")}, "duration_seconds"),
])
def test_invalid_summary_values_are_rejected(workout, changes, message):
    with pytest.raises(ValueError, match=message):
        encode_workout(replace(workout, **changes))


def test_time_reversal_is_not_silently_reordered(workout):
    points = [workout.trackpoints[1], workout.trackpoints[0], *workout.trackpoints[2:]]
    with pytest.raises(ValueError, match="time.*backwards"):
        encode_workout(replace(workout, trackpoints=points))


def test_timestamp_overflow_is_rejected(workout):
    points = [replace(point, time=point.time.replace("2026", "2040")) for point in workout.trackpoints]
    with pytest.raises(ValueError, match="timestamp"):
        encode_workout(replace(workout, trackpoints=points))


@pytest.mark.parametrize("seconds", [9, 7 * 24 * 3600])
def test_unsupported_track_duration_is_rejected(workout, seconds):
    end = workout.start_time + timedelta(seconds=seconds)
    points = [workout.trackpoints[0], replace(workout.trackpoints[-1], time=end.isoformat())]
    with pytest.raises(ValueError, match="Track duration"):
        encode_workout(replace(workout, trackpoints=points))


def test_steps_above_tcx_limit_remain_total_steps(workout):
    data = _sample_workout(workout, 50000, [(index * 600, index * 1000) for index in range(51)])
    points = data.trackpoints
    assert compute_lap_cadence_metrics(points) == (80, 80, None)
    encoded = encode_workout(data)
    assert struct.unpack_from("<i", encoded, len(encoded) - 92 + 20) == (80000,)
    assert struct.unpack_from("<i", encoded, 3 + 50 * 65 + 56) == (80000,)
    assert encoded[-92 + 76] == 160


def test_nominal_distance_does_not_replace_point_distance(workout):
    encoded = encode_workout(replace(workout, distance_km=3.8))
    assert struct.unpack_from("<i", encoded, len(encoded) - 92 + 16) == (3800,)
    last = 3 + 65 * (len(workout.trackpoints) - 1)
    assert struct.unpack_from("<i", encoded, last + 52) == (round(workout.trackpoints[-1].distance_meters),)


def test_wire_file_limit_is_checked_before_allocating(workout):
    class OversizedPoints(list):
        def __len__(self):
            return 1 << 31

    with pytest.raises(ValueError, match="file size"):
        encode_workout(replace(workout, trackpoints=OversizedPoints()))


def test_explicit_segments_prevent_implicit_zero_pace_and_distance(workout):
    data = _sample_workout(workout, 1000, [(0, 0), (200, 450), (411, 914.612384)])
    encoded = encode_workout(data)
    assert _segments(encoded, 3) == {40: (411,), 43: (411,), 20: (1000,), 44: (411,)}
    # Keep's h() sees one supplied duration, so it will not append a bare one.
    assert struct.unpack_from("<i", encoded, len(encoded) - 92 + 16) == (1000,)
    assert struct.unpack_from("<i", encoded, 3 + 2 * 65 + 52) == (915,)
    assert len(encoded) == 3 + 3 * 65 + 26 + 92


def test_multiple_segments_match_rounded_crossings_and_partial_summary_tail(workout):
    data = _sample_workout(workout, 2500, [
        (0, 0), (390, 999.4), (400, 999.6), (410, 1025),
        (800, 2010.2), (1000, 2450),
    ])
    encoded = encode_workout(data)
    # K() chooses 999.6 -> wire1000 at400s, not the later1025 point.
    assert _segments(encoded, 6) == {
        40: (400, 400, 200), 43: (400, 400, 200),
        20: (1000, 1010, 490), 44: (400, 396, 408),
    }
    assert struct.unpack_from("<i", encoded, 3 + 5 * 65 + 52) == (2450,)


def test_subkilometer_tail_uses_distance_normalized_pace(workout):
    data = _sample_workout(workout, 750, [(0, 0), (300, 700)])
    assert _segments(encode_workout(data), 2) == {
        40: (300,), 43: (300,), 20: (750,), 44: (400,),
    }


def test_exact_final_kilometer_crossing_matches_summary(workout):
    data = _sample_workout(workout, 2000, [(0, 0), (400, 1000), (900, 2000)])
    assert _segments(encode_workout(data), 3) == {
        40: (400, 500), 43: (400, 500), 20: (1000, 1000), 44: (400, 500),
    }


def test_v2_time_and_pace_do_not_overflow_signed_short(workout):
    data = _sample_workout(workout, 500, [(0, 0), (40000, 450)])
    assert _segments(encode_workout(data), 2) == {
        40: (40000,), 43: (40000,), 20: (500,), 44: (80000,),
    }


@pytest.mark.parametrize("summary_meters, samples, message", [
    (1000, [(0, 0), (411, 1001)], "GPS distance exceeds"),
    (1000, [(0, 0), (400, 999.6), (411, 1000)], "Final GPS segment"),
    (3500, [(0, 0), (400, 1010), (800, 2010), (1200, 2900)], "Missing GPS crossing"),
    (3000, [(0, 0), (800, 2010), (1200, 2900)], "positive duration"),
    (2500, [(0, 0), (500, 1000), (500, 2000), (1000, 2450)], "positive duration"),
    (1500, [(0, 0), (500, 1499.6), (600, 1499.7)], "positive duration"),
])
def test_inconsistent_segment_boundaries_are_rejected(workout, summary_meters, samples, message):
    with pytest.raises(ValueError, match=message):
        encode_workout(_sample_workout(workout, summary_meters, samples))
