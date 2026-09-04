#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""FIT 导出器结构与聚合一致性测试"""

import datetime

import pytest
from garmin_fit_sdk import Decoder, Stream

from src.core.models import ExportData, TrackpointData
from src.exporters.fit_exporter import FitExporter


def make_trackpoint(time: datetime.datetime, cadence=None, speed=None,
                    distance=10.0) -> TrackpointData:
    return TrackpointData(
        time=time.strftime("%Y-%m-%dT%H:%M:%S"),
        latitude=26.44,
        longitude=106.67,
        altitude=100.0,
        distance_meters=distance,
        run_cadence=cadence,
        speed=speed,
    )


def make_export_data(trackpoints, distance_km=3.0) -> ExportData:
    start = datetime.datetime(2026, 9, 4, 7, 0, 0)
    return ExportData(
        date=start.date(),
        start_time=start,
        distance_km=distance_km,
        duration_seconds=1350.0,
        calories=180,
        trackpoints=list(trackpoints),
    )


def decode_file(path) -> dict:
    """解码 FIT 文件，断言无错误并返回分组消息"""
    messages, errors = Decoder(Stream.from_file(str(path))).read()
    assert errors == []
    return messages


@pytest.mark.unit
class TestFitStructure:
    """FIT 文件消息结构测试"""

    def _cadence_points(self, n=5):
        base = datetime.datetime(2026, 9, 4, 7, 0, 0)
        return [
            make_trackpoint(
                base + datetime.timedelta(seconds=i * 30),
                cadence=80 + i, speed=2.38, distance=i * 71.0,
            )
            for i in range(n)
        ]

    def test_export_writes_file_and_decodes(self, tmp_path):
        exporter = FitExporter()
        path = str(tmp_path / "test.fit")
        result = exporter.export(make_export_data(self._cadence_points()), path)

        assert result == path
        messages = decode_file(path)
        for group in ("file_id_mesgs", "record_mesgs", "lap_mesgs",
                      "session_mesgs", "activity_mesgs"):
            assert group in messages

    def test_get_file_extension(self):
        assert FitExporter().get_file_extension() == ".fit"

    def test_record_fields_and_cadence(self, tmp_path):
        path = str(tmp_path / "test.fit")
        FitExporter().export(make_export_data(self._cadence_points()), path)

        records = decode_file(path)["record_mesgs"]
        assert len(records) == 5
        for rec in records:
            assert 75 <= rec["cadence"] <= 96  # 单脚 rpm
            assert 600 <= rec["step_length"] <= 1000  # 步幅 mm
            assert "position_lat" in rec and "position_long" in rec
            assert "distance" in rec and "speed" in rec

    def test_position_roundtrip(self, tmp_path):
        """semicircles 编码后解码应还原为原坐标（±1e-6 度）"""
        path = str(tmp_path / "test.fit")
        FitExporter().export(make_export_data(self._cadence_points()), path)

        rec = decode_file(path)["record_mesgs"][0]
        lat = rec["position_lat"] * 180.0 / 2 ** 31
        lon = rec["position_long"] * 180.0 / 2 ** 31
        assert abs(lat - 26.44) < 1e-6
        assert abs(lon - 106.67) < 1e-6

    def test_timestamp_is_utc(self, tmp_path):
        """本地 07:00（东八区）应写为前一天 23:00 UTC"""
        path = str(tmp_path / "test.fit")
        FitExporter().export(make_export_data(self._cadence_points()), path)

        rec = decode_file(path)["record_mesgs"][0]
        assert rec["timestamp"] == datetime.datetime(
            2026, 9, 3, 23, 0, 0, tzinfo=datetime.timezone.utc)

    def test_session_aggregates_consistent(self, tmp_path):
        """session 步频聚合值必须与 compute_lap_cadence_metrics 同源"""
        from src.core.cadence_generator import compute_lap_cadence_metrics

        points = self._cadence_points()
        path = str(tmp_path / "test.fit")
        FitExporter().export(make_export_data(points), path)

        session = decode_file(path)["session_mesgs"][0]
        avg_c, max_c, steps = compute_lap_cadence_metrics(points)
        assert session["avg_cadence"] == avg_c
        assert session["max_cadence"] == max_c
        assert session["total_cycles"] == round(steps / 2)

    def test_session_distance_uses_nominal(self, tmp_path):
        """lap/session 距离用名义距离（与 TCX 行为一致）"""
        path = str(tmp_path / "test.fit")
        FitExporter().export(
            make_export_data(self._cadence_points(), distance_km=3.0), path)

        session = decode_file(path)["session_mesgs"][0]
        assert session["total_distance"] == 3000.0

    def test_empty_trackpoints_still_valid(self, tmp_path):
        """无轨迹点时应导出仅含汇总信息的合法 FIT"""
        path = str(tmp_path / "test.fit")
        FitExporter().export(make_export_data([]), path)

        messages = decode_file(path)
        assert messages.get("record_mesgs", []) == []
        assert "avg_cadence" not in messages["session_mesgs"][0]


@pytest.mark.unit
class TestFitLegacyCompat:
    """关闭步频数据时的输出测试"""

    def test_no_cadence_fields(self, tmp_path):
        base = datetime.datetime(2026, 9, 4, 7, 0, 0)
        points = [
            make_trackpoint(base),
            make_trackpoint(base.replace(second=30)),
        ]
        path = str(tmp_path / "test.fit")
        FitExporter().export(make_export_data(points), path)

        messages = decode_file(path)
        for rec in messages["record_mesgs"]:
            assert "cadence" not in rec
            assert "step_length" not in rec
            # speed 缺失时应省略字段而非写 0.0
            assert "speed" not in rec
        session = messages["session_mesgs"][0]
        assert "avg_cadence" not in session
        assert "total_cycles" not in session
        # 无有效速度时不应出现 max_speed=0 < avg_speed 的矛盾
        assert "max_speed" not in session

    def test_zero_cadence_no_step_length(self, tmp_path):
        """run_cadence=0 时不应计算 step_length（除零守卫）"""
        base = datetime.datetime(2026, 9, 4, 7, 0, 0)
        points = [
            make_trackpoint(base, cadence=0, speed=2.0),
            make_trackpoint(base.replace(second=30), cadence=0, speed=2.0),
        ]
        path = str(tmp_path / "test.fit")
        FitExporter().export(make_export_data(points), path)

        for rec in decode_file(path)["record_mesgs"]:
            assert "step_length" not in rec


@pytest.mark.unit
class TestOutputFormatValidation:
    """输出格式配置校验测试"""

    def test_invalid_format_raises(self):
        from src.core.models import GenerationConfig

        with pytest.raises(ValueError, match="不支持的输出格式"):
            GenerationConfig(output_format="TCX")

    def test_valid_formats_accepted(self):
        from src.core.models import GenerationConfig

        assert GenerationConfig(output_format="fit").output_format == "fit"
        assert GenerationConfig(output_format="tcx").output_format == "tcx"


@pytest.mark.integration
class TestEngineFitWiring:
    """生成引擎到 FIT 导出器的接线测试"""

    def test_engine_default_format_is_fit(self, tmp_path):
        from src.generation_engine import GenerationEngine
        from src.core.models import GenerationConfig
        from src.exporters.fit_exporter import FitExporter

        # 默认配置应为 fit，且引擎能取到 FitExporter
        config = GenerationConfig(output_dir=str(tmp_path))
        assert config.output_format == "fit"

        engine = GenerationEngine.__new__(GenerationEngine)
        engine._exporters = {}
        assert isinstance(engine._get_exporter("fit"), FitExporter)

    def test_engine_unknown_format_raises(self):
        from src.generation_engine import GenerationEngine

        engine = GenerationEngine.__new__(GenerationEngine)
        engine._exporters = {"tcx": object()}
        with pytest.raises(ValueError, match="不支持的输出格式"):
            engine._get_exporter("gpx")
