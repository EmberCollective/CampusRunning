#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""TCX 导出器步频节点的结构测试"""

import datetime
import xml.etree.ElementTree as ET

import pytest

from src.core.models import ExportData, TrackpointData
from src.exporters.tcx_exporter import TcxExporter

TC_NS = "http://www.garmin.com/xmlschemas/TrainingCenterDatabase/v2"
EXT_NS = "http://www.garmin.com/xmlschemas/ActivityExtension/v2"


def make_trackpoint(time: datetime.datetime, cadence=None, speed=None) -> TrackpointData:
    return TrackpointData(
        time=time.strftime("%Y-%m-%dT%H:%M:%S"),
        latitude=26.44,
        longitude=106.67,
        altitude=100.0,
        distance_meters=10.0,
        run_cadence=cadence,
        speed=speed,
    )


def make_export_data(trackpoints) -> ExportData:
    start = datetime.datetime(2026, 9, 4, 7, 0, 0)
    return ExportData(
        date=start.date(),
        start_time=start,
        distance_km=3.0,
        duration_seconds=1500.0,
        calories=180,
        trackpoints=list(trackpoints),
    )


def export_content(trackpoints, tmp_path) -> str:
    exporter = TcxExporter()
    path = str(tmp_path / "test.tcx")
    exporter.export(make_export_data(trackpoints), path)
    with open(path, "r", encoding="utf-8") as fh:
        return fh.read()


@pytest.mark.unit
class TestLegacyCompat:
    """无步频数据时的向后兼容测试"""

    def test_legacy_output_has_no_cadence_nodes(self, tmp_path):
        base = datetime.datetime(2026, 9, 4, 7, 0, 0)
        points = [
            make_trackpoint(base),
            make_trackpoint(base.replace(second=30)),
        ]
        content = export_content(points, tmp_path)

        assert "<Cadence>" not in content
        assert "ns3:" not in content
        assert "<Extensions>" not in content
        assert "xmlns:ns3" not in content
        assert "ActivityExtensionv2.xsd" not in content

    def test_empty_trackpoints_no_cadence(self, tmp_path):
        content = export_content([], tmp_path)

        assert "<Cadence>" not in content
        assert "ns3:" not in content


@pytest.mark.unit
class TestCadenceOutput:
    """有步频数据时的输出结构测试"""

    def _cadence_points(self, n=5):
        base = datetime.datetime(2026, 9, 4, 7, 0, 0)
        return [
            make_trackpoint(
                base + datetime.timedelta(seconds=i * 30),
                cadence=80 + i,
                speed=2.38,
            )
            for i in range(n)
        ]

    def test_trackpoint_cadence_and_tpx_structure(self, tmp_path):
        content = export_content(self._cadence_points(), tmp_path)

        assert "<Cadence>80</Cadence>" in content
        assert "<ns3:TPX>" in content
        assert "<ns3:Speed>2.38</ns3:Speed>" in content
        assert "<ns3:RunCadence>80</ns3:RunCadence>" in content

        # XSD 元素顺序: Cadence 在 Extensions 前; TPX 内 Speed 在 RunCadence 前
        first_point = content[: content.index("</Trackpoint>")]
        assert first_point.index("<Cadence>") < first_point.index("<Extensions>")
        assert first_point.index("ns3:Speed") < first_point.index("ns3:RunCadence")

    def test_lap_lx_structure(self, tmp_path):
        content = export_content(self._cadence_points(), tmp_path)

        assert "<ns3:LX>" in content
        assert "<ns3:AvgRunCadence>" in content
        assert "<ns3:MaxRunCadence>" in content
        assert "<ns3:Steps>" in content

        # LX 位于 </Track> 之后、</Lap> 之前
        assert content.rindex("</Track>") < content.index("<ns3:LX>")
        assert content.index("<ns3:LX>") < content.index("</Lap>")

    def test_root_namespace_declared_conditionally(self, tmp_path):
        content = export_content(self._cadence_points(), tmp_path)

        assert f'xmlns:ns3="{EXT_NS}"' in content
        assert "ActivityExtensionv2.xsd" in content
        # minidom 重解析不抛 unbound prefix（export 内部隐式验证）

    def test_cadence_without_speed(self, tmp_path):
        base = datetime.datetime(2026, 9, 4, 7, 0, 0)
        points = [
            make_trackpoint(base, cadence=82),
            make_trackpoint(base.replace(second=30), cadence=83),
        ]
        content = export_content(points, tmp_path)

        assert "<ns3:RunCadence>82</ns3:RunCadence>" in content
        assert "ns3:Speed" not in content
        assert "<ns3:LX>" in content

    def test_speed_only_declares_namespace(self, tmp_path):
        """仅有 speed 无 cadence 时也必须声明 ns3 命名空间（minidom unbound prefix）"""
        base = datetime.datetime(2026, 9, 4, 7, 0, 0)
        points = [
            make_trackpoint(base, speed=2.38),
            make_trackpoint(base.replace(second=30), speed=2.40),
        ]
        content = export_content(points, tmp_path)  # 不抛即通过

        assert "<ns3:Speed>2.38</ns3:Speed>" in content
        assert "<Cadence>" not in content
        assert "<ns3:LX>" not in content  # 无步频数据无 LX

    def test_single_point_no_lx(self, tmp_path):
        base = datetime.datetime(2026, 9, 4, 7, 0, 0)
        points = [make_trackpoint(base, cadence=82, speed=2.4)]
        content = export_content(points, tmp_path)

        assert "<Cadence>82</Cadence>" in content
        assert "<ns3:TPX>" in content
        assert "<ns3:LX>" not in content

    def test_lx_values_consistent_with_trackpoints(self, tmp_path):
        points = self._cadence_points()
        content = export_content(points, tmp_path)

        root = ET.fromstring(content)
        lx = root.find(f".//{{{EXT_NS}}}LX")
        assert lx is not None

        steps = int(lx.find(f"{{{EXT_NS}}}Steps").text)
        max_cadence = int(lx.find(f"{{{EXT_NS}}}MaxRunCadence").text)
        avg_cadence = int(lx.find(f"{{{EXT_NS}}}AvgRunCadence").text)

        # LX 聚合值必须与 compute_lap_cadence_metrics 同源一致
        from src.core.cadence_generator import compute_lap_cadence_metrics

        expected = compute_lap_cadence_metrics(points)
        assert expected is not None
        assert (avg_cadence, max_cadence, steps) == expected

    def test_xml_parseable_both_modes(self, tmp_path):
        # 有步频模式（覆盖 minidom unbound prefix 回归）
        export_content(self._cadence_points(), tmp_path)

        # 无步频模式
        base = datetime.datetime(2026, 9, 4, 7, 0, 0)
        export_content(
            [make_trackpoint(base), make_trackpoint(base.replace(second=30))],
            tmp_path,
        )


@pytest.mark.integration
class TestEndToEndStride:
    """完整生成链的步幅一致性测试"""

    def test_generated_stride_in_plausible_range(self, tmp_path):
        from src.core.cadence_generator import compute_lap_cadence_metrics
        from src.core.track_generator import TrackGenerator
        from src.core.track_analyzer import TrackAnalyzer
        from src.core.models import GeoPoint

        # 简单方形轨迹（约 1880 米周长）
        base_coords = [
            GeoPoint(longitude=106.670, latitude=26.440),
            GeoPoint(longitude=106.675, latitude=26.440),
            GeoPoint(longitude=106.675, latitude=26.444),
            GeoPoint(longitude=106.670, latitude=26.444),
        ]
        analyzer = TrackAnalyzer(base_coords)
        track_gen = TrackGenerator(
            track_analysis=analyzer.analyze_track(),
            analyzer=analyzer,
        )

        start = datetime.datetime(2026, 9, 4, 7, 0, 0)
        geo_points = track_gen.generate_smooth_track(3.0, 50)
        duration = 3.0 * 7.5 * 60  # 配速 7.5 min/km
        trackpoints = track_gen.generate_tcx_trackpoints(
            geo_points, start, duration, base_pace_min_per_km=7.5,
        )

        result = compute_lap_cadence_metrics(trackpoints)
        assert result is not None

        _, _, total_steps = result
        distance_meters = trackpoints[-1].distance_meters
        stride = distance_meters / total_steps
        assert 0.5 <= stride <= 1.5
