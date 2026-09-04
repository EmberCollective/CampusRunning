#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Web API路由

作者: 猫娘幽浮喵
"""

import datetime
import logging
import os
import uuid
import zipfile
from typing import Optional

from flask import Flask, render_template, request, jsonify, send_file, abort

from src.config_manager import ConfigManager
from src.template_manager import TemplateManager
from src.core.models import (
    GenerationConfig,
    GenerationResult,
    GeoPoint,
    TrackDefinition,
    CoordinateCorrection,
)
from src.core.track_analyzer import TrackAnalyzer

logger = logging.getLogger(__name__)

# 全局状态
_config_manager: Optional[ConfigManager] = None
_template_manager: Optional[TemplateManager] = None
_generation_jobs: dict = {}  # job_id -> results
_tracks_cache: Optional[list[dict]] = None  # 轨迹分析缓存


def _ensure_tracks_cache() -> list[dict]:
    """确保轨迹缓存已初始化（延迟初始化模式）

    Returns:
        缓存的轨迹列表
    """
    global _tracks_cache
    if _tracks_cache is None:
        _init_tracks_cache()
    return _tracks_cache


def _init_tracks_cache() -> None:
    """初始化轨迹缓存 - 预计算所有轨迹的分析结果"""
    global _tracks_cache
    if _config_manager is None:
        logger.warning("配置管理器未初始化，跳过缓存初始化")
        return
    _tracks_cache = []
    for track_id in _config_manager.list_tracks():
        try:
            track = _config_manager.load_track(track_id)
            analyzer = TrackAnalyzer(track.base_coordinates)
            analysis = analyzer.analyze_track()
            _tracks_cache.append({
                "id": track.id,
                "name": track.name,
                "description": track.description,
                "distance_meters": round(analysis.total_distance_meters, 1),
                "lap_distance_km": round(analysis.total_distance_meters / 1000, 3),
                "num_points": analysis.num_points,
                "is_clockwise": analysis.is_clockwise,
            })
        except Exception as e:
            logger.error("缓存轨迹 %s 失败: %s", track_id, e)
    logger.info("轨迹缓存初始化完成，共 %d 条", len(_tracks_cache))


def create_app() -> Flask:
    """创建并配置 Flask 应用

    Returns:
        配置好的 Flask 应用实例
    """
    global _config_manager, _template_manager

    # 计算项目根目录（app.py 所在目录）
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    template_folder = os.path.join(project_root, "web", "templates")
    static_folder = os.path.join(project_root, "web", "static")

    app = Flask(
        __name__,
        template_folder=template_folder,
        static_folder=static_folder,
    )

    _config_manager = ConfigManager(os.path.join(project_root, "config"))
    _template_manager = TemplateManager(_config_manager)

    # 注册路由
    app.add_url_rule("/", "index", index)
    app.add_url_rule("/api/tracks", "list_tracks", list_tracks, methods=["GET"])
    app.add_url_rule(
        "/api/tracks/<track_id>", "get_track", get_track, methods=["GET"]
    )
    app.add_url_rule(
        "/api/templates", "list_templates", list_templates, methods=["GET"]
    )
    app.add_url_rule(
        "/api/template/<template_id>", "get_template", get_template, methods=["GET"]
    )
    app.add_url_rule(
        "/api/template", "create_template", create_template, methods=["POST"]
    )
    app.add_url_rule("/api/defaults", "get_defaults", get_defaults, methods=["GET"])
    app.add_url_rule(
        "/api/generate/daily", "generate_daily", generate_daily, methods=["POST"]
    )
    app.add_url_rule(
        "/api/generate/total", "generate_total", generate_total, methods=["POST"]
    )
    app.add_url_rule(
        "/api/generate/single", "generate_single", generate_single, methods=["POST"]
    )
    app.add_url_rule(
        "/api/generate/dates", "generate_dates", generate_dates, methods=["POST"]
    )
    app.add_url_rule(
        "/api/download/<job_id>", "download_files", download_files, methods=["GET"]
    )
    app.add_url_rule("/track-editor", "track_editor_page", track_editor_page)
    app.add_url_rule(
        "/api/tracks/<track_id>/coords",
        "get_track_coords",
        get_track_coords,
        methods=["GET"],
    )
    # 与 GET /api/tracks（endpoint "list_tracks"）同路径不同方法，endpoint 名必须不同
    app.add_url_rule("/api/tracks", "save_track_route", save_track, methods=["POST"])

    return app


def index():
    """渲染主页面"""
    return render_template("index.html")


def list_tracks():
    """列出所有可用轨迹（使用缓存）"""
    return jsonify(_ensure_tracks_cache())


def get_track(track_id):
    """获取轨迹详情"""
    try:
        track = _config_manager.load_track(track_id)
        return jsonify({
            "id": track.id,
            "name": track.name,
            "description": track.description,
            "num_points": len(track.base_coordinates),
            "has_correction": track.coordinate_correction is not None,
        })
    except FileNotFoundError:
        abort(404, description=f"轨迹 {track_id} 不存在")


def track_editor_page():
    """渲染轨迹编辑器页面"""
    return render_template("track_editor.html")


def get_track_coords(track_id):
    """获取轨迹的完整坐标数据（供轨迹编辑器使用）"""
    try:
        track = _config_manager.load_track(track_id)
    except FileNotFoundError:
        abort(404, description=f"轨迹 {track_id} 不存在")
    except ValueError:
        # track_id 含非法字符（如路径分隔符），与保存侧校验对齐
        abort(404, description=f"轨迹 {track_id} 不存在")
    except Exception as e:
        # KeyError / JSONDecodeError 等文件损坏场景
        logger.error("加载轨迹坐标 %s 失败: %s", track_id, e, exc_info=True)
        # 详细异常只进日志，响应用固定文案避免泄露服务端路径等信息
        return jsonify({"error": "轨迹文件无法读取，请检查文件是否损坏"}), 500

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

    return jsonify({
        "id": track.id,
        "name": track.name,
        "description": track.description,
        "base_coordinates": [
            {"longitude": p.longitude, "latitude": p.latitude}
            for p in track.base_coordinates
        ],
        "coordinate_correction": correction_data,
    })


def save_track():
    """保存轨迹（轨迹编辑器提交）"""
    global _tracks_cache

    data = request.get_json()
    if not isinstance(data, dict):
        return jsonify({"error": "无效的请求数据"}), 400

    try:
        # 解析坐标修正（前端可能传 null）
        correction = None
        cc_data = data.get("coordinate_correction")
        if cc_data:
            correction = CoordinateCorrection(
                current_center=GeoPoint(
                    longitude=cc_data["current_center"]["longitude"],
                    latitude=cc_data["current_center"]["latitude"],
                ),
                target_center=GeoPoint(
                    longitude=cc_data["target_center"]["longitude"],
                    latitude=cc_data["target_center"]["latitude"],
                ),
            )

        track = TrackDefinition(
            id=data["id"],
            name=data["name"],
            description=data.get("description", ""),
            base_coordinates=[
                GeoPoint(longitude=p["longitude"], latitude=p["latitude"])
                for p in data["base_coordinates"]
            ],
            coordinate_correction=correction,
        )

        filepath, created = _config_manager.save_track(
            track, overwrite=bool(data.get("overwrite", False))
        )
    except KeyError as e:
        return jsonify({"error": f"请求数据缺少必填字段: {e}"}), 400
    except TypeError as e:
        return jsonify({"error": f"请求数据缺少必填字段: {e}"}), 400
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except FileExistsError:
        return jsonify({"error": f"轨迹 {data.get('id', '')} 已存在", "exists": True}), 409

    # 保存后回读验证，确保文件可正常加载且坐标可分析
    try:
        reloaded = _config_manager.load_track(track.id)
        analysis = TrackAnalyzer(reloaded.base_coordinates).analyze_track()
    except Exception as e:
        logger.error("保存后校验失败 %s: %s", track.id, e, exc_info=True)
        # 详细异常只进日志，响应用固定文案避免泄露服务端路径等信息
        return jsonify({"error": "保存后校验失败，文件可能已写入但无法回读"}), 500

    # 使轨迹列表缓存失效，下次请求时重新加载
    _tracks_cache = None

    logger.info("轨迹编辑器保存成功: %s (created=%s)", track.id, created)
    return jsonify({
        "id": track.id,
        "name": track.name,
        # 仅返回相对路径，避免向客户端暴露服务端目录结构
        "filepath": f"config/tracks/{os.path.basename(filepath)}",
        "created": created,
        "distance_meters": round(analysis.total_distance_meters, 1),
        "num_points": analysis.num_points,
    }), 201


def list_templates():
    """列出所有模板"""
    templates = _template_manager.list_available()
    return jsonify(templates)


def get_template(template_id):
    """获取模板详情（包含generation_config）"""
    template = _template_manager.load_template(template_id)
    if not template:
        abort(404, description=f"模板 {template_id} 不存在")
    return jsonify(template)


def create_template():
    """创建新模板"""
    data = request.get_json()
    if not data:
        return jsonify({"error": "无效的请求数据"}), 400

    name = data.get("name")
    description = data.get("description", "")
    generation_config = data.get("generation_config", {})

    if not name:
        return jsonify({"error": "模板名称不能为空"}), 400

    try:
        result = _template_manager.save_template(name, description, generation_config)
        return jsonify(result), 201
    except Exception as e:
        logger.error("创建模板失败: %s", e, exc_info=True)
        return jsonify({"error": str(e)}), 500


def get_defaults():
    """获取默认设置"""
    defaults = _config_manager.load_defaults()
    return jsonify(defaults)


def _parse_generate_request(data: dict) -> GenerationConfig:
    """从请求体解析生成配置

    Args:
        data: 请求体字典

    Returns:
        生成配置对象
    """
    overrides = {
        "min_pace": data.get("min_pace", 7.0),
        "max_pace": data.get("max_pace", 8.0),
        "start_time_min": data.get("start_time_min", "06:00"),
        "start_time_max": data.get("start_time_max", "08:00"),
        "output_dir": data.get("output_dir", "output"),
        "include_track": data.get("include_track", True),
        "apply_correction": data.get("apply_correction", True),
        "enable_pace_fluctuation": data.get("enable_pace_fluctuation", True),
        "enable_cadence": data.get("enable_cadence", True),
    }
    if "track_id" in data:
        overrides["track_id"] = data["track_id"]

    return _template_manager.apply_template(
        template_id=data.get("template_id"),
        overrides=overrides,
    )


def generate_daily():
    """每日范围生成"""
    data = request.get_json()
    if not data:
        return jsonify({"error": "无效的请求数据"}), 400

    try:
        config = _parse_generate_request(data)
        start = datetime.datetime.strptime(data["start_date"], "%Y-%m-%d").date()
        end = datetime.datetime.strptime(data["end_date"], "%Y-%m-%d").date()
        min_km = float(data["min_km"])
        max_km = float(data["max_km"])

        from src.generation_engine import GenerationEngine

        engine = GenerationEngine(_config_manager)
        results = engine.generate_daily(start, end, min_km, max_km, config)

        job_id = (
            f"gen_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}"
            f"_{uuid.uuid4().hex[:6]}"
        )
        _generation_jobs[job_id] = results

        return jsonify({
            "job_id": job_id,
            "status": "complete",
            "total_files": len(results),
            "files": [_result_to_dict(r) for r in results],
            "download_url": f"/api/download/{job_id}",
        })
    except Exception as e:
        logger.error("生成失败: %s", e, exc_info=True)
        return jsonify({"error": str(e)}), 500


def generate_total():
    """总公里数生成"""
    data = request.get_json()
    if not data:
        return jsonify({"error": "无效的请求数据"}), 400

    try:
        config = _parse_generate_request(data)
        config.weekend_factor = data.get("weekend_factor", config.weekend_factor)
        config.rest_days_per_week = data.get(
            "rest_days_per_week", config.rest_days_per_week
        )
        config.min_daily_km = data.get("min_daily_km", config.min_daily_km)
        config.max_daily_km = data.get("max_daily_km", config.max_daily_km)

        start = datetime.datetime.strptime(data["start_date"], "%Y-%m-%d").date()
        end = datetime.datetime.strptime(data["end_date"], "%Y-%m-%d").date()
        total_km = float(data["total_km"])

        from src.generation_engine import GenerationEngine

        engine = GenerationEngine(_config_manager)
        results = engine.generate_total(start, end, total_km, config)

        job_id = (
            f"gen_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}"
            f"_{uuid.uuid4().hex[:6]}"
        )
        _generation_jobs[job_id] = results

        return jsonify({
            "job_id": job_id,
            "status": "complete",
            "total_files": len(results),
            "files": [_result_to_dict(r) for r in results],
            "download_url": f"/api/download/{job_id}",
        })
    except Exception as e:
        logger.error("生成失败: %s", e, exc_info=True)
        return jsonify({"error": str(e)}), 500


def generate_single():
    """单文件生成"""
    data = request.get_json()
    if not data:
        return jsonify({"error": "无效的请求数据"}), 400

    try:
        config = _parse_generate_request(data)
        date = datetime.datetime.strptime(data["date"], "%Y-%m-%d").date()
        distance = float(data["distance"])

        from src.generation_engine import GenerationEngine

        engine = GenerationEngine(_config_manager)
        result = engine.generate_single(date, distance, config)

        job_id = (
            f"gen_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}"
            f"_{uuid.uuid4().hex[:6]}"
        )
        _generation_jobs[job_id] = [result]

        return jsonify({
            "job_id": job_id,
            "status": "complete",
            "total_files": 1,
            "files": [_result_to_dict(result)],
            "download_url": f"/api/download/{job_id}",
        })
    except Exception as e:
        logger.error("生成失败: %s", e, exc_info=True)
        return jsonify({"error": str(e)}), 500


def generate_dates():
    """指定日期批量生成"""
    data = request.get_json()
    if not data:
        return jsonify({"error": "无效的请求数据"}), 400

    try:
        config = _parse_generate_request(data)
        dates_raw = data.get("dates", [])
        if not dates_raw or not isinstance(dates_raw, list):
            return jsonify({"error": "请至少选择一个日期"}), 400

        # 逐元素校验类型与格式，避免 TypeError/ValueError 落入兜底 500 泄露异常文本
        dates = []
        for d in dates_raw:
            if not isinstance(d, str):
                return jsonify({"error": f"日期 {d!r} 无效，应为 YYYY-MM-DD 格式的字符串"}), 400
            try:
                dates.append(datetime.datetime.strptime(d, "%Y-%m-%d").date())
            except ValueError:
                return jsonify({"error": f"日期 {d} 无效，应为 YYYY-MM-DD 格式"}), 400
        # 去重排序：重复日期会生成同名文件相互覆盖，导致 total_files 虚高、ZIP 内出现重名条目
        dates = sorted(set(dates))
        distance = float(data["distance"])

        from src.generation_engine import GenerationEngine

        engine = GenerationEngine(_config_manager)
        results = engine.generate_dates(dates, distance, config)

        if not results:
            # 全部日期生成失败（如开始时间晚于结束时间），不注册任务、不提供下载入口
            return jsonify({"error": "生成失败：所有日期均未成功生成文件，请检查配速与时间设置"}), 500

        job_id = (
            f"gen_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}"
            f"_{uuid.uuid4().hex[:6]}"
        )
        _generation_jobs[job_id] = results

        return jsonify({
            "job_id": job_id,
            "status": "complete",
            "total_files": len(results),
            "files": [_result_to_dict(r) for r in results],
            "download_url": f"/api/download/{job_id}",
        })
    except Exception as e:
        logger.error("生成失败: %s", e, exc_info=True)
        return jsonify({"error": str(e)}), 500


def download_files(job_id):
    """下载生成的文件"""
    if job_id not in _generation_jobs:
        return jsonify({"error": "任务不存在"}), 404

    results = _generation_jobs[job_id]

    if not results:
        # 任务存在但没有成功生成的文件（如全部计划失败时注册的空结果）
        return jsonify({"error": "该任务没有可下载的文件"}), 400

    if len(results) == 1:
        return send_file(results[0].filepath, as_attachment=True)

    # 多文件打包为 ZIP
    zip_path = os.path.join(
        os.path.dirname(results[0].filepath),
        f"{job_id}.zip",
    )
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for r in results:
            zf.write(r.filepath, os.path.basename(r.filepath))

    return send_file(zip_path, as_attachment=True)


def _result_to_dict(result: GenerationResult) -> dict:
    """将生成结果转换为字典

    Args:
        result: 生成结果对象

    Returns:
        结果字典
    """
    return {
        "filename": os.path.basename(result.filepath),
        "date": result.date.strftime("%Y-%m-%d"),
        "distance_km": result.distance_km,
        "pace_min_per_km": result.pace_min_per_km,
        "duration_seconds": result.duration_seconds,
        "calories": result.calories,
    }
