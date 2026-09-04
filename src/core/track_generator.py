#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
轨迹生成器
根据基础轨迹生成符合要求的跑步轨迹

作者: 猫娘幽浮喵
功能:
1. 轨迹生成为顺时针
2. 根据距离动态调整轨迹
3. 优化圆弧，使得其更加光滑
4. 轨迹需要浮动，有略微随机性，但不能偏离主要轨道
5. 支持配速波动生成真实的时间分布
"""

import datetime
import logging
import math
import random
from typing import List, Optional

from src.core.models import GeoPoint, TrackAnalysis, TrackpointData
from src.core.track_analyzer import TrackAnalyzer
from src.core.coordinate_corrector import CoordinateCorrector
from src.core.pace_fluctuator import PaceFluctuator
from src.core.cadence_generator import CadenceGenerator

logger = logging.getLogger(__name__)


class TrackGenerator:
    """轨迹生成器类

    通过依赖注入接收 TrackAnalysis、TrackAnalyzer 和可选的
    CoordinateCorrector，生成具有随机波动和平滑处理的跑步轨迹。
    """

    def __init__(
        self,
        track_analysis: TrackAnalysis,
        analyzer: TrackAnalyzer,
        corrector: Optional[CoordinateCorrector] = None,
        max_deviation: float = 2.0,
        smooth_factor: float = 0.3,
        enable_pace_fluctuation: bool = True,
        enable_cadence: bool = True,
    ) -> None:
        """初始化轨迹生成器。

        Args:
            track_analysis: 轨迹分析结果。
            analyzer: 轨迹分析器，用于计算距离。
            corrector: 坐标修正器，可选。传入时对坐标进行修正。
            max_deviation: 最大偏离距离（米）。
            smooth_factor: 光滑因子。
            enable_pace_fluctuation: 是否启用配速波动。
            enable_cadence: 是否启用步频/步数数据自动生成。
        """
        self.base_analysis: TrackAnalysis = track_analysis
        self.analyzer: TrackAnalyzer = analyzer
        self.center: GeoPoint = track_analysis.center
        self.base_distance: float = track_analysis.total_distance_meters
        self.is_clockwise: bool = track_analysis.is_clockwise
        self.max_deviation: float = max_deviation
        self.smooth_factor: float = smooth_factor
        self.enable_pace_fluctuation: bool = enable_pace_fluctuation
        self.enable_cadence: bool = enable_cadence

        # 基础轨迹（可能经过坐标修正）
        if corrector is not None:
            self.base_track: List[GeoPoint] = corrector.correct_coordinates(
                analyzer.base_coordinates
            )
            self.center = corrector.correct_coordinate(self.center)
            logger.info("坐标修正已应用到基础轨迹")
        else:
            self.base_track: List[GeoPoint] = list(analyzer.base_coordinates)

        # 配速波动器（延迟初始化）
        self._pace_fluctuator: Optional[PaceFluctuator] = None

        # 步频生成器（无 base_pace 依赖，无需延迟初始化）
        self._cadence_generator: CadenceGenerator = CadenceGenerator()

        logger.info(
            "轨迹生成器初始化: 基础距离 %.2f 米, 最大偏离 %.2f 米",
            self.base_distance,
            self.max_deviation,
        )

    def generate_smooth_track(
        self,
        target_distance_km: float,
        points_per_km: int = 50,
        enable_randomness: bool = True,
    ) -> List[GeoPoint]:
        """生成光滑的轨迹。

        根据目标距离和每公里点数，通过插值、随机偏移和
        平滑处理生成最终轨迹。

        Args:
            target_distance_km: 目标距离（公里）。
            points_per_km: 每公里的轨迹点数。
            enable_randomness: 是否启用随机浮动。

        Returns:
            轨迹点列表。
        """
        # 计算需要的总圈数
        target_distance_m = target_distance_km * 1000
        total_laps = target_distance_m / self.base_distance

        # 计算每圈需要的点数
        points_per_lap = max(10, int(self.base_distance / 1000 * points_per_km))
        total_points = int(points_per_lap * total_laps)

        # 生成基础轨迹点
        base_points = self._generate_interpolated_track(points_per_lap)

        # 如果需要多圈，重复轨迹
        if total_laps > 1:
            full_laps = int(total_laps)
            remaining_lap_fraction = total_laps - full_laps

            # 完整圈
            track_points: List[GeoPoint] = []
            for _ in range(full_laps):
                track_points.extend(base_points)

            # 最后一部分圈
            if remaining_lap_fraction > 0:
                remaining_points = int(points_per_lap * remaining_lap_fraction)
                track_points.extend(base_points[:remaining_points])
        else:
            # 不足一圈的情况
            track_points = base_points[:total_points]

        # 应用随机浮动
        if enable_randomness:
            track_points = self._apply_randomness(track_points)

        # 光滑处理
        track_points = self._smooth_track(track_points)

        logger.info(
            "生成光滑轨迹: 目标 %.2f km, %d 个点",
            target_distance_km,
            len(track_points),
        )

        return track_points

    def _generate_interpolated_track(self, points_per_lap: int) -> List[GeoPoint]:
        """生成插值轨迹点。

        在基础轨迹的各段之间进行线性插值，按距离比例分配点数。

        Args:
            points_per_lap: 每圈的点数。

        Returns:
            插值后的轨迹点列表。
        """
        # 确保轨迹是顺时针
        if not self.is_clockwise:
            base_track = list(reversed(self.base_track))
        else:
            base_track = self.base_track

        # 计算每段应该分配的点数
        segment_distances: List[float] = []
        for i in range(len(base_track)):
            next_idx = (i + 1) % len(base_track)
            distance = self.analyzer.calculate_distance(
                base_track[i], base_track[next_idx]
            )
            segment_distances.append(distance)

        total_distance = sum(segment_distances)
        points: List[GeoPoint] = []

        # 为每段分配点数
        accumulated_distance = 0.0
        current_segment = 0
        segment_start_distance = 0.0

        for point_idx in range(points_per_lap):
            # 计算当前点应该在的总距离位置
            target_distance = (point_idx / points_per_lap) * total_distance

            # 找到当前点所在的段
            while (
                current_segment < len(base_track) - 1
                and target_distance
                > segment_start_distance + segment_distances[current_segment]
            ):
                segment_start_distance += segment_distances[current_segment]
                current_segment += 1

            if current_segment >= len(base_track) - 1:
                current_segment = 0
                segment_start_distance = 0.0

            # 计算在当前段中的位置比例
            if segment_distances[current_segment] > 0:
                segment_progress = (
                    (target_distance - segment_start_distance)
                    / segment_distances[current_segment]
                )
            else:
                segment_progress = 0.0
            segment_progress = max(0.0, min(1.0, segment_progress))

            # 获取段的起点和终点
            start_point = base_track[current_segment]
            end_point = base_track[(current_segment + 1) % len(base_track)]

            # 线性插值
            lon = start_point.longitude + (
                end_point.longitude - start_point.longitude
            ) * segment_progress
            lat = start_point.latitude + (
                end_point.latitude - start_point.latitude
            ) * segment_progress

            points.append(GeoPoint(longitude=lon, latitude=lat))

        return points

    def _apply_randomness(self, track_points: List[GeoPoint]) -> List[GeoPoint]:
        """应用随机浮动到轨迹点。

        对每个点添加径向和切向的随机偏移，偏移量不超过 max_deviation。

        Args:
            track_points: 原始轨迹点。

        Returns:
            应用随机浮动后的轨迹点。
        """
        random_points: List[GeoPoint] = []

        for point in track_points:
            # 计算到中心点的方向
            dx = point.longitude - self.center.longitude
            dy = point.latitude - self.center.latitude
            distance_to_center = math.sqrt(dx * dx + dy * dy)

            if distance_to_center > 0:
                # 归一化方向向量
                dx /= distance_to_center
                dy /= distance_to_center

                # 计算垂直方向（用于切向随机性）
                perp_dx = -dy
                perp_dy = dx

                # 径向随机偏移（向内或向外）
                radial_offset = random.uniform(-self.max_deviation, self.max_deviation)

                # 切向随机偏移（沿轨迹方向）
                tangential_offset = random.uniform(
                    -self.max_deviation / 2, self.max_deviation / 2
                )

                # 转换为经纬度偏移
                meters_per_degree_lon = 111320 * math.cos(
                    math.radians(point.latitude)
                )
                meters_per_degree_lat = 110540

                lon_offset = (
                    dx * radial_offset + perp_dx * tangential_offset
                ) / meters_per_degree_lon
                lat_offset = (
                    dy * radial_offset + perp_dy * tangential_offset
                ) / meters_per_degree_lat

                random_points.append(
                    GeoPoint(
                        longitude=point.longitude + lon_offset,
                        latitude=point.latitude + lat_offset,
                    )
                )
            else:
                # 如果在中心点，只添加随机偏移
                meters_per_degree_lon = 111320 * math.cos(
                    math.radians(point.latitude)
                )
                meters_per_degree_lat = 110540

                lon_offset = random.uniform(
                    -self.max_deviation, self.max_deviation
                ) / meters_per_degree_lon
                lat_offset = random.uniform(
                    -self.max_deviation, self.max_deviation
                ) / meters_per_degree_lat

                random_points.append(
                    GeoPoint(
                        longitude=point.longitude + lon_offset,
                        latitude=point.latitude + lat_offset,
                    )
                )

        return random_points

    def _smooth_track(self, track_points: List[GeoPoint]) -> List[GeoPoint]:
        """光滑轨迹点。

        对中间点应用加权平均平滑处理，保留起点和终点。

        Args:
            track_points: 原始轨迹点。

        Returns:
            光滑后的轨迹点。
        """
        if len(track_points) < 3:
            return track_points

        smoothed_points: List[GeoPoint] = []

        for i, point in enumerate(track_points):
            if i == 0 or i == len(track_points) - 1:
                # 保留起点和终点
                smoothed_points.append(point)
            else:
                # 对中间点应用加权平均
                prev_point = track_points[i - 1]
                curr_point = track_points[i]
                next_point = track_points[i + 1]

                # 计算加权平均
                weight_center = 1 - 2 * self.smooth_factor
                weight_neighbors = self.smooth_factor

                smoothed_lon = (
                    weight_center * curr_point.longitude
                    + weight_neighbors * prev_point.longitude
                    + weight_neighbors * next_point.longitude
                )

                smoothed_lat = (
                    weight_center * curr_point.latitude
                    + weight_neighbors * prev_point.latitude
                    + weight_neighbors * next_point.latitude
                )

                smoothed_points.append(
                    GeoPoint(longitude=smoothed_lon, latitude=smoothed_lat)
                )

        return smoothed_points

    def generate_tcx_trackpoints(
        self,
        track_points: List[GeoPoint],
        start_time: datetime.datetime,
        duration_seconds: float,
        base_pace_min_per_km: Optional[float] = None,
        enable_pace_fluctuation: bool = True,
        enable_cadence: bool = True,
    ) -> List[TrackpointData]:
        """生成TCX格式的轨迹点。

        根据配速波动或均匀时间分布，为每个轨迹点生成时间戳、
        海拔、累计距离以及步频/速度等信息。

        Args:
            track_points: 轨迹点列表。
            start_time: 开始时间。
            duration_seconds: 总时长（秒）。
            base_pace_min_per_km: 基础配速（分钟/公里），
                                  为 None 时使用均匀时间分布。
            enable_pace_fluctuation: 是否启用配速波动。
            enable_cadence: 是否启用步频/步数数据自动生成。

        Returns:
            TrackpointData 列表。
        """
        if not track_points:
            return []

        if enable_pace_fluctuation and base_pace_min_per_km is not None:
            return self._generate_trackpoints_with_pace(
                track_points, start_time, base_pace_min_per_km, enable_cadence
            )
        else:
            return self._generate_trackpoints_uniform(
                track_points, start_time, duration_seconds, enable_cadence
            )

    def _generate_trackpoints_with_pace(
        self,
        track_points: List[GeoPoint],
        start_time: datetime.datetime,
        base_pace_min_per_km: float,
        enable_cadence: bool = True,
    ) -> List[TrackpointData]:
        """使用配速波动生成轨迹点。

        Args:
            track_points: 轨迹点列表。
            start_time: 开始时间。
            base_pace_min_per_km: 基础配速（分钟/公里）。
            enable_cadence: 是否启用步频/步数数据自动生成。

        Returns:
            TrackpointData 列表。
        """
        # 创建或复用配速波动器
        if (
            self._pace_fluctuator is None
            or self._pace_fluctuator.base_pace != base_pace_min_per_km
        ):
            self._pace_fluctuator = PaceFluctuator(base_pace_min_per_km)

        # 生成配速曲线
        pace_profile = self._pace_fluctuator.generate_pace_profile(
            len(track_points)
        )

        # 根据配速曲线推导每点速度与步频（速度 = 1000 / (60·配速)）
        speeds: List[float] = []
        cadence_spm: List[int] = []
        if enable_cadence:
            speeds = [
                1000.0 / (60.0 * pace) if pace > 0 else 0.0
                for pace in pace_profile
            ]
            cadence_spm = self._cadence_generator.generate_cadence_profile(
                len(track_points), speeds
            )

        # 计算每段距离
        segment_distances: List[float] = []
        for i in range(len(track_points) - 1):
            distance = self.analyzer.calculate_distance(
                track_points[i], track_points[i + 1]
            )
            segment_distances.append(distance / 1000)  # 转换为公里

        # 计算每段的时间
        segment_times = self._pace_fluctuator.generate_segment_times(
            pace_profile[:-1], segment_distances
        )

        # 生成轨迹点
        trackpoints: List[TrackpointData] = []
        current_time = start_time

        for i, point in enumerate(track_points):
            # 使用本地时间格式
            point_time_str = current_time.strftime("%Y-%m-%dT%H:%M:%S")

            # 计算海拔（模拟值，基于到中心的距离）
            distance_to_center = self.analyzer.calculate_distance(
                self.center, point
            )
            altitude = (
                100
                + (distance_to_center - self.base_analysis.approximate_radius_meters)
                * 0.1
            )

            # 计算累计距离
            if i == 0:
                cumulative_distance = 0.0
            else:
                cumulative_distance = sum(
                    self.analyzer.calculate_distance(
                        track_points[j], track_points[j + 1]
                    )
                    for j in range(i)
                )

            trackpoints.append(
                TrackpointData(
                    time=point_time_str,
                    latitude=point.latitude,
                    longitude=point.longitude,
                    altitude=altitude,
                    distance_meters=cumulative_distance,
                    run_cadence=(
                        round(cadence_spm[i] / 2) if enable_cadence else None
                    ),
                    speed=(
                        round(speeds[i], 2) if enable_cadence else None
                    ),
                )
            )

            # 更新当前时间（除了最后一个点）
            if i < len(track_points) - 1:
                current_time += datetime.timedelta(
                    seconds=segment_times[i]
                )

        return trackpoints

    def _generate_trackpoints_uniform(
        self,
        track_points: List[GeoPoint],
        start_time: datetime.datetime,
        duration_seconds: float,
        enable_cadence: bool = True,
    ) -> List[TrackpointData]:
        """使用均匀时间分布生成轨迹点。

        Args:
            track_points: 轨迹点列表。
            start_time: 开始时间。
            duration_seconds: 总时长（秒）。
            enable_cadence: 是否启用步频/步数数据自动生成。

        Returns:
            TrackpointData 列表。
        """
        time_interval = duration_seconds / len(track_points)

        # 按实际轨迹点距离计算累计距离。
        # 注意：base_distance 是单圈长度，多圈轨迹下不能用其均分近似
        # （否则累计距离与速度都会系统性偏低）。
        segment_distances = [
            self.analyzer.calculate_distance(
                track_points[j], track_points[j + 1]
            )
            for j in range(len(track_points) - 1)
        ]
        cumulative_distances: List[float] = [0.0]
        for segment_distance in segment_distances:
            cumulative_distances.append(
                cumulative_distances[-1] + segment_distance
            )

        # 均匀路径无配速曲线，使用恒定速度（实际总距离 / 总时长）
        avg_speed: float = 0.0
        if (
            enable_cadence
            and duration_seconds > 0
            and len(track_points) >= 2
        ):
            avg_speed = cumulative_distances[-1] / duration_seconds

        speeds: List[float] = []
        cadence_spm: List[int] = []
        if enable_cadence:
            speeds = [avg_speed] * len(track_points)
            cadence_spm = self._cadence_generator.generate_cadence_profile(
                len(track_points), speeds
            )

        trackpoints: List[TrackpointData] = []

        for i, point in enumerate(track_points):
            # 计算当前点的时间
            point_time = start_time + datetime.timedelta(
                seconds=i * time_interval
            )
            # 使用本地时间格式
            point_time_str = point_time.strftime("%Y-%m-%dT%H:%M:%S")

            # 计算海拔（模拟值，基于到中心的距离）
            distance_to_center = self.analyzer.calculate_distance(
                self.center, point
            )
            altitude = (
                100
                + (distance_to_center - self.base_analysis.approximate_radius_meters)
                * 0.1
            )

            # 均匀分布的累计距离
            cumulative_distance = cumulative_distances[i]

            trackpoints.append(
                TrackpointData(
                    time=point_time_str,
                    latitude=point.latitude,
                    longitude=point.longitude,
                    altitude=altitude,
                    distance_meters=cumulative_distance,
                    run_cadence=(
                        round(cadence_spm[i] / 2) if enable_cadence else None
                    ),
                    speed=(
                        round(speeds[i], 2) if enable_cadence else None
                    ),
                )
            )

        return trackpoints
