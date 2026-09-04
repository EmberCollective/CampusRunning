#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""模板管理器

作者: 猫娘幽浮喵
功能: 加载和管理跑步模板配置
"""

import json
import logging
import os
import uuid
from typing import Optional

from src.config_manager import ConfigManager
from src.core.models import GenerationConfig

logger = logging.getLogger(__name__)


class TemplateManager:
    """模板管理器

    负责从 config/templates/ 目录加载模板，并提供模板应用功能。
    """

    def __init__(self, config_manager: ConfigManager) -> None:
        """初始化模板管理器

        Args:
            config_manager: 配置管理器实例
        """
        self._config_manager = config_manager
        self._templates_dir = os.path.join(
            config_manager._config_dir, "templates"
        )

        logger.info("模板管理器初始化: %s", self._templates_dir)

    def list_available(self) -> list[dict]:
        """列出所有可用模板

        Returns:
            模板信息列表，每项包含 id, name, description
        """
        templates = []

        if not os.path.isdir(self._templates_dir):
            logger.warning("模板目录不存在: %s", self._templates_dir)
            return templates

        for filename in os.listdir(self._templates_dir):
            if not filename.endswith(".json"):
                continue

            filepath = os.path.join(self._templates_dir, filename)
            try:
                with open(filepath, "r", encoding="utf-8") as fh:
                    data = json.load(fh)

                templates.append({
                    "id": data["id"],
                    "name": data["name"],
                    "description": data["description"],
                })
            except Exception as e:
                logger.error("加载模板 %s 失败: %s", filename, e)

        logger.info("发现 %d 个模板", len(templates))
        return templates

    def load_template(self, template_id: str) -> Optional[dict]:
        """加载模板配置

        Args:
            template_id: 模板ID

        Returns:
            模板数据字典，不存在时返回 None
        """
        filepath = os.path.join(self._templates_dir, f"{template_id}.json")
        if not os.path.isfile(filepath):
            logger.warning("模板不存在: %s", template_id)
            return None

        with open(filepath, "r", encoding="utf-8") as fh:
            data = json.load(fh)

        logger.info("加载模板: %s (%s)", data["name"], data["id"])
        return data

    def save_template(
        self,
        name: str,
        description: str,
        generation_config: dict,
    ) -> dict:
        """保存模板到文件

        Args:
            name: 模板名称
            description: 模板描述
            generation_config: 生成配置字典

        Returns:
            创建的模板信息，包含 id, name, description
        """
        # 生成唯一ID
        template_id = f"custom_{uuid.uuid4().hex[:8]}"

        template_data = {
            "id": template_id,
            "name": name,
            "description": description,
            "generation_config": generation_config,
        }

        # 确保目录存在
        os.makedirs(self._templates_dir, exist_ok=True)

        filepath = os.path.join(self._templates_dir, f"{template_id}.json")
        with open(filepath, "w", encoding="utf-8") as fh:
            json.dump(template_data, fh, ensure_ascii=False, indent=2)

        logger.info("模板已保存: %s (%s)", name, template_id)

        return {
            "id": template_id,
            "name": name,
            "description": description,
        }

    @staticmethod
    def _migrate_time_fields(data: dict) -> None:
        """将旧版 start_hour_min/max (int) 迁移为 start_time_min/max (str)

        Args:
            data: 待迁移的配置字典（原地修改）
        """
        if "start_hour_min" in data and "start_time_min" not in data:
            hour = data.pop("start_hour_min")
            data["start_time_min"] = f"{int(hour):02d}:00"
        if "start_hour_max" in data and "start_time_max" not in data:
            hour = data.pop("start_hour_max")
            data["start_time_max"] = f"{int(hour):02d}:00"

    def apply_template(
        self,
        template_id: Optional[str] = None,
        overrides: Optional[dict] = None,
    ) -> GenerationConfig:
        """应用模板并合并覆盖项，生成最终配置

        优先级：overrides > template > defaults

        Args:
            template_id: 模板ID（可选）
            overrides: 覆盖项字典（可选）

        Returns:
            最终的生成配置
        """
        # 从默认配置开始
        config_dict = self._config_manager.build_default_config()
        base_params = {
            "track_id": config_dict.track_id,
            "min_pace": config_dict.min_pace,
            "max_pace": config_dict.max_pace,
            "start_time_min": config_dict.start_time_min,
            "start_time_max": config_dict.start_time_max,
            "output_dir": config_dict.output_dir,
            "include_track": config_dict.include_track,
            "apply_correction": config_dict.apply_correction,
            "enable_pace_fluctuation": config_dict.enable_pace_fluctuation,
            "enable_cadence": config_dict.enable_cadence,
            "create_zip": config_dict.create_zip,
            "points_per_km": config_dict.points_per_km,
            "max_deviation_meters": config_dict.max_deviation_meters,
            "smooth_factor": config_dict.smooth_factor,
            "weekend_factor": config_dict.weekend_factor,
            "rest_days_per_week": config_dict.rest_days_per_week,
            "min_daily_km": config_dict.min_daily_km,
            "max_daily_km": config_dict.max_daily_km,
            "calories_per_km": config_dict.calories_per_km,
            "start_date": config_dict.start_date,
            "end_date": config_dict.end_date,
        }

        # 应用模板
        if template_id:
            template_data = self.load_template(template_id)
            if template_data and "generation_config" in template_data:
                gen_config = template_data["generation_config"]
                # 向后兼容：旧模板使用 start_hour_min/max (int)
                self._migrate_time_fields(gen_config)
                for key, value in gen_config.items():
                    if key in base_params:
                        base_params[key] = value
                logger.info("模板 %s 已应用", template_id)

        # 应用覆盖项
        if overrides:
            # 向后兼容：旧覆盖项使用 start_hour_min/max (int)
            self._migrate_time_fields(overrides)
            for key, value in overrides.items():
                if key in base_params:
                    base_params[key] = value
            logger.info("覆盖项已应用")

        return GenerationConfig(**base_params)
