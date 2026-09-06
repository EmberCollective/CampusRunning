#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
校园跑步数据生成器
用于生成校园跑步数据的TCX格式文件

作者: 猫娘幽浮喵
"""

from .core.track_analyzer import TrackAnalyzer
from .core.track_generator import TrackGenerator
from .core.pace_fluctuator import PaceFluctuator
from .core.coordinate_corrector import CoordinateCorrector
from .exporters.tcx_exporter import TcxExporter

# 版本号单一来源：跟随发布 tag（次版本号递增），与打包元数据
# （version_info.txt / installer.iss / CI 注入的 /DMyAppVersion）保持一致
__version__ = "3.1.0"
__author__ = "猫娘幽浮喵"

__all__ = [
    "TrackAnalyzer",
    "TrackGenerator",
    "PaceFluctuator",
    "CoordinateCorrector",
    "TcxExporter",
]
