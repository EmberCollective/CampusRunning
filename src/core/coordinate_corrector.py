#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Convert GCJ-02 track coordinates to WGS-84 before export."""

import math
from typing import List

from src.core.models import GeoPoint

_KRASOVSKY_SEMI_MAJOR_AXIS = 6378245.0
_KRASOVSKY_ECCENTRICITY_SQUARED = 0.00669342162296594323
_INVERSE_CONVERGENCE_DEGREES = 1e-10
_INVERSE_MAX_ITERATIONS = 8

class CoordinateCorrector:
    """Convert GCJ-02 coordinates to WGS-84 for fitness files."""

    def correct_coordinate(self, point: GeoPoint) -> GeoPoint:
        """Convert one point; coordinates outside China stay unchanged."""
        if self._outside_china(point.longitude, point.latitude):
            return point

        corrected = point
        for _ in range(_INVERSE_MAX_ITERATIONS):
            transformed = self._to_gcj02(corrected)
            longitude_delta = point.longitude - transformed.longitude
            latitude_delta = point.latitude - transformed.latitude
            corrected = GeoPoint(
                longitude=corrected.longitude + longitude_delta,
                latitude=corrected.latitude + latitude_delta,
            )
            if max(abs(longitude_delta), abs(latitude_delta)) <= (
                _INVERSE_CONVERGENCE_DEGREES
            ):
                break
        return corrected

    def correct_coordinates(self, coordinates: List[GeoPoint]) -> List[GeoPoint]:
        """Convert a coordinate sequence."""
        return [self.correct_coordinate(point) for point in coordinates]

    @staticmethod
    def _outside_china(longitude: float, latitude: float) -> bool:
        return not (
            72.004 < longitude < 137.8347
            and 0.8293 < latitude < 55.8271
        )

    def _to_gcj02(self, point: GeoPoint) -> GeoPoint:
        if self._outside_china(point.longitude, point.latitude):
            return point

        delta_lon = self._transform_longitude(
            point.longitude - 105.0, point.latitude - 35.0
        )
        delta_lat = self._transform_latitude(
            point.longitude - 105.0, point.latitude - 35.0
        )
        latitude_radians = math.radians(point.latitude)
        magic = 1 - (
            _KRASOVSKY_ECCENTRICITY_SQUARED
            * math.sin(latitude_radians) ** 2
        )
        sqrt_magic = math.sqrt(magic)
        delta_lat = (
            delta_lat
            * 180.0
            / (
                (
                    _KRASOVSKY_SEMI_MAJOR_AXIS
                    * (1 - _KRASOVSKY_ECCENTRICITY_SQUARED)
                    / (magic * sqrt_magic)
                )
                * math.pi
            )
        )
        delta_lon = (
            delta_lon
            * 180.0
            / (
                (
                    _KRASOVSKY_SEMI_MAJOR_AXIS
                    / sqrt_magic
                    * math.cos(latitude_radians)
                )
                * math.pi
            )
        )

        return GeoPoint(
            longitude=point.longitude + delta_lon,
            latitude=point.latitude + delta_lat,
        )

    @staticmethod
    def _transform_latitude(x: float, y: float) -> float:
        result = (
            -100.0
            + 2.0 * x
            + 3.0 * y
            + 0.2 * y * y
            + 0.1 * x * y
            + 0.2 * math.sqrt(abs(x))
        )
        result += (
            20.0 * math.sin(6.0 * x * math.pi)
            + 20.0 * math.sin(2.0 * x * math.pi)
        ) * 2.0 / 3.0
        result += (
            20.0 * math.sin(y * math.pi)
            + 40.0 * math.sin(y / 3.0 * math.pi)
        ) * 2.0 / 3.0
        result += (
            160.0 * math.sin(y / 12.0 * math.pi)
            + 320.0 * math.sin(y * math.pi / 30.0)
        ) * 2.0 / 3.0
        return result

    @staticmethod
    def _transform_longitude(x: float, y: float) -> float:
        result = (
            300.0
            + x
            + 2.0 * y
            + 0.1 * x * x
            + 0.1 * x * y
            + 0.1 * math.sqrt(abs(x))
        )
        result += (
            20.0 * math.sin(6.0 * x * math.pi)
            + 20.0 * math.sin(2.0 * x * math.pi)
        ) * 2.0 / 3.0
        result += (
            20.0 * math.sin(x * math.pi)
            + 40.0 * math.sin(x / 3.0 * math.pi)
        ) * 2.0 / 3.0
        result += (
            150.0 * math.sin(x / 12.0 * math.pi)
            + 300.0 * math.sin(x / 30.0 * math.pi)
        ) * 2.0 / 3.0
        return result
