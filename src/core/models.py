#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""数据模型定义

定义校园跑步数据生成器使用的所有数据模型。
大部分模型使用 frozen dataclass 以保证不可变性。

Author: 猫娘幽浮喵
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass, field
from typing import Optional


@dataclass(frozen=True)
class GeoPoint:
    """地理坐标点

    Attributes:
        longitude: 经度
        latitude: 纬度
    """
    longitude: float
    latitude: float


@dataclass(frozen=True)
class CoordinateCorrection:
    """坐标修正配置

    用于将轨迹从当前中心点平移至目标中心点。

    Attributes:
        current_center: 当前轨迹中心坐标
        target_center: 目标中心坐标
    """
    current_center: GeoPoint
    target_center: GeoPoint


@dataclass(frozen=True)
class TrackDefinition:
    """轨迹定义

    定义一条完整的跑步轨迹，包括基础坐标点和可选的坐标修正参数。

    Attributes:
        id: 轨迹唯一标识符
        name: 轨迹名称
        description: 轨迹描述
        base_coordinates: 基础坐标点列表
        coordinate_correction: 可选的坐标修正配置
    """
    id: str
    name: str
    description: str
    base_coordinates: list[GeoPoint]
    coordinate_correction: Optional[CoordinateCorrection] = None


@dataclass(frozen=True)
class TrackAnalysis:
    """轨迹分析结果

    存储对轨迹进行分析后得到的各项指标。

    Attributes:
        total_distance_meters: 轨迹总距离（米）
        segment_distances: 各段距离列表（米）
        num_points: 坐标点数量
        center: 轨迹中心点
        approximate_radius_meters: 轨迹近似半径（米）
        is_clockwise: 轨迹方向是否为顺时针
    """
    total_distance_meters: float
    segment_distances: list[float]
    num_points: int
    center: GeoPoint
    approximate_radius_meters: float
    is_clockwise: bool


@dataclass(frozen=True)
class TrackpointData:
    """轨迹点数据

    单个轨迹点的完整数据，用于 TCX 文件导出。

    Attributes:
        time: 时间戳字符串（ISO 8601 格式）
        latitude: 纬度
        longitude: 经度
        altitude: 海拔高度（米）
        distance_meters: 累计距离（米）
        run_cadence: 单脚步频（总步频/2，Garmin Cadence/RunCadence 语义，
                     典型值 75-95）
        speed: 瞬时速度（米/秒）
    """
    time: str
    latitude: float
    longitude: float
    altitude: float
    distance_meters: float
    run_cadence: Optional[int] = None
    speed: Optional[float] = None


@dataclass(frozen=True)
class ExportData:
    """导出数据

    一次跑步记录的完整导出数据。

    Attributes:
        date: 跑步日期
        start_time: 开始时间
        distance_km: 距离（公里）
        duration_seconds: 持续时间（秒）
        calories: 消耗卡路里
        trackpoints: 轨迹点列表
    """
    date: datetime.date
    start_time: datetime.datetime
    distance_km: float
    duration_seconds: float
    calories: int
    trackpoints: list[TrackpointData]


@dataclass(frozen=True)
class GenerationResult:
    """单个生成结果

    记录单次跑步数据生成的结果信息。

    Attributes:
        filepath: 生成的文件路径
        date: 跑步日期
        distance_km: 距离（公里）
        pace_min_per_km: 配速（分钟/公里）
        duration_seconds: 持续时间（秒）
        calories: 消耗卡路里
    """
    filepath: str
    date: datetime.date
    distance_km: float
    pace_min_per_km: float
    duration_seconds: float
    calories: int


@dataclass(frozen=True)
class DailyPlan:
    """每日跑步计划

    Attributes:
        date: 日期
        distance_km: 计划距离（公里）
    """
    date: datetime.date
    distance_km: float


@dataclass(frozen=True)
class RunningPlan:
    """完整跑步计划

    包含一段时间内的完整跑步安排。

    Attributes:
        start_date: 计划开始日期
        end_date: 计划结束日期
        total_days: 总天数
        running_days: 跑步天数
        target_total_km: 目标总里程（公里）
        actual_total_km: 实际总里程（公里）
        weekday_avg_km: 工作日平均里程（公里）
        weekend_avg_km: 周末平均里程（公里）
        daily_plans: 每日计划列表
    """
    start_date: datetime.date
    end_date: datetime.date
    total_days: int
    running_days: int
    target_total_km: float
    actual_total_km: float
    weekday_avg_km: float
    weekend_avg_km: float
    daily_plans: list[DailyPlan]


@dataclass
class GenerationConfig:
    """生成配置（可变，用于运行时覆盖）

    包含跑步数据生成过程中所有可配置的参数。

    Attributes:
        track_id: 轨迹 ID
        min_pace: 最小配速（分钟/公里）
        max_pace: 最大配速（分钟/公里）
        start_time_min: 最早开始时间（"HH:MM" 格式）
        start_time_max: 最晚开始时间（"HH:MM" 格式）
        output_dir: 输出目录
        include_track: 是否包含轨迹数据
        apply_correction: 是否应用坐标修正
        enable_pace_fluctuation: 是否启用配速波动
        enable_cadence: 是否启用步频/步数数据自动生成
        output_format: 输出文件格式（"fit" 或 "tcx"；Keep 的 TCX
                       导入通道不解析步频，FIT 为默认格式）
        create_zip: 是否创建 ZIP 压缩包
        points_per_km: 每公里生成的轨迹点数
        max_deviation_meters: 最大偏移距离（米）
        smooth_factor: 平滑因子
        weekend_factor: 周末里程系数
        rest_days_per_week: 每周休息天数
        min_daily_km: 每日最小里程（公里）
        max_daily_km: 每日最大里程（公里）
        calories_per_km: 每公里消耗卡路里
        start_date: 可选的默认开始日期
        end_date: 可选的默认结束日期
    """
    track_id: str = "campus_default"
    min_pace: float = 7.0
    max_pace: float = 8.0
    start_time_min: str = "06:00"
    start_time_max: str = "08:00"
    output_dir: str = "output"
    include_track: bool = True
    apply_correction: bool = True
    enable_pace_fluctuation: bool = True
    enable_cadence: bool = True
    output_format: str = "fit"
    create_zip: bool = False
    points_per_km: int = 50
    max_deviation_meters: float = 2.0
    smooth_factor: float = 0.3
    weekend_factor: float = 1.5
    rest_days_per_week: int = 1
    min_daily_km: float = 2.0
    max_daily_km: float = 8.0
    calories_per_km: float = 60.0
    start_date: Optional[datetime.date] = None
    end_date: Optional[datetime.date] = None

    _VALID_OUTPUT_FORMATS = ("tcx", "fit")

    def __post_init__(self) -> None:
        """构造时校验关键字段取值，非法值尽早暴露

        Raises:
            ValueError: output_format 不是受支持的格式
        """
        if self.output_format not in self._VALID_OUTPUT_FORMATS:
            raise ValueError(
                f"不支持的输出格式: {self.output_format}（可选 tcx/fit）"
            )
