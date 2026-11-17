"""Distance-aware pace models and an explicit registration API for local algorithms."""

import math
import random
import re
from dataclasses import dataclass
from itertools import accumulate
from typing import Callable, Optional


@dataclass(frozen=True)
class PaceContext:
    """Algorithm input: cumulative sample distances (km), target pace (min/km)."""

    distances_km: tuple[float, ...]
    base_pace_min_per_km: float
    intensity: float


@dataclass(frozen=True)
class PaceAlgorithm:
    id: str
    name: str
    description: str
    generate: Callable[[PaceContext, random.Random], list[float]]


_ALGORITHMS: dict[str, PaceAlgorithm] = {}


def register_pace_algorithm(algorithm: PaceAlgorithm) -> None:
    """Register trusted local Python code at startup; duplicate IDs are rejected."""
    if not isinstance(algorithm.id, str) or not re.fullmatch(r"[a-z0-9_-]{1,64}", algorithm.id):
        raise ValueError("配速算法 ID 仅允许 1–64 个小写字母、数字、下划线或连字符")
    if algorithm.id in _ALGORITHMS:
        raise ValueError(f"配速算法已注册: {algorithm.id}")
    if not algorithm.name or not algorithm.description or not callable(algorithm.generate):
        raise ValueError("配速算法需要名称、说明和可调用的生成函数")
    _ALGORITHMS[algorithm.id] = algorithm


def get_pace_algorithm(algorithm_id: str) -> PaceAlgorithm:
    if not isinstance(algorithm_id, str) or algorithm_id not in _ALGORITHMS:
        raise ValueError("未知配速算法，请选择已注册的算法")
    return _ALGORITHMS[algorithm_id]


def list_pace_algorithms() -> list[dict[str, str]]:
    return [{"id": a.id, "name": a.name, "description": a.description} for a in _ALGORITHMS.values()]


def _smoothstep(value: float) -> float:
    value = max(0.0, min(1.0, value))
    return value * value * (3 - 2 * value)


def _correlated_paces(context, rng, warmup=0.0, drift=0.0, finish=0.0):
    # Engineering parameters, not population estimates: 45 s correlation and ~2.4% noise at intensity .15.
    total_seconds = context.distances_km[-1] * context.base_pace_min_per_km * 60
    warmup_seconds = min(90.0, total_seconds / 5)
    finish_seconds = min(75.0, total_seconds * .12)
    noise, previous_seconds = rng.gauss(0, .16), 0.0
    paces = []
    for distance in context.distances_km:
        seconds = distance * context.base_pace_min_per_km * 60
        rho = math.exp(-(seconds - previous_seconds) / 45.0)
        noise = rho * noise + math.sqrt(max(0.0, 1 - rho * rho)) * rng.gauss(0, .16)
        progress = seconds / total_seconds
        trend = warmup * math.exp(-seconds / warmup_seconds)
        trend += drift * _smoothstep((progress - .4) / .6)
        trend += finish * _smoothstep((seconds - total_seconds + finish_seconds) / finish_seconds)
        paces.append(context.base_pace_min_per_km * math.exp(context.intensity * (trend + noise)))
        previous_seconds = seconds
    return paces


def _natural(context, rng):
    # Choose a finish once per workout, instead of switching between sprint/rest at every sample.
    return _correlated_paces(context, rng, rng.uniform(.4, .8), rng.uniform(0, .4), rng.uniform(-.4, .2))


def _steady(context, rng):
    return _correlated_paces(context, rng)


def _progressive(context, rng):
    return _correlated_paces(context, rng, warmup=.2, drift=-.8)


for _algorithm in (
    PaceAlgorithm("natural", "自然慢跑", "缓慢进入状态，途中连续起伏，末段可能小幅加速或放慢。", _natural),
    PaceAlgorithm("steady", "稳定跑", "围绕目标配速连续小幅波动，不设固定冲刺。", _steady),
    PaceAlgorithm("progressive", "渐进跑", "从较慢配速平滑加快，适合渐进训练的样例。", _progressive),
):
    register_pace_algorithm(_algorithm)


class PaceFluctuator:
    """Generate positive, distance-weighted pace samples without changing global RNG state."""

    def __init__(
        self,
        base_pace_min_per_km: float,
        fluctuation_intensity: float = .15,
        random_seed: Optional[int] = None,
        *,
        algorithm: str = "natural",
    ) -> None:
        if (isinstance(base_pace_min_per_km, bool)
                or not isinstance(base_pace_min_per_km, (int, float))
                or not math.isfinite(base_pace_min_per_km) or base_pace_min_per_km <= 0):
            raise ValueError("目标配速必须是大于 0 的有限数值")
        if (isinstance(fluctuation_intensity, bool)
                or not isinstance(fluctuation_intensity, (int, float))
                or not math.isfinite(fluctuation_intensity) or not 0 <= fluctuation_intensity <= 1):
            raise ValueError("配速波动强度必须在 0–1 之间")
        self.base_pace = base_pace_min_per_km
        self.fluctuation_intensity = fluctuation_intensity
        self.algorithm = get_pace_algorithm(algorithm)
        self._rng = random.Random(random_seed)

    def generate_pace_profile(
        self, num_points: int, segment_distances: Optional[list[float]] = None,
    ) -> list[float]:
        """Return one min/km value per point; each value applies to the following segment.

        segment_distances contains N-1 actual lengths in km; omitted means 20 m spacing.
        The last pace repeats the last segment. Normalization preserves the distance-weighted target.
        """
        if isinstance(num_points, bool) or not isinstance(num_points, int) or num_points < 0:
            raise ValueError("轨迹点数量必须是非负整数")
        distances = [.02] * max(0, num_points - 1) if segment_distances is None else list(segment_distances)
        if len(distances) != max(0, num_points - 1):
            raise ValueError("分段距离数量必须等于轨迹点数量减一")
        if any(isinstance(d, bool) or not isinstance(d, (int, float)) or not math.isfinite(d) or d < 0 for d in distances):
            raise ValueError("分段距离必须是非负有限数值（公里）")
        if num_points < 2:
            return [self.base_pace] * num_points
        total = sum(distances)
        if not math.isfinite(total) or total <= 0:
            raise ValueError("轨迹总距离必须大于 0 且有限")
        context = PaceContext(tuple(accumulate(distances, initial=0.0)), self.base_pace, self.fluctuation_intensity)
        profile = list(self.algorithm.generate(context, self._rng))
        if len(profile) != num_points or any(
            isinstance(p, bool) or not isinstance(p, (int, float)) or not math.isfinite(p) or p <= 0 for p in profile
        ):
            raise ValueError("配速算法必须为每个轨迹点返回一个大于 0 的有限配速值")
        average = sum(p * (d / total) for p, d in zip(profile, distances))
        if not math.isfinite(average) or average <= 0:
            raise ValueError("配速算法返回的加权平均值无效")
        profile = [p / average * self.base_pace for p in profile]
        if any(not math.isfinite(p) or p <= 0 for p in profile):
            raise ValueError("配速算法归一化后的值无效")
        profile[-1] = profile[-2]
        return profile

    def generate_segment_times(self, pace_profile: list[float], segment_distances: list[float]) -> list[float]:
        """Calculate seconds from min/km and km; the caller supplies one pace per segment."""
        if len(pace_profile) != len(segment_distances):
            raise ValueError("配速曲线和分段距离数量不匹配")
        if any(not math.isfinite(p) or p <= 0 for p in pace_profile) or any(
            not math.isfinite(d) or d < 0 for d in segment_distances
        ):
            raise ValueError("配速须为正数，分段距离须为非负有限数值")
        times = [p * d * 60 for p, d in zip(pace_profile, segment_distances)]
        if any(not math.isfinite(t) or t < 0 for t in times):
            raise ValueError("分段时间必须是非负有限数值")
        return times
