#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""pytest 共享配置

项目无 pyproject/setup 配置，此处显式将项目根目录加入
sys.path，保证 `from src...` 绝对导入在测试中可用。
"""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
