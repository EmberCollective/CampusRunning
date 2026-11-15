"""Encode a candidate B5 SPORT44 file, not a verified hardware file format.

ExportData coordinates must already be WGS-84, as for FIT export. No coordinate
conversion or sensor-data generation takes place here. The observed Android
reader ignores the eight bytes before CRC32; this candidate writes zeros there.
Missing pressure, bearing, accuracy and point calories remain zero. Point pace
is seconds per kilometer, derived from the source speed without changing it.
Explicit segments preserve the summary and the client's GPS crossing choices.
Location type 1 selects the observed geographic-point branch; its exact hardware
meaning is unverified. No heart-rate data is invented (Keep may recalculate kcal).
"""

import math
import struct
import zlib
from datetime import datetime, timedelta, timezone

from src.core.cadence_generator import TIME_FORMAT, compute_lap_cadence_metrics
from src.core.models import ExportData


_LOCAL_TZ = timezone(timedelta(hours=8))  # Same local-clock convention as FIT.
_GPS = struct.Struct("<fffiddiBBhiffiiib")
_SECTION_POINTS = 32767  # Android reads the count as a signed int16.
_MAX_INT32 = (1 << 31) - 1
_MAX_FILE_SIZE = _MAX_INT32  # FileTable size is consumed as a Java array length.


def _finite(value: float, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{field} must be a finite number")
    try:
        finite = math.isfinite(value)
    except OverflowError:
        finite = False
    if not finite:
        raise ValueError(f"{field} must be a finite number")
    return value


def _int32(value: float, field: str, minimum: int = 0) -> int:
    result = round(_finite(value, field))
    if not minimum <= result <= _MAX_INT32:
        raise ValueError(f"{field} is outside the supported int32 range")
    return result


def encode_workout(data: ExportData) -> bytes:
    """Encode RUN=2 with GPS tag 8, aligned segments and a 78-byte description.

    As in FIT, first/last track timestamps determine the elapsed duration;
    summary distance uses nominal distance_km and points retain their cumulative
    distances. Seconds, meters and steps are rounded to integer wire fields.
    Duplicate seconds are supported; reversed time/distance and absent speed or
    cadence are rejected. This experiment has no pause-event representation.
    Kilometer boundaries follow the first rounded GPS distance crossing; the
    final unmatched segment uses the summary. Inconsistent boundaries reject.
    """
    points = data.trackpoints
    if points is None:
        raise ValueError("At least two GPS trackpoints are required")
    count = len(points)
    if count < 2:
        raise ValueError("At least two GPS trackpoints are required")
    sections = (count + _SECTION_POINTS - 1) // _SECTION_POINTS
    if count * _GPS.size + sections * 3 + 78 + 14 > _MAX_FILE_SIZE:
        raise ValueError("Workout file size exceeds the supported limit")
    if _finite(data.duration_seconds, "duration_seconds") <= 0:
        raise ValueError("duration_seconds must be positive")
    distance = _int32(_finite(data.distance_km, "distance_km") * 1000, "distance_km", 1)
    segment_count = (distance + 999) // 1000
    if segment_count > _SECTION_POINTS:
        raise ValueError("Segment count exceeds the supported int16 range")
    if count * _GPS.size + sections * 3 + 78 + 14 + 12 + segment_count * 14 > _MAX_FILE_SIZE:
        raise ValueError("Workout file size exceeds the supported limit")
    if not isinstance(data.calories, int) or isinstance(data.calories, bool):
        raise ValueError("calories must be a nonnegative integer")
    calories = _int32(data.calories * 1000, "calories")

    try:
        times = [
            datetime.strptime(point.time, TIME_FORMAT).replace(tzinfo=_LOCAL_TZ)
            for point in points
        ]
    except (ValueError, TypeError) as exc:
        raise ValueError("Trackpoint time must be local YYYY-MM-DDTHH:MM:SS") from exc
    timestamps = [_int32(time.timestamp(), "timestamp", 1) for time in times]
    if any(current < previous for previous, current in zip(timestamps, timestamps[1:])):
        raise ValueError("Trackpoint time must not move backwards")
    duration = timestamps[-1] - timestamps[0]
    if not 10 <= duration < 7 * 24 * 3600:
        raise ValueError("Track duration must be at least 10 seconds and below 7 days")

    body = bytearray()
    integrated_steps = 0.0
    previous_distance = 0.0
    point_distances = []
    for index, (point, timestamp) in enumerate(zip(points, timestamps)):
        latitude = _finite(point.latitude, "latitude")
        longitude = _finite(point.longitude, "longitude")
        if not -90 <= latitude <= 90 or not -180 <= longitude <= 180:
            raise ValueError("GPS coordinates are out of range")
        altitude = _finite(point.altitude, "altitude")
        speed = _finite(point.speed, "speed")
        if speed < 0:
            raise ValueError("speed must be nonnegative")
        speed_kmh = _finite(speed * 3.6, "speed")
        # Keep's PaceUtils uses milliseconds/meters, numerically seconds/km.
        # Zero speed has no finite pace; retain the client's zero/no-value form.
        pace_seconds_per_km = _finite(1000.0 / speed if speed else 0.0, "currentPace")
        point_distance = _finite(point.distance_meters, "distance_meters")
        if point_distance < previous_distance:
            raise ValueError("Trackpoint distance must not move backwards")
        previous_distance = point_distance
        cadence = point.run_cadence
        if isinstance(cadence, bool) or not isinstance(cadence, int) or not 0 <= cadence <= 127:
            raise ValueError("run_cadence must be an integer in 0..127 (total spm fits uint8)")
        if index:
            # Match compute_lap_cadence_metrics: right-endpoint cadence, total steps.
            integrated_steps += cadence * 2 / 60.0 * (timestamp - timestamps[index - 1])
        elapsed = timestamp - timestamps[0]
        if index % _SECTION_POINTS == 0:
            body.extend(struct.pack("<Bh", 8, min(_SECTION_POINTS, count - index)))
        wire_distance = _int32(point_distance, "distance_meters")
        point_distances.append(wire_distance)
        try:
            body.extend(_GPS.pack(
                speed_kmh, 0.0, 0.0, elapsed, longitude, latitude, elapsed,
                0, 0, 0, timestamp, pace_seconds_per_km, altitude,
                wire_distance,
                _int32(integrated_steps, "steps"), 0, 1,
            ))
        except (struct.error, OverflowError) as exc:
            raise ValueError("GPS values exceed their wire field sizes") from exc

    metrics = compute_lap_cadence_metrics(points)
    if metrics is None:
        raise ValueError("Trackpoint cadence cannot be integrated")
    # The shared helper omits totals above TCX's uint16 limit; this wire uses int32.
    steps = metrics[2] if metrics[2] is not None else _int32(integrated_steps, "steps")
    stride_cm = round(distance * 100 / steps) if steps else 0
    if not 0 <= stride_cm <= 255:
        raise ValueError("Average stride length exceeds the uint8 centimeter field")

    # h() can auto-add a duration without distance/pace; supply all four arrays.
    if point_distances[-1] > distance:
        raise ValueError("GPS distance exceeds summary distance")
    segment_seconds, segment_meters, segment_paces = [], [], []
    previous_seconds = previous_meters = point_index = 0
    for segment in range(1, segment_count + 1):
        # Match KitbitWorkoutLogUtils.K's first integer-distance crossing.
        while point_index < count and point_distances[point_index] < segment * 1000:
            point_index += 1
        if point_index < count:
            end_seconds = timestamps[point_index] - timestamps[0]
            end_meters = point_distances[point_index]
            if segment == segment_count and (
                point_index != count - 1 or end_seconds != duration or end_meters != distance
            ):
                raise ValueError("Final GPS segment does not match the summary endpoint")
        elif segment == segment_count:
            end_seconds, end_meters = duration, distance
        else:
            raise ValueError("Missing GPS crossing for a non-final kilometer segment")
        seconds = end_seconds - previous_seconds
        meters = end_meters - previous_meters
        if seconds <= 0 or not 0 < meters <= _SECTION_POINTS:
            raise ValueError("Segment requires positive duration and int16 distance")
        segment_seconds.append(seconds)
        segment_meters.append(meters)
        segment_paces.append(_int32(seconds * 1000 / meters, "segment pace", 1))
        previous_seconds, previous_meters = end_seconds, end_meters
    # Confirmed V2 tags avoid signed-short overflow in duration and pace.
    for tag, code, values in (
        (40, "i", segment_seconds), (43, "i", segment_seconds),
        (20, "h", segment_meters), (44, "i", segment_paces),
    ):
        body.extend(struct.pack("<Bh", tag, segment_count))
        body.extend(struct.pack(f"<{segment_count}{code}", *values))

    description = bytearray(78)
    struct.pack_into("<7i", description, 0, 2, duration, timestamps[0], timestamps[-1],
                     distance, steps, calories)
    description[76] = metrics[0] * 2
    description[77] = stride_cm
    body.extend(description)
    # shortcut: opaque8 and absent optional metrics are zero candidates; verify on hardware.
    body.extend(struct.pack("<h8x", len(description)))
    body.extend(struct.pack("<I", zlib.crc32(body)))
    return bytes(body)
