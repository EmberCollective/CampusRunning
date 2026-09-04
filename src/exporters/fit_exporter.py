#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""FIT格式导出器

功能: 将 ExportData 导出为 Garmin FIT Activity 格式文件

背景: Keep 的「运动数据文件导入」不解析 TCX 的任何步频字段
（Trackpoint Cadence/ns3:RunCadence/LX Steps 全写仍报"缺少步数"，
issue #8 真机验证），但完整支持 FIT 的步频/步数/步幅。
因此输出格式支持 FIT，且作为默认格式。
消息结构遵循 Garmin FIT Profile 的标准 Activity 布局。
"""

import logging
from datetime import datetime, timedelta, timezone

from garmin_fit_sdk import Encoder

from src.core.models import ExportData, TrackpointData
from src.core.cadence_generator import compute_lap_cadence_metrics
from .base import BaseExporter

logger = logging.getLogger(__name__)

# FIT 消息号（Garmin FIT Profile 定义）
MESG_NUM_FILE_ID = 0
MESG_NUM_DEVICE_INFO = 23
MESG_NUM_SPORT = 12
MESG_NUM_EVENT = 21
MESG_NUM_RECORD = 20
MESG_NUM_LAP = 19
MESG_NUM_SESSION = 18
MESG_NUM_ACTIVITY = 34

# 枚举值
FILE_TYPE_ACTIVITY = 4
MANUFACTURER_DEVELOPMENT = 255
PRODUCT_CAMPUS_RUNNING = 1
SPORT_RUNNING = 1
SUB_SPORT_GENERIC = 0
EVENT_TIMER = 0
EVENT_ACTIVITY_END = 26
EVENT_TYPE_START = 0
EVENT_TYPE_STOP = 1
EVENT_TYPE_STOP_ALL = 4

# 经纬度转 FIT semicircles（2^31 / 180）
SEMICIRCLES_PER_DEGREE = 2 ** 31 / 180.0

# 轨迹时间为本地钟面时间（与 TCX 导出器约定一致），固定东八区
# （无夏令时，用固定偏移避免 Windows 上 zoneinfo 依赖 tzdata 包）
_LOCAL_TZ = timezone(timedelta(hours=8))

_TIME_FORMAT = "%Y-%m-%dT%H:%M:%S"


class FitExporter(BaseExporter):
    """FIT格式导出器

    将跑步数据导出为 Garmin FIT Activity 文件。
    record 级写入 cadence（单脚 rpm）与 step_length（步幅，毫米），
    lap/session 级写入 total_cycles/avg_cadence/max_cadence，
    Keep 导入后可正常显示步频、步数与步幅。

    距离约定与 TCX 导出器一致：lap/session 的 total_distance 使用
    名义距离（distance_km），record 的 distance 使用轨迹点累计值。
    """

    _SERIAL_NUMBER = 0x43415055

    def export(self, data: ExportData, output_path: str) -> str:
        """导出 ExportData 为 FIT 文件

        Args:
            data: 包含跑步数据的导出数据对象
            output_path: 输出文件路径

        Returns:
            实际写入的文件路径
        """
        self.ensure_output_dir(output_path)

        encoder = Encoder()
        self._write_all_mesgs(encoder, data)
        with open(output_path, "wb") as fh:
            fh.write(encoder.close())

        logger.info(
            "FIT文件已导出: %s (%.2fkm, %d秒, %d卡路里)",
            output_path, data.distance_km,
            int(data.duration_seconds), data.calories,
        )
        return output_path

    def get_file_extension(self) -> str:
        """获取FIT文件扩展名

        Returns:
            ".fit"
        """
        return ".fit"

    def _write_all_mesgs(self, encoder: Encoder, data: ExportData) -> None:
        """按 FIT Activity 标准顺序写入全部消息

        Args:
            encoder: FIT SDK 编码器
            data: 导出数据
        """
        trackpoints = data.trackpoints
        has_track = bool(trackpoints)

        start_local = (
            self._parse_local(trackpoints[0].time)
            if has_track else data.start_time.replace(tzinfo=_LOCAL_TZ)
        )
        end_local = (
            self._parse_local(trackpoints[-1].time)
            if has_track else start_local
        )
        start_utc = start_local.astimezone(timezone.utc)
        end_utc = end_local.astimezone(timezone.utc)
        elapsed = (
            (end_local - start_local).total_seconds() or data.duration_seconds
        )

        encoder.on_mesg(MESG_NUM_FILE_ID, {
            "type": FILE_TYPE_ACTIVITY,
            "manufacturer": MANUFACTURER_DEVELOPMENT,
            "product": PRODUCT_CAMPUS_RUNNING,
            "product_name": "Campus Running Data Generator",
            "time_created": start_utc,
            "serial_number": self._SERIAL_NUMBER,
        })
        encoder.on_mesg(MESG_NUM_DEVICE_INFO, {
            "timestamp": start_utc,
            "device_index": 0,
            "manufacturer": MANUFACTURER_DEVELOPMENT,
            "product": PRODUCT_CAMPUS_RUNNING,
            "serial_number": self._SERIAL_NUMBER,
            "software_version": 1.0,
        })
        encoder.on_mesg(MESG_NUM_SPORT, {
            "sport": SPORT_RUNNING, "sub_sport": SUB_SPORT_GENERIC,
        })
        encoder.on_mesg(MESG_NUM_EVENT, {
            "timestamp": start_utc, "event": EVENT_TIMER,
            "event_type": EVENT_TYPE_START,
        })

        ascent, descent = self._write_records(encoder, trackpoints)

        encoder.on_mesg(MESG_NUM_EVENT, {
            "timestamp": end_utc, "event": EVENT_TIMER,
            "event_type": EVENT_TYPE_STOP_ALL,
        })

        lap = self._build_lap_mesg(
            data, trackpoints, start_utc, end_utc, elapsed,
            ascent, descent,
        )
        encoder.on_mesg(MESG_NUM_LAP, lap)

        session = dict(lap)
        session.update({
            "first_lap_index": 0,
            "num_laps": 1,
            "total_ascent": round(ascent),
            "total_descent": round(descent),
        })
        encoder.on_mesg(MESG_NUM_SESSION, session)

        encoder.on_mesg(MESG_NUM_ACTIVITY, {
            "timestamp": end_utc,
            # FIT 约定: local_timestamp 为本地钟面时间挂 UTC 语义
            "local_timestamp": end_local.replace(tzinfo=timezone.utc),
            "total_timer_time": elapsed,
            "num_sessions": 1,
            "event": EVENT_ACTIVITY_END,
            "event_type": EVENT_TYPE_STOP,
        })

    @classmethod
    def _write_records(
        cls, encoder: Encoder, trackpoints: list[TrackpointData],
    ) -> tuple[float, float]:
        """写入全部 record 消息并累计海拔升降

        Args:
            encoder: FIT SDK 编码器
            trackpoints: 轨迹点列表

        Returns:
            (累计上升米数, 累计下降米数)
        """
        ascent = 0.0
        descent = 0.0
        prev_altitude: float | None = None

        for tp in trackpoints:
            if prev_altitude is not None:
                delta = tp.altitude - prev_altitude
                if delta > 0:
                    ascent += delta
                else:
                    descent += abs(delta)
            prev_altitude = tp.altitude

            mesg = {
                "timestamp": cls._parse_local(tp.time).astimezone(
                    timezone.utc),
                "position_lat": cls._semicircles(tp.latitude),
                "position_long": cls._semicircles(tp.longitude),
                "altitude": tp.altitude,
                "distance": tp.distance_meters,
                "speed": tp.speed or 0.0,
            }
            if tp.run_cadence is not None:
                mesg["cadence"] = tp.run_cadence
                if tp.speed and tp.speed > 0:
                    # 步幅(毫米) = 速度*60000 / 总步频
                    mesg["step_length"] = round(
                        tp.speed * 60000 / (tp.run_cadence * 2))
            encoder.on_mesg(MESG_NUM_RECORD, mesg)

        return ascent, descent

    @staticmethod
    def _build_lap_mesg(
        data: ExportData,
        trackpoints: list[TrackpointData],
        start_utc,
        end_utc,
        elapsed: float,
        ascent: float,
        descent: float,
    ) -> dict:
        """构建 lap 消息（session 消息在此基础上扩展）

        步频聚合值来自 compute_lap_cadence_metrics，
        与 TCX 的 LX 扩展同源，保证两种格式数值一致。

        Args:
            data: 导出数据
            trackpoints: 轨迹点列表
            start_utc: 开始时间（UTC）
            end_utc: 结束时间（UTC）
            elapsed: 实际耗时（秒）
            ascent: 累计上升（米）
            descent: 累计下降（米）

        Returns:
            lap 消息字典
        """
        nominal_distance = data.distance_km * 1000
        lap: dict = {
            "message_index": 0,
            "timestamp": end_utc,
            "start_time": start_utc,
            "total_elapsed_time": elapsed,
            "total_timer_time": elapsed,
            "total_distance": nominal_distance,
            "total_calories": data.calories,
            "sport": SPORT_RUNNING,
            "sub_sport": SUB_SPORT_GENERIC,
        }

        if trackpoints:
            duration = elapsed if elapsed > 0 else 1.0
            speeds = [tp.speed or 0.0 for tp in trackpoints]
            lap["avg_speed"] = nominal_distance / duration
            lap["max_speed"] = max(speeds)

        metrics = compute_lap_cadence_metrics(trackpoints)
        if metrics is not None:
            avg_cadence, max_cadence, total_steps = metrics
            lap["avg_cadence"] = avg_cadence
            lap["max_cadence"] = max_cadence
            if total_steps is not None:
                # FIT total_cycles 为单脚圈数（总步数/2）
                lap["total_cycles"] = round(total_steps / 2)

        return lap

    @staticmethod
    def _parse_local(time_str: str) -> datetime:
        """解析轨迹点时间为带本地时区的时间

        Args:
            time_str: ISO 8601 时间字符串（本地钟面时间）

        Returns:
            带时区信息的时间
        """
        return datetime.strptime(time_str, _TIME_FORMAT).replace(
            tzinfo=_LOCAL_TZ)

    @staticmethod
    def _semicircles(degrees: float) -> int:
        """角度转 FIT semicircles

        Args:
            degrees: 经纬度角度值

        Returns:
            semicircles 整数值
        """
        return int(round(degrees * SEMICIRCLES_PER_DEGREE))
