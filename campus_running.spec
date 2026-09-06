# -*- mode: python ; coding: utf-8 -*-
"""校园跑步数据生成器 - PyInstaller 打包定义（onedir，双入口）

构建命令（项目根目录、激活 .venv 后执行）::

    pyinstaller campus_running.spec --noconfirm --clean

产物：dist/CampusRunningGenerator/
    CampusRunningGen.exe      桌面 GUI（noconsole，入口 desktop.py）
    CampusRunningGenCLI.exe   命令行工具（console，入口 main.py）
    _internal/                Python 运行时、依赖库与数据文件

关键选择：
- onedir 而非 onefile：Web 静态资源（Leaflet 等）与轨迹配置较多，
  onefile 每次启动都要解压临时目录，启动慢且易触发杀毒软件误报；
  onedir 启动快、误报少，也更契合 Inno Setup 的整目录分发。
- upx=False：UPX 压缩 DLL/pyd 常被杀软标记为可疑，且对收益有限，
  一律关闭。
- 前置条件：desktop.py（GUI 入口）与 pywebview（requirements-desktop.txt）
  必须就位；collect_submodules("webview") 要求 pywebview 已安装。
"""

import glob
import os

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

# ---------------------------------------------------------------------------
# 可选资源：图标 / 版本资源文件由并行任务生成，存在则启用，缺失则回退默认
# ---------------------------------------------------------------------------
ICON = "assets/icon.ico" if os.path.exists("assets/icon.ico") else None
VERSION = "version_info.txt" if os.path.exists("version_info.txt") else None

# venv 中遗留的未用包与测试依赖，一律不进产物
EXCLUDES = [
    "PIL", "gpxpy", "websocket", "yaml",
    "pytest", "pluggy", "iniconfig", "Pygments", "tkinter",
]

# ---------------------------------------------------------------------------
# GUI 数据文件：Web 模板与静态资源、轨迹/模板配置（仅 .json，
# 排除 TEMPLATE_GUIDE.md），以及 pywebview 内嵌的平台 JS/HTML 资源
# （缺它 EdgeChromium 后端无法渲染页面）
# ---------------------------------------------------------------------------
GUI_DATAS = [
    ("web/templates", "web/templates"),
    ("web/static", "web/static"),
]
GUI_DATAS += [(f, "config") for f in sorted(glob.glob("config/*.json"))]
GUI_DATAS += [(f, "config/tracks") for f in sorted(glob.glob("config/tracks/*.json"))]
GUI_DATAS += [(f, "config/templates") for f in sorted(glob.glob("config/templates/*.json"))]
GUI_DATAS += collect_data_files("webview")

# hiddenimports 保险：
# - pywebview 按操作系统在函数内部动态选择平台后端，静态分析不可见；
# - src.exporters.fit_exporter、src.generation_engine 等在 web/routes.py
#   中为函数级延迟导入，collect_submodules("src") 兜底收集全部子模块
GUI_HIDDENIMPORTS = (
    ["webview.platforms.edgechromium"]
    + collect_submodules("webview")
    + collect_submodules("src")
    + collect_submodules("web")
)


def _dedup(toc):
    """按目标路径（TOC 条目第一项）去重并保持首次出现顺序。

    用于合并两个 Analysis 的 pure/binaries/datas：同一份数据文件
    （如 config 下的 json）可能被双方各收录一次，重复条目会让
    COLLECT 输出冗余甚至冲突。
    """
    seen = set()
    merged = []
    for entry in toc:
        key = entry[0]
        if key not in seen:
            seen.add(key)
            merged.append(entry)
    return merged


# ---------------------------------------------------------------------------
# 双 Analysis：GUI（desktop.py，完整资源）与 CLI（main.py，仅需 src 包）
# ---------------------------------------------------------------------------
a_gui = Analysis(
    ["desktop.py"],
    pathex=["."],
    binaries=[],
    datas=GUI_DATAS,
    hiddenimports=GUI_HIDDENIMPORTS,
    hookspath=[],
    hooksconfig={},
    excludes=EXCLUDES,
    noarchive=False,
)

a_cli = Analysis(
    ["main.py"],
    pathex=["."],
    binaries=[],
    datas=[],
    hiddenimports=collect_submodules("src"),
    hookspath=[],
    hooksconfig={},
    excludes=EXCLUDES,
    noarchive=False,
)

# 共享 PYZ：两个入口的纯 Python 模块合并去重后打进同一包
pyz = PYZ(_dedup(a_gui.pure + a_cli.pure))

exe_gui = EXE(
    pyz,
    a_gui.scripts,
    [],
    exclude_binaries=True,
    name="CampusRunningGen",
    icon=ICON,
    version=VERSION,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,  # GUI：不弹黑框
)

# main.py 开头对 sys.stdout 做 UTF-8 重包（detach），无控制台会直接崩溃，
# CLI 入口必须 console=True
exe_cli = EXE(
    pyz,
    a_cli.scripts,
    [],
    exclude_binaries=True,
    name="CampusRunningGenCLI",
    icon=ICON,
    version=VERSION,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,  # CLI：必须保留真实控制台
)

coll = COLLECT(
    exe_gui,
    exe_cli,
    _dedup(a_gui.binaries + a_cli.binaries),
    _dedup(a_gui.datas + a_cli.datas),
    strip=False,
    upx=False,
    name="CampusRunningGenerator",
)
