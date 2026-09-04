#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""TCX格式导出器

作者: 猫娘幽浮喵
功能: 将 ExportData 导出为 Garmin TCX 格式文件
"""

import os
import zipfile
import logging
from xml.dom import minidom

from src.core.models import ExportData, TrackpointData
from src.core.cadence_generator import compute_lap_cadence_metrics
from .base import BaseExporter

logger = logging.getLogger(__name__)


class TcxExporter(BaseExporter):
    """TCX格式导出器

    将跑步数据导出为 Garmin Training Center XML (TCX) 格式。
    保留与原始 TCXGenerator 完全一致的 XML 结构，
    并在轨迹点携带步频数据时输出 Cadence/TPX/LX 扩展节点。
    """

    _NAMESPACE = "http://www.garmin.com/xmlschemas/TrainingCenterDatabase/v2"
    _XSI = "http://www.w3.org/2001/XMLSchema-instance"
    _EXTENSION_NS = "http://www.garmin.com/xmlschemas/ActivityExtension/v2"
    _EXTENSION_XSD = "http://www.garmin.com/xmlschemas/ActivityExtensionv2.xsd"

    def export(self, data: ExportData, output_path: str) -> str:
        """导出 ExportData 为 TCX 文件

        Args:
            data: 包含跑步数据的导出数据对象
            output_path: 输出文件路径

        Returns:
            实际写入的文件路径
        """
        self.ensure_output_dir(output_path)

        xml_content = self._build_tcx_xml(data)

        with open(output_path, "w", encoding="utf-8") as fh:
            fh.write(xml_content)

        logger.info("TCX文件已导出: %s (%.2fkm, %d秒, %d卡路里)",
                     output_path, data.distance_km,
                     int(data.duration_seconds), data.calories)
        return output_path

    def get_file_extension(self) -> str:
        """获取TCX文件扩展名

        Returns:
            ".tcx"
        """
        return ".tcx"

    @staticmethod
    def create_zip_archive(file_list: list[str], archive_path: str) -> str:
        """将文件列表打包成ZIP压缩包

        Args:
            file_list: 要打包的文件路径列表
            archive_path: 压缩包路径

        Returns:
            压缩包路径
        """
        logger.info("正在创建压缩包: %s", archive_path)

        with zipfile.ZipFile(archive_path, "w", zipfile.ZIP_DEFLATED) as zipf:
            for file_path in file_list:
                filename = os.path.basename(file_path)
                zipf.write(file_path, filename)

        logger.info("压缩包创建完成: %s", archive_path)
        return archive_path

    def _build_tcx_xml(self, data: ExportData) -> str:
        """构建完整的TCX XML字符串

        XML结构与原始 TCXGenerator.create_tcx_content 保持完全一致：
        - TrainingCenterDatabase 根节点包含正确的 namespace 和 xsi:schemaLocation
        - Activity Sport="Running" 包含 Id、Lap
        - Lap 包含 TotalTimeSeconds、DistanceMeters、MaximumSpeed、Calories 等
        - 可选的 Track 节点包含 Trackpoint 序列
        - Author 节点包含应用信息

        Args:
            data: 导出数据

        Returns:
            格式化后的 TCX XML 字符串
        """
        distance_meters = data.distance_km * 1000
        start_time_str = data.start_time.strftime("%Y-%m-%dT%H:%M:%S")

        # 构建轨迹XML（如果有轨迹点）
        track_xml = self._build_track_xml(data.trackpoints)

        # 构建Lap扩展XML（如果有可积分的步频数据）
        lap_ext_xml = self._build_lap_extensions_xml(data.trackpoints)

        # 是否携带扩展数据（步频或速度）：决定是否声明扩展命名空间。
        # minidom 重解析要求 ns3 前缀必须已在根节点绑定，
        # 因此命名空间声明与任何可能输出 ns3 元素的条件保持一致。
        has_extension = any(
            tp.run_cadence is not None or tp.speed is not None
            for tp in data.trackpoints
        )
        if has_extension:
            root_attrs = (
                f'xmlns:ns3="{self._EXTENSION_NS}" '
                f'xsi:schemaLocation="{self._NAMESPACE} '
                f'{self._NAMESPACE}/TrainingCenterDatabasev2.xsd '
                f'{self._EXTENSION_NS} {self._EXTENSION_XSD}"'
            )
        else:
            root_attrs = (
                f'xsi:schemaLocation="{self._NAMESPACE} '
                f'{self._NAMESPACE}/TrainingCenterDatabasev2.xsd"'
            )

        # 组装完整XML
        xml_content = (
            f'<?xml version="1.0" encoding="UTF-8"?>\n'
            f'<TrainingCenterDatabase xmlns="{self._NAMESPACE}" '
            f'xmlns:xsi="{self._XSI}" '
            f'{root_attrs}>\n'
            f'  <Activities>\n'
            f'    <Activity Sport="Running">\n'
            f'      <Id>{start_time_str}</Id>\n'
            f'      <Lap StartTime="{start_time_str}">\n'
            f'        <TotalTimeSeconds>{data.duration_seconds}</TotalTimeSeconds>\n'
            f'        <DistanceMeters>{distance_meters}</DistanceMeters>\n'
            f'        <MaximumSpeed>3.5</MaximumSpeed>\n'
            f'        <Calories>{data.calories}</Calories>\n'
            f'        <Intensity>Active</Intensity>\n'
            f'        <TriggerMethod>Manual</TriggerMethod>\n'
            f'{track_xml}'
            f'{lap_ext_xml}'
            f'      </Lap>\n'
            f'    </Activity>\n'
            f'  </Activities>\n'
            f'  <Author xsi:type="Application_t">\n'
            f'    <Name>Campus Running Data Generator</Name>\n'
            f'    <Build>\n'
            f'      <Version>\n'
            f'        <VersionMajor>1</VersionMajor>\n'
            f'        <VersionMinor>0</VersionMinor>\n'
            f'        <BuildMajor>0</BuildMajor>\n'
            f'        <BuildMinor>0</BuildMinor>\n'
            f'      </Version>\n'
            f'    </Build>\n'
            f'    <LangID>zh</LangID>\n'
            f'    <PartNumber>000-00000-00</PartNumber>\n'
            f'  </Author>\n'
            f'</TrainingCenterDatabase>'
        )

        # 使用 minidom 美化XML格式
        dom = minidom.parseString(xml_content)
        return dom.toprettyxml(indent="  ")

    @staticmethod
    def _build_trackpoint_xml(tp: TrackpointData) -> str:
        """构建单个Trackpoint的XML片段

        有步频数据时（XSD 元素顺序：Cadence 在 Extensions 前）：
        <Trackpoint>
          <Time>{time}</Time>
          <Position>...</Position>
          <AltitudeMeters>{altitude}</AltitudeMeters>
          <DistanceMeters>{distance_meters}</DistanceMeters>
          <Cadence>{run_cadence}</Cadence>
          <Extensions>
            <ns3:TPX>
              <ns3:Speed>{speed}</ns3:Speed>
              <ns3:RunCadence>{run_cadence}</ns3:RunCadence>
            </ns3:TPX>
          </Extensions>
        </Trackpoint>

        Args:
            tp: 轨迹点数据

        Returns:
            Trackpoint XML片段
        """
        # Cadence 节点（XSD 中位于 DistanceMeters 之后、Extensions 之前）
        cadence_xml = ""
        if tp.run_cadence is not None:
            cadence_xml = (
                f"          <Cadence>{tp.run_cadence}</Cadence>\n"
            )

        # TPX 扩展节点（Speed 与 RunCadence 任一存在时输出）
        tpx_lines = []
        if tp.speed is not None:
            tpx_lines.append(
                f"            <ns3:Speed>{tp.speed:.2f}</ns3:Speed>"
            )
        if tp.run_cadence is not None:
            tpx_lines.append(
                f"            <ns3:RunCadence>{tp.run_cadence}</ns3:RunCadence>"
            )
        if tpx_lines:
            extension_xml = (
                f"          <Extensions>\n"
                f"            <ns3:TPX>\n"
                + "\n".join(tpx_lines) + "\n"
                f"            </ns3:TPX>\n"
                f"          </Extensions>\n"
            )
        else:
            extension_xml = ""

        return (
            f"        <Trackpoint>\n"
            f"          <Time>{tp.time}</Time>\n"
            f"          <Position>\n"
            f"            <LatitudeDegrees>{tp.latitude}</LatitudeDegrees>\n"
            f"            <LongitudeDegrees>{tp.longitude}</LongitudeDegrees>\n"
            f"          </Position>\n"
            f"          <AltitudeMeters>{tp.altitude}</AltitudeMeters>\n"
            f"          <DistanceMeters>{tp.distance_meters}</DistanceMeters>\n"
            f"{cadence_xml}"
            f"{extension_xml}"
            f"        </Trackpoint>"
        )

    @staticmethod
    def _build_track_xml(trackpoints: list) -> str:
        """构建Track节点的XML字符串

        Args:
            trackpoints: 轨迹点数据列表（可能为空）

        Returns:
            Track XML字符串，无轨迹点时返回空字符串
        """
        if not trackpoints:
            return ""

        lines = ["      <Track>"]
        for tp in trackpoints:
            lines.append(TcxExporter._build_trackpoint_xml(tp))
        lines.append("      </Track>")
        lines.append("")  # 尾部换行

        return "\n".join(lines)

    @staticmethod
    def _build_lap_extensions_xml(trackpoints: list) -> str:
        """构建Lap级步频扩展XML字符串（ns3:LX）

        从轨迹点积分计算平均步频/最大步频/总步数，
        保证 Lap 聚合值与逐点数据构造性一致。

        格式（XSD 中 Extensions 位于 Track 之后）：
        <Extensions>
          <ns3:LX>
            <ns3:AvgRunCadence>{avg}</ns3:AvgRunCadence>
            <ns3:MaxRunCadence>{max}</ns3:MaxRunCadence>
            <ns3:Steps>{steps}</ns3:Steps>
          </ns3:LX>
        </Extensions>

        Args:
            trackpoints: 轨迹点数据列表

        Returns:
            LX扩展XML字符串，无法积分时返回空字符串
        """
        metrics = compute_lap_cadence_metrics(trackpoints)
        if metrics is None:
            return ""

        avg_cadence, max_cadence, total_steps = metrics

        lines = [
            "      <Extensions>",
            "        <ns3:LX>",
            f"          <ns3:AvgRunCadence>{avg_cadence}</ns3:AvgRunCadence>",
            f"          <ns3:MaxRunCadence>{max_cadence}</ns3:MaxRunCadence>",
        ]
        if total_steps is not None:
            lines.append(
                f"          <ns3:Steps>{total_steps}</ns3:Steps>"
            )
        lines.append("        </ns3:LX>")
        lines.append("      </Extensions>")
        lines.append("")  # 尾部换行

        return "\n".join(lines)
