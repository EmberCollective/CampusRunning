#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成引擎

作者: 猫娘幽浮喵
功能: 协调规划器、轨迹生成器和导出器，完成完整的数据生成流程
"""

import datetime
import logging
import os
from typing import Optional

from src.config_manager import ConfigManager
from src.core.models import (
    DailyPlan,
    GenerationConfig,
    GenerationResult,
    ExportData,
)
from src.core.track_analyzer import TrackAnalyzer
from src.core.track_generator import TrackGenerator
from src.core.coordinate_corrector import CoordinateCorrector
from src.core.helpers import (
    generate_pace,
    calculate_duration,
    calculate_calories,
    generate_start_time,
)
from src.planners.daily_planner import DailyPlanner
from src.planners.total_km_planner import TotalKmPlanner
from src.planners.single_planner import SinglePlanner
from src.exporters.tcx_exporter import TcxExporter

logger = logging.getLogger(__name__)


class GenerationEngine:
    """生成引擎

    协调各模块完成跑步数据的完整生成流程：
    规划 -> 轨迹生成 -> 导出
    """

    def __init__(self, config_manager: ConfigManager) -> None:
        """初始化生成引擎

        Args:
            config_manager: 配置管理器实例
        """
        self._config_manager = config_manager
        self._exporter = TcxExporter()

        logger.info("生成引擎初始化完成")

    def generate_daily(
        self,
        start_date: datetime.date,
        end_date: datetime.date,
        min_km: float,
        max_km: float,
        config: GenerationConfig,
    ) -> list[GenerationResult]:
        """每日范围生成

        Args:
            start_date: 开始日期
            end_date: 结束日期
            min_km: 每日最低公里数
            max_km: 每日最高公里数
            config: 生成配置

        Returns:
            生成结果列表
        """
        logger.info(
            "每日范围生成: %s ~ %s, %.1f-%.1f km",
            start_date, end_date, min_km, max_km,
        )

        planner = DailyPlanner(config)
        plans = planner.plan(start_date, end_date, min_km, max_km)

        return self._generate_from_plans(plans, config)

    def generate_total(
        self,
        start_date: datetime.date,
        end_date: datetime.date,
        total_km: float,
        config: GenerationConfig,
    ) -> list[GenerationResult]:
        """总公里数生成

        Args:
            start_date: 开始日期
            end_date: 结束日期
            total_km: 总公里数
            config: 生成配置

        Returns:
            生成结果列表
        """
        logger.info(
            "总公里数生成: %s ~ %s, 目标 %.1f km",
            start_date, end_date, total_km,
        )

        planner = TotalKmPlanner(config)
        running_plan = planner.plan(start_date, end_date, total_km)

        logger.info(
            "规划完成: 目标 %.2f km, 实际 %.2f km, 跑步天数 %d",
            running_plan.target_total_km,
            running_plan.actual_total_km,
            running_plan.running_days,
        )

        return self._generate_from_plans(running_plan.daily_plans, config)

    def generate_single(
        self,
        date: datetime.date,
        distance: float,
        config: GenerationConfig,
    ) -> GenerationResult:
        """单文件生成

        Args:
            date: 日期
            distance: 距离（公里）
            config: 生成配置

        Returns:
            生成结果
        """
        logger.info("单文件生成: %s, %.2f km", date, distance)

        planner = SinglePlanner()
        plan = planner.plan(date, distance)

        results = self._generate_from_plans([plan], config)
        return results[0]

    def generate_dates(
        self,
        dates: list[datetime.date],
        distance: float,
        config: GenerationConfig,
    ) -> list[GenerationResult]:
        """指定日期批量生成

        Args:
            dates: 日期列表
            distance: 每日距离（公里）
            config: 生成配置

        Returns:
            生成结果列表
        """
        logger.info(
            "指定日期批量生成: %d 天, %.2f km/天",
            len(dates), distance,
        )

        planner = SinglePlanner()
        plans = [planner.plan(d, distance) for d in dates]

        return self._generate_from_plans(plans, config)

    def _generate_from_plans(
        self,
        plans: list[DailyPlan],
        config: GenerationConfig,
    ) -> list[GenerationResult]:
        """根据计划列表生成所有文件

        Args:
            plans: 每日计划列表
            config: 生成配置

        Returns:
            生成结果列表
        """
        results: list[GenerationResult] = []

        # 加载轨迹
        track_def = self._config_manager.load_track(config.track_id)
        analyzer = TrackAnalyzer(track_def.base_coordinates)
        analysis = analyzer.analyze_track()

        # 创建坐标修正器
        corrector: Optional[CoordinateCorrector] = None
        if config.apply_correction and track_def.coordinate_correction:
            corrector = CoordinateCorrector(track_def.coordinate_correction)

        # 创建轨迹生成器
        track_gen = TrackGenerator(
            track_analysis=analysis,
            analyzer=analyzer,
            corrector=corrector,
            max_deviation=config.max_deviation_meters,
            smooth_factor=config.smooth_factor,
            enable_pace_fluctuation=config.enable_pace_fluctuation,
        )

        for plan in plans:
            try:
                result = self._generate_single_file(
                    plan, config, track_gen, analyzer,
                )
                results.append(result)
            except Exception as e:
                logger.error(
                    "生成 %s 的数据失败: %s", plan.date, e, exc_info=True,
                )

        logger.info("生成完成: %d/%d 个文件", len(results), len(plans))
        return results

    def _generate_single_file(
        self,
        plan: DailyPlan,
        config: GenerationConfig,
        track_gen: TrackGenerator,
        analyzer: TrackAnalyzer,
    ) -> GenerationResult:
        """生成单个TCX文件

        Args:
            plan: 每日计划
            config: 生成配置
            track_gen: 轨迹生成器
            analyzer: 轨迹分析器

        Returns:
            生成结果
        """
        distance_km = plan.distance_km
        pace = generate_pace(config.min_pace, config.max_pace)
        duration = calculate_duration(distance_km, pace)
        start_time = generate_start_time(
            plan.date,
            (config.start_time_min, config.start_time_max),
        )
        calories = calculate_calories(
            distance_km, duration, config.calories_per_km,
        )

        # 生成轨迹点
        trackpoints = []
        if config.include_track:
            geo_points = track_gen.generate_smooth_track(
                distance_km, config.points_per_km,
            )
            trackpoints = track_gen.generate_tcx_trackpoints(
                geo_points, start_time, duration, pace,
                config.enable_pace_fluctuation,
            )

        # 构建导出数据
        export_data = ExportData(
            date=plan.date,
            start_time=start_time,
            distance_km=distance_km,
            duration_seconds=duration,
            calories=calories,
            trackpoints=trackpoints,
        )

        # 导出文件
        output_dir = os.path.abspath(config.output_dir)
        os.makedirs(output_dir, exist_ok=True)
        filename = f"{plan.date.strftime('%Y-%m-%d')}_{distance_km}km.tcx"
        filepath = os.path.join(output_dir, filename)

        self._exporter.export(export_data, filepath)

        logger.info(
            "文件已生成: %s (%.2f km, 配速 %.2f min/km)",
            filename, distance_km, pace,
        )

        return GenerationResult(
            filepath=filepath,
            date=plan.date,
            distance_km=distance_km,
            pace_min_per_km=pace,
            duration_seconds=duration,
            calories=calories,
        )
