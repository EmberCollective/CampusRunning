#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""TrackGenerator 步频接线测试"""

import datetime

import pytest

from src.core.models import GeoPoint
from src.core.track_analyzer import TrackAnalyzer
from src.core.track_generator import TrackGenerator

# 简单方形轨迹（约 1880 米周长，多圈时可复现量纲问题）
BASE_COORDS = [
    GeoPoint(longitude=106.670, latitude=26.440),
    GeoPoint(longitude=106.675, latitude=26.440),
    GeoPoint(longitude=106.675, latitude=26.444),
    GeoPoint(longitude=106.670, latitude=26.444),
]

START_TIME = datetime.datetime(2026, 9, 4, 7, 0, 0)


def make_generator(enable_cadence: bool = True) -> TrackGenerator:
    analyzer = TrackAnalyzer(BASE_COORDS)
    return TrackGenerator(
        track_analysis=analyzer.analyze_track(),
        analyzer=analyzer,
        enable_cadence=enable_cadence,
    )


@pytest.mark.integration
class TestCadenceWiring:
    """两条生成路径的步频接线测试"""

    def test_pace_path_populates_cadence(self):
        track_gen = make_generator()
        geo_points = track_gen.generate_smooth_track(3.0, 50)
        trackpoints = track_gen.generate_tcx_trackpoints(
            geo_points, START_TIME, 3.0 * 7.5 * 60,
            base_pace_min_per_km=7.5,
            enable_pace_fluctuation=True,
            enable_cadence=True,
        )

        assert len(trackpoints) > 2
        for tp in trackpoints:
            assert tp.run_cadence is not None
            assert 75 <= tp.run_cadence <= 96
            assert tp.speed is not None
            assert tp.speed > 0

    def test_uniform_path_populates_cadence(self):
        track_gen = make_generator()
        geo_points = track_gen.generate_smooth_track(3.0, 50)
        trackpoints = track_gen.generate_tcx_trackpoints(
            geo_points, START_TIME, 3.0 * 7.5 * 60,
            base_pace_min_per_km=None,
            enable_cadence=True,
        )

        assert len(trackpoints) > 2
        for tp in trackpoints:
            assert tp.run_cadence is not None
            assert 75 <= tp.run_cadence <= 96
            assert tp.speed is not None
            # 3km / 7.5min/km = 2.22 m/s；若误用单圈 base_distance
            # （约1880米）会得到 ~1.39 m/s，此断言防量纲回归
            assert tp.speed > 2.0

        # 累计距离应覆盖多圈全程（约 3km），而非止步于单圈长度
        assert trackpoints[-1].distance_meters > 2500

    def test_disable_cadence_yields_none(self):
        track_gen = make_generator(enable_cadence=False)
        geo_points = track_gen.generate_smooth_track(3.0, 50)
        trackpoints = track_gen.generate_tcx_trackpoints(
            geo_points, START_TIME, 3.0 * 7.5 * 60,
            base_pace_min_per_km=7.5,
            enable_pace_fluctuation=True,
            enable_cadence=False,
        )

        for tp in trackpoints:
            assert tp.run_cadence is None
            assert tp.speed is None

    def test_default_enable_cadence(self):
        """generate_tcx_trackpoints 默认启用步频"""
        track_gen = make_generator()
        geo_points = track_gen.generate_smooth_track(2.0, 50)
        trackpoints = track_gen.generate_tcx_trackpoints(
            geo_points, START_TIME, 2.0 * 7.5 * 60,
            base_pace_min_per_km=7.5,
        )

        for tp in trackpoints:
            assert tp.run_cadence is not None
