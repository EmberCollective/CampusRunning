#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
步频生成器
为跑步数据生成真实的步频曲线和步数统计

作者: 猫娘幽浮喵
功能:
1. 根据速度推导步频（步频与速度正相关）
2. 基于跑步阶段（热身/稳定/疲劳/冲刺）调整步频
3. 按时间积分计算 Lap 级步数统计（平均步频/最大步频/总步数）

TCX 步频语义说明:
- Trackpoint 的 Cadence 与 TPX 扩展中的 RunCadence 均为单脚步频
  （总步频/2，真实 Garmin 跑步导出典型值 75-95）
- Lap 级 LX 扩展中的 Steps 为双脚合计总步数
"""

import logging
import math
import random
from datetime import datetime
from typing import List, Optional, Tuple

from src.core.models import TrackpointData

logger = logging.getLogger(__name__)

# TrackpointData.time 的时间格式（本地时间，无时区）
TIME_FORMAT = "%Y-%m-%dT%H:%M:%S"

# LX 扩展中 Steps 元素为 unsignedShort，上限 65535
MAX_LAP_STEPS = 65535


class CadenceGenerator:
    """步频生成器类

    根据速度曲线和跑步阶段生成具有真实感的步频曲线。
    步频与速度正相关（步幅 = 60·v/总步频 保持在合理区间），
    并通过阶段乘数和小幅随机噪声增强自然感。
    """

    # 步频-速度线性映射参数（总步频，双脚合计，单位: 步/分钟; 速度: 米/秒）
    CAD_INTERCEPT_SPM: float = 118.0
    CAD_SLOPE_SPM_PER_MS: float = 20.0
    CAD_MIN_SPM: int = 150
    CAD_MAX_SPM: int = 192

    def __init__(self, random_seed: Optional[int] = None) -> None:
        """初始化步频生成器。

        Args:
            random_seed: 随机种子，用于可重现的结果。
        """
        if random_seed is not None:
            random.seed(random_seed)

        # 定义跑步阶段（起止进度百分比），与 PaceFluctuator 保持同构
        self.phases = {
            'warmup': (0.0, 0.1),      # 0-10% 热身阶段
            'steady': (0.1, 0.7),      # 10-70% 稳定阶段
            'fatigue': (0.7, 0.9),     # 70-90% 疲劳阶段
            'final': (0.9, 1.0),       # 90-100% 最后阶段
        }

        logger.debug("步频生成器初始化")

    def generate_cadence_profile(
        self,
        num_points: int,
        speeds: List[float],
    ) -> List[int]:
        """生成步频曲线。

        根据速度曲线、跑步阶段和随机噪声生成每个轨迹点
        的总步频（双脚合计，单位: 步/分钟）。

        Args:
            num_points: 轨迹点数量。
            speeds: 每个轨迹点的速度（米/秒）。

        Returns:
            每个点的总步频列表（步/分钟），数量不足时返回空列表。
        """
        if num_points <= 0:
            return []

        cadence_profile: List[int] = []

        for i in range(num_points):
            speed = speeds[i] if i < len(speeds) else 0.0
            progress = i / (num_points - 1) if num_points > 1 else 0.5

            base_spm = self._get_base_cadence(speed)
            phase_multiplier = self._get_phase_multiplier(progress)
            noise = 1.0 + random.gauss(0, 0.015)

            spm = base_spm * phase_multiplier * noise
            spm = max(self.CAD_MIN_SPM, min(self.CAD_MAX_SPM, spm))
            cadence_profile.append(round(spm))

        return cadence_profile

    def _get_base_cadence(self, speed: float) -> float:
        """根据速度计算基础总步频。

        线性映射: spm = 118 + 20·v，并限制在合理区间。
        锚点: 7'00"/km (2.38m/s) → 166spm (步幅0.86m)，
              8'00"/km (2.08m/s) → 160spm (步幅0.78m)。

        Args:
            speed: 速度（米/秒）。

        Returns:
            基础总步频（步/分钟）。
        """
        spm = self.CAD_INTERCEPT_SPM + self.CAD_SLOPE_SPM_PER_MS * speed
        return max(float(self.CAD_MIN_SPM), min(float(self.CAD_MAX_SPM), spm))

    def _get_phase_multiplier(self, progress: float) -> float:
        """根据跑步进度获取阶段步频乘数。

        与配速波动的阶段同向：热身步频略低，疲劳期缓缓下降，
        最后阶段上抬（冲刺）。

        Args:
            progress: 跑步进度（0.0到1.0）。

        Returns:
            步频乘数。
        """
        # 热身阶段：步频比目标低4%，逐渐回升
        if progress <= self.phases['warmup'][1]:
            return 0.96 + 0.04 * (progress / self.phases['warmup'][1])

        # 稳定阶段：步频在目标附近小幅长波起伏（±2%）
        elif progress <= self.phases['steady'][1]:
            steady_progress = (
                (progress - self.phases['steady'][0])
                / (self.phases['steady'][1] - self.phases['steady'][0])
            )
            return 1.0 + 0.02 * math.sin(steady_progress * math.pi * 3)

        # 疲劳阶段：步频逐渐下降4%
        elif progress <= self.phases['fatigue'][1]:
            fatigue_progress = (
                (progress - self.phases['fatigue'][0])
                / (self.phases['fatigue'][1] - self.phases['fatigue'][0])
            )
            return 1.0 - 0.04 * fatigue_progress

        # 最后阶段：步频上抬（冲刺）
        else:
            final_progress = (
                (progress - self.phases['final'][0])
                / (self.phases['final'][1] - self.phases['final'][0])
            )
            return 0.96 + 0.10 * final_progress


def compute_lap_cadence_metrics(
    trackpoints: List[TrackpointData],
) -> Optional[Tuple[int, int, Optional[int]]]:
    """计算 Lap 级步频统计。

    通过对逐点单脚步频按时间积分得出总步数，保证与
    Trackpoint 数据构造性一致（Keep 交叉校验不会矛盾）。

    Args:
        trackpoints: 轨迹点数据列表。

    Returns:
        (平均单脚步频, 最大单脚步频, 总步数) 元组；
        总步数超过 TCX unsignedShort 上限时该位为 None；
        无法积分（点数不足或时间无法解析）时整体返回 None。
    """
    pts = [tp for tp in trackpoints if tp.run_cadence is not None]
    if len(pts) < 2:
        return None

    try:
        times = [datetime.strptime(tp.time, TIME_FORMAT) for tp in pts]
    except (ValueError, TypeError) as exc:
        logger.warning("解析轨迹点时间失败，跳过 Lap 步频统计: %s", exc)
        return None

    # 按时间积分总步数（每段使用段末点的瞬时步频）
    total_steps = 0.0
    for i in range(1, len(pts)):
        delta_seconds = (times[i] - times[i - 1]).total_seconds()
        if delta_seconds <= 0:
            continue  # 跳过秒级截断导致的重影段
        total_steps += pts[i].run_cadence * 2 / 60.0 * delta_seconds

    total_minutes = (times[-1] - times[0]).total_seconds() / 60.0
    if total_minutes <= 0:
        return None

    steps = round(total_steps)
    avg_run_cadence = round(total_steps / total_minutes / 2)
    max_run_cadence = max(tp.run_cadence for tp in pts)

    if steps > MAX_LAP_STEPS:
        logger.warning(
            "Lap 总步数 %d 超过 TCX unsignedShort 上限 %d，省略 Steps 元素",
            steps, MAX_LAP_STEPS,
        )
        return (avg_run_cadence, max_run_cadence, None)

    return (avg_run_cadence, max_run_cadence, steps)
