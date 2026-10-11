#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""config/templates/ 内置预设模板结构测试。

两套消费通道、两种格式并存于同一模板文件：

- Web 前端 applyTemplateToForms 依据 daily_config/total_config/single_config/
  dates_config 哪个节非空来切换生成模式（issue #44 的根因是旧模板只有
  generation_config，选中后不跳模式）
- CLI / API 的 TemplateManager.apply_template 只合并 generation_config 节
  （src/template_manager.py 白名单），缺失则 --template 静默失效

本测试保证内置模板两条通道都能命中，且字段名无拼写错误。
"""

import json
from pathlib import Path

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "config" / "templates"

# 各模式节支持的字段（web/static/js/app.js applyTemplateToForms / doExportTemplate）
MODE_SECTION_FIELDS = {
    "daily_config": {
        "min_pace", "max_pace", "start_time_min", "start_time_max",
        "start_hour_min", "start_hour_max",
        "start_date", "end_date", "min_km", "max_km",
        "include_track", "apply_correction", "enable_pace_fluctuation",
        "output_format",
    },
    "total_config": {
        "min_pace", "max_pace", "start_time_min", "start_time_max",
        "start_hour_min", "start_hour_max",
        "start_date", "end_date", "total_km", "weekend_factor",
        "min_daily_km", "max_daily_km", "rest_days_per_week",
        "include_track", "apply_correction", "enable_pace_fluctuation",
        "output_format",
    },
    "single_config": {
        "pace", "include_track", "apply_correction",
        "enable_pace_fluctuation", "output_format",
    },
    "dates_config": {
        "dates", "min_km", "max_km", "min_pace", "max_pace",
        "start_time_min", "start_time_max", "output_format",
    },
}

# CLI / API 通道（TemplateManager.apply_template base_params）可消费的字段
CLI_CONFIG_FIELDS = {
    "track_id", "min_pace", "max_pace", "start_time_min", "start_time_max",
    "output_dir", "include_track", "apply_correction",
    "enable_pace_fluctuation", "enable_cadence", "output_format",
    "create_zip", "points_per_km", "max_deviation_meters", "smooth_factor",
    "weekend_factor", "rest_days_per_week", "min_daily_km", "max_daily_km",
    "calories_per_km", "start_date", "end_date",
}

MODE_SECTIONS = set(MODE_SECTION_FIELDS)


def _load_preset_templates():
    """读取内置预设模板，返回 {文件名: 解析后的 dict}。

    排除 POST /api/template 生成的 custom_* 用户模板（旧格式，
    与内置预设的结构约束无关）。
    """
    templates = {}
    for path in sorted(TEMPLATES_DIR.glob("*.json")):
        if path.stem.startswith("custom_"):
            continue
        with open(path, encoding="utf-8") as f:
            templates[path.name] = json.load(f)
    assert templates, "config/templates 目录下没有任何内置模板"
    return templates


def test_preset_templates_have_basic_fields():
    # list_available 硬性读取 id/name/description，缺失的文件会被静默跳过
    for name, template in _load_preset_templates().items():
        assert template.get("id"), f"{name} 缺少 id"
        assert template.get("name"), f"{name} 缺少 name"
        assert template.get("description") is not None, f"{name} 缺少 description"


def test_preset_templates_use_mode_sections():
    """每个内置模板至少有一个非空模式节，选中后前端才能切换生成模式。"""
    for name, template in _load_preset_templates().items():
        non_empty = [
            section
            for section in MODE_SECTIONS
            if template.get(section)
        ]
        assert non_empty, (
            f"{name} 没有任何非空的模式节（daily/total/single/dates_config），"
            "选中后无法切换生成模式"
        )


def test_preset_templates_fields_are_supported():
    """模式节内的字段名必须在白名单内，防止拼写错误静默失效。"""
    for name, template in _load_preset_templates().items():
        for section, fields in MODE_SECTION_FIELDS.items():
            unknown = set(template.get(section) or {}) - fields
            assert not unknown, f"{name} 的 {section} 含不支持的字段: {unknown}"


def test_preset_templates_keep_cli_generation_config():
    """CLI --template / API template_id 只读 generation_config，缺失即静默失效。"""
    for name, template in _load_preset_templates().items():
        gen_config = template.get("generation_config")
        assert gen_config, f"{name} 缺少 generation_config，CLI --template 将无效"
        unknown = set(gen_config) - CLI_CONFIG_FIELDS
        assert not unknown, f"{name} 的 generation_config 含无效字段: {unknown}"
