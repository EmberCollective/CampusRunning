"""图形几何模块（web/static/js/shape_geometry.js）的单测驱动。

几何是纯 JS（无 DOM），用 Node 跑；CI 只装 Python，故无 Node 时整组跳过。
"""

import shutil
import subprocess
from pathlib import Path

import pytest

NODE = shutil.which("node")


@pytest.mark.skipif(NODE is None, reason="需要 Node.js 运行前端几何单测（CI 无 Node 时跳过）")
@pytest.mark.parametrize("suite", ["shape", "selection"])
def test_geometry_js_suite(suite):
    js_test = Path(__file__).parent / "js" / f"test_{suite}_geometry.js"
    result = subprocess.run(
        [NODE, str(js_test)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=60,
    )
    assert result.returncode == 0, f"Node 用例失败：\n{result.stdout}\n{result.stderr}"
