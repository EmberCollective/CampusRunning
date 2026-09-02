#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""配置管理器

作者: 猫娘幽浮喵
功能: 加载和管理轨迹配置、默认设置等
"""

import json
import logging
import math
import os
import re
from typing import Optional

from src.core.models import (
    GeoPoint,
    CoordinateCorrection,
    TrackDefinition,
    GenerationConfig,
)

logger = logging.getLogger(__name__)

# 轨迹ID合法字符：小写字母、数字、下划线、连字符
_TRACK_ID_PATTERN = re.compile(r"^[a-z0-9_-]+$")


class ConfigManager:
    """配置管理器

    负责从 config/ 目录加载轨迹定义、默认设置等配置数据。
    """

    def __init__(self, config_dir: str) -> None:
        """初始化配置管理器

        Args:
            config_dir: 配置目录路径（通常为项目根目录下的 config/）
        """
        self._config_dir = config_dir
        self._tracks_dir = os.path.join(config_dir, "tracks")
        self._defaults_path = os.path.join(config_dir, "default_settings.json")

        logger.info("配置管理器初始化: %s", config_dir)

    def list_tracks(self) -> list[str]:
        """列出所有可用的轨迹ID

        Returns:
            轨迹ID列表
        """
        tracks = []
        if not os.path.isdir(self._tracks_dir):
            logger.warning("轨迹目录不存在: %s", self._tracks_dir)
            return tracks

        for filename in os.listdir(self._tracks_dir):
            if filename.endswith(".json"):
                tracks.append(filename[:-5])

        logger.info("发现 %d 条轨迹", len(tracks))
        return tracks

    def load_track(self, track_id: str) -> TrackDefinition:
        """加载轨迹定义

        Args:
            track_id: 轨迹ID

        Returns:
            轨迹定义对象

        Raises:
            FileNotFoundError: 轨迹文件不存在
        """
        # track_id 校验与保存侧对齐：拒绝路径分隔符等非法字符（防目录穿越读取）
        if not isinstance(track_id, str) or not _TRACK_ID_PATTERN.fullmatch(track_id):
            raise FileNotFoundError(f"轨迹不存在: {track_id}")

        filepath = os.path.join(self._tracks_dir, f"{track_id}.json")
        if not os.path.isfile(filepath):
            raise FileNotFoundError(f"轨迹文件不存在: {filepath}")

        with open(filepath, "r", encoding="utf-8") as fh:
            data = json.load(fh)

        # 解析基础坐标
        base_coords = [
            GeoPoint(longitude=p["longitude"], latitude=p["latitude"])
            for p in data["base_coordinates"]
        ]

        # 解析可选的坐标修正
        correction = None
        if "coordinate_correction" in data and data["coordinate_correction"]:
            cc = data["coordinate_correction"]
            correction = CoordinateCorrection(
                current_center=GeoPoint(
                    longitude=cc["current_center"]["longitude"],
                    latitude=cc["current_center"]["latitude"],
                ),
                target_center=GeoPoint(
                    longitude=cc["target_center"]["longitude"],
                    latitude=cc["target_center"]["latitude"],
                ),
            )

        track = TrackDefinition(
            id=data["id"],
            name=data["name"],
            description=data["description"],
            base_coordinates=base_coords,
            coordinate_correction=correction,
        )

        logger.info("加载轨迹: %s (%s)", track.name, track.id)
        return track

    @staticmethod
    def _validate_point(point: GeoPoint, label: str) -> None:
        """校验单个坐标点的合法性

        Args:
            point: 待校验的坐标点
            label: 出错信息中的位置描述（如 "第 1 个坐标点"）

        Raises:
            ValueError: 坐标值非法（非数字、bool、NaN/Inf、超出经纬度范围）
        """
        for field_name, value in (
            ("longitude", point.longitude),
            ("latitude", point.latitude),
        ):
            # 显式排除 bool（bool 是 int 的子类，需先判）
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValueError(f"{label} 的 {field_name} 必须为数字")
            if not math.isfinite(value):
                raise ValueError(f"{label} 的 {field_name} 必须为有限数值（不能是 NaN 或无穷）")

        if not -180 <= point.longitude <= 180:
            raise ValueError(f"{label} 的经度超出范围 [-180, 180]")
        if not -90 <= point.latitude <= 90:
            raise ValueError(f"{label} 的纬度超出范围 [-90, 90]")

    def save_track(
        self, track: TrackDefinition, overwrite: bool = False
    ) -> tuple[str, bool]:
        """保存轨迹定义到 config/tracks/<id>.json

        Args:
            track: 轨迹定义对象（点原样保留，不去重、不平滑）
            overwrite: 是否允许覆盖已存在的轨迹文件

        Returns:
            (文件路径, 是否新建) 元组；新建为 True，覆盖为 False

        Raises:
            ValueError: 校验失败（消息可直接展示给用户，中文）
            FileExistsError: 文件已存在且未允许覆盖
        """
        # 校验轨迹ID：合法字符 + 长度限制
        track_id = track.id
        if (
            not isinstance(track_id, str)
            or not 1 <= len(track_id) <= 64
            or not _TRACK_ID_PATTERN.fullmatch(track_id)
        ):
            raise ValueError(
                "轨迹ID仅允许小写字母、数字、下划线和连字符，长度 1~64"
            )

        # 校验名称与描述
        if not isinstance(track.name, str) or not track.name.strip():
            raise ValueError("轨迹名称不能为空")
        if not isinstance(track.description, str):
            raise ValueError("轨迹描述必须为字符串")

        # 校验基础坐标：至少 3 个点才能构成轨迹
        if (
            not isinstance(track.base_coordinates, list)
            or len(track.base_coordinates) < 3
        ):
            raise ValueError("轨迹至少需要 3 个基础坐标点")
        for index, point in enumerate(track.base_coordinates):
            self._validate_point(point, f"第 {index + 1} 个坐标点")

        # 校验可选的坐标修正
        if track.coordinate_correction is not None:
            self._validate_point(
                track.coordinate_correction.current_center,
                "coordinate_correction.current_center",
            )
            self._validate_point(
                track.coordinate_correction.target_center,
                "coordinate_correction.target_center",
            )

        filepath = os.path.join(self._tracks_dir, f"{track.id}.json")
        # 第二道防线：join 后的绝对路径必须仍在 tracks 目录内
        if not os.path.abspath(filepath).startswith(
            os.path.abspath(self._tracks_dir) + os.sep
        ):
            raise ValueError("非法的轨迹ID")
        if os.path.exists(filepath) and not overwrite:
            raise FileExistsError(f"轨迹文件已存在: {track.id}")

        # 组装写入数据（coordinate_correction 为 None 时显式写 null）
        correction_data = None
        if track.coordinate_correction is not None:
            correction_data = {
                "current_center": {
                    "longitude": track.coordinate_correction.current_center.longitude,
                    "latitude": track.coordinate_correction.current_center.latitude,
                },
                "target_center": {
                    "longitude": track.coordinate_correction.target_center.longitude,
                    "latitude": track.coordinate_correction.target_center.latitude,
                },
            }

        track_data = {
            "id": track.id,
            "name": track.name,
            "description": track.description,
            "base_coordinates": [
                {"longitude": p.longitude, "latitude": p.latitude}
                for p in track.base_coordinates
            ],
            "coordinate_correction": correction_data,
        }

        # created 需在写入前判断文件是否已存在
        created = not os.path.exists(filepath)

        # 确保目录存在后写入（先写临时文件再原子替换，避免覆盖时写坏原轨迹文件）
        os.makedirs(self._tracks_dir, exist_ok=True)
        tmp_path = filepath + ".tmp"
        with open(tmp_path, "w", encoding="utf-8") as fh:
            json.dump(track_data, fh, ensure_ascii=False, indent=2)
        os.replace(tmp_path, filepath)

        logger.info("轨迹已保存: %s (%s)", track.name, track.id)

        return filepath, created

    def load_defaults(self) -> dict:
        """加载默认设置

        Returns:
            默认设置字典
        """
        if not os.path.isfile(self._defaults_path):
            logger.warning("默认设置文件不存在，使用内置默认值")
            return {}

        with open(self._defaults_path, "r", encoding="utf-8") as fh:
            defaults = json.load(fh)

        logger.info("默认设置已加载")
        return defaults

    def build_default_config(self, overrides: Optional[dict] = None) -> GenerationConfig:
        """根据默认设置构建生成配置

        Args:
            overrides: 覆盖项字典

        Returns:
            生成配置对象
        """
        defaults = self.load_defaults()
        params = {
            "track_id": defaults.get("default_track_id", "campus_default"),
            "min_pace": defaults.get("default_pace_range", [7.0, 8.0])[0],
            "max_pace": defaults.get("default_pace_range", [7.0, 8.0])[1],
            "start_time_min": defaults.get("default_start_time_range", ["06:00", "08:00"])[0],
            "start_time_max": defaults.get("default_start_time_range", ["06:00", "08:00"])[1],
            "weekend_factor": defaults.get("weekend_factor", 1.5),
            "rest_days_per_week": defaults.get("rest_days_per_week", 1),
            "points_per_km": defaults.get("points_per_km", 50),
            "max_deviation_meters": defaults.get("max_deviation_meters", 2.0),
            "smooth_factor": defaults.get("smooth_factor", 0.3),
            "calories_per_km": defaults.get("calories_per_km", 60.0),
            "min_daily_km": defaults.get("min_daily_km", 2.0),
            "max_daily_km": defaults.get("max_daily_km", 8.0),
        }

        if overrides:
            params.update(overrides)

        return GenerationConfig(**params)
