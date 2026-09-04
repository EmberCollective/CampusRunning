#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""CadenceGenerator 与 Lap 聚合函数的单元测试"""

import random
from datetime import datetime, timedelta

import pytest

from src.core.cadence_generator import (
    CadenceGenerator,
    compute_lap_cadence_metrics,
)
from src.core.models import TrackpointData


def make_trackpoint(time: datetime, cadence=None, speed=None) -> TrackpointData:
    """构造测试用轨迹点"""
    return TrackpointData(
        time=time.strftime("%Y-%m-%dT%H:%M:%S"),
        latitude=26.44,
        longitude=106.67,
        altitude=100.0,
        distance_meters=0.0,
        run_cadence=cadence,
        speed=speed,
    )


@pytest.mark.unit
class TestCadenceGenerator:
    """步频曲线生成测试"""

    def test_values_in_plausible_range(self):
        gen = CadenceGenerator(random_seed=42)
        speeds = [random.uniform(1.5, 4.5) for _ in range(500)]
        profile = gen.generate_cadence_profile(len(speeds), speeds)

        assert len(profile) == 500
        for spm in profile:
            assert 150 <= spm <= 192
            single_foot = round(spm / 2)
            assert 75 <= single_foot <= 96

    def test_cadence_increases_with_speed(self):
        gen = CadenceGenerator(random_seed=7)
        n = 200
        low = gen.generate_cadence_profile(n, [2.0] * n)
        high = gen.generate_cadence_profile(n, [3.5] * n)

        assert sum(high) / n > sum(low) / n

    def test_phase_pattern(self):
        gen = CadenceGenerator(random_seed=3)
        n = 200
        profile = gen.generate_cadence_profile(n, [2.38] * n)

        warmup = profile[: n // 10]           # 0-10% 热身
        steady = profile[n // 10: n * 7 // 10]  # 10-70% 稳定
        final = profile[n * 9 // 10:]          # 90-100% 冲刺

        warmup_avg = sum(warmup) / len(warmup)
        steady_avg = sum(steady) / len(steady)
        final_avg = sum(final) / len(final)

        assert warmup_avg < steady_avg < final_avg

    def test_reproducible_with_seed(self):
        speeds = [2.5] * 50
        profile_a = CadenceGenerator(random_seed=99).generate_cadence_profile(50, speeds)
        profile_b = CadenceGenerator(random_seed=99).generate_cadence_profile(50, speeds)

        assert profile_a == profile_b

    def test_stride_sanity(self):
        """步幅 = 60·v/总步频 必须落在合理跑者区间"""
        gen = CadenceGenerator(random_seed=11)
        for speed in (2.0, 2.38, 3.0, 3.5):
            profile = gen.generate_cadence_profile(30, [speed] * 30)
            for spm in profile:
                stride = 60.0 * speed / spm
                assert 0.6 <= stride <= 1.5

    def test_edge_num_points(self):
        gen = CadenceGenerator(random_seed=5)

        assert gen.generate_cadence_profile(0, []) == []

        single = gen.generate_cadence_profile(1, [2.4])
        assert len(single) == 1
        assert 150 <= single[0] <= 192

    def test_uniform_speed_nonconstant_output(self):
        """恒速输入时相位与噪声仍应产生非常数曲线"""
        gen = CadenceGenerator(random_seed=13)
        profile = gen.generate_cadence_profile(100, [2.38] * 100)

        assert len(set(profile)) > 1


@pytest.mark.unit
class TestComputeLapCadenceMetrics:
    """Lap 级步频积分测试"""

    def test_basic_integration(self):
        base = datetime(2026, 9, 4, 7, 0, 0)
        points = [
            make_trackpoint(base, cadence=80),
            make_trackpoint(base + timedelta(seconds=300), cadence=82),
            make_trackpoint(base + timedelta(seconds=600), cadence=84),
        ]

        result = compute_lap_cadence_metrics(points)

        assert result is not None
        avg_cadence, max_cadence, total_steps = result
        # 段1: 82*2/60*300=820 步; 段2: 84*2/60*300=840 步
        assert total_steps == 820 + 840
        assert avg_cadence == round(1660 / 10 / 2)
        assert max_cadence == 84

    def test_insufficient_points_returns_none(self):
        base = datetime(2026, 9, 4, 7, 0, 0)

        assert compute_lap_cadence_metrics([]) is None
        assert compute_lap_cadence_metrics(
            [make_trackpoint(base, cadence=80)]
        ) is None

    def test_points_without_cadence_filtered(self):
        base = datetime(2026, 9, 4, 7, 0, 0)
        points = [
            make_trackpoint(base, cadence=None),
            make_trackpoint(base + timedelta(seconds=60), cadence=80),
            make_trackpoint(base + timedelta(seconds=120), cadence=None),
            make_trackpoint(base + timedelta(seconds=180), cadence=80),
        ]

        result = compute_lap_cadence_metrics(points)

        assert result is not None
        _, _, total_steps = result
        # 有效点只有首尾两个（跨120秒）
        assert total_steps == round(80 * 2 / 60 * 120)

    def test_all_without_cadence_returns_none(self):
        base = datetime(2026, 9, 4, 7, 0, 0)
        points = [make_trackpoint(base), make_trackpoint(base + timedelta(seconds=60))]

        assert compute_lap_cadence_metrics(points) is None

    def test_zero_time_span_returns_none(self):
        base = datetime(2026, 9, 4, 7, 0, 0)
        points = [
            make_trackpoint(base, cadence=80),
            make_trackpoint(base, cadence=82),
        ]

        assert compute_lap_cadence_metrics(points) is None

    def test_steps_overflow_returns_none_steps(self):
        base = datetime(2026, 9, 4, 7, 0, 0)
        points = [
            make_trackpoint(base, cadence=90),
            make_trackpoint(base + timedelta(minutes=400), cadence=90),
        ]

        result = compute_lap_cadence_metrics(points)

        assert result is not None
        avg_cadence, max_cadence, total_steps = result
        # 90*2/60*24000s = 72000 > 65535
        assert total_steps is None
        assert avg_cadence == 90
        assert max_cadence == 90
