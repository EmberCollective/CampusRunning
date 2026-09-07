#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""统一路径锚定模块

将散落在各入口（app.py / main.py / web/routes.py / generation_engine.py）
的 __file__ 路径推导收口到此处，并为 PyInstaller frozen 模式提供一致的
路径语义：

- 只读资源（web/templates、web/static、config 种子）从 sys._MEIPASS 读取
- 可写数据（config、output）优先落在 exe 旁目录（portable 便携模式），
  不可写时回退到 %LOCALAPPDATA%\\CampusRunningDataGeneration

铁律：
1. 源码模式（python app.py / python main.py）行为与收口前完全等价
2. frozen 分支仅在 sys.frozen 存在时激活，对源码模式零副作用

本模块不得 import 任何项目内模块（零循环导入），仅依赖标准库。
"""

import logging
import os
import shutil
import sys

logger = logging.getLogger(__name__)

# frozen 模式下可写基目录缓存（避免每次调用都做写探测）
_writable_base_cache: str | None = None

# exe 目录不可写时的回退目录名（位于 %LOCALAPPDATA% 下）
_FALLBACK_DIR_NAME = "CampusRunningDataGeneration"


def is_frozen() -> bool:
    """判断当前是否运行在 PyInstaller frozen 模式

    Returns:
        frozen 模式返回 True，源码模式返回 False
    """
    return bool(getattr(sys, "frozen", False))


def _get_source_root() -> str:
    """源码模式下的仓库根目录（src/ 的上一级）

    Returns:
        仓库根目录绝对路径
    """
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def get_resource_root() -> str:
    """只读资源根目录（web/templates、web/static、config 种子）

    frozen 模式下资源由 PyInstaller 打包进 sys._MEIPASS（onedir 布局中
    指向 _internal 目录），该目录只读不可写；源码模式即仓库根。

    Returns:
        资源根目录绝对路径
    """
    if is_frozen():
        # getattr 防御非标准 frozen 环境（正常 PyInstaller 必定设置 _MEIPASS）
        return str(getattr(sys, "_MEIPASS", os.path.dirname(sys.executable)))
    return _get_source_root()


def get_project_root() -> str:
    """程序所在目录

    frozen 模式返回 exe 所在目录；源码模式返回仓库根。
    当前无核心调用方，与 get_resource_root / get_writable_base 构成
    完整的三根 API（资源根 / 程序根 / 可写根），保留供打包与
    桌面入口场景使用。

    Returns:
        程序所在目录绝对路径
    """
    if is_frozen():
        return os.path.dirname(sys.executable)
    return _get_source_root()


def _probe_writable(directory: str) -> bool:
    """实际写入探测文件判断目录是否可写

    os.access 在 Windows 上不可靠（受只读属性、UAC 虚拟化等影响），
    因此用真实写入再删除的方式探测。

    Args:
        directory: 待探测的目录

    Returns:
        目录存在且可写返回 True，否则 False
    """
    if not os.path.isdir(directory):
        return False
    # 文件名附加 pid：并发首调时避免两线程操作同一探测文件
    probe_path = os.path.join(directory, f".write_probe_{os.getpid()}")
    try:
        with open(probe_path, "w", encoding="utf-8") as f:
            f.write("probe")
        os.remove(probe_path)
    except OSError:
        return False
    return True


def get_writable_base() -> str:
    """获取可写基目录（frozen 模式下用户数据与输出的锚点）

    frozen 模式优先使用 exe 所在目录（portable 便携模式，写探测通过）；
    不可写时（如安装到 Program Files）回退到
    %LOCALAPPDATA%\\CampusRunningDataGeneration 并自动创建。
    结果缓存于模块级变量，避免重复探测。

    源码模式直接返回仓库根（与收口前行为一致，不做探测）。

    Returns:
        可写基目录绝对路径
    """
    global _writable_base_cache
    if _writable_base_cache is not None:
        return _writable_base_cache

    if not is_frozen():
        _writable_base_cache = _get_source_root()
        return _writable_base_cache

    exe_dir = os.path.dirname(sys.executable)
    if _probe_writable(exe_dir):
        _writable_base_cache = exe_dir
        return exe_dir

    fallback_base = os.path.join(
        os.environ.get("LOCALAPPDATA", os.path.expanduser("~")),
        _FALLBACK_DIR_NAME,
    )
    os.makedirs(fallback_base, exist_ok=True)
    logger.warning(
        "exe 所在目录不可写，已回退到用户本地目录: %s", fallback_base
    )
    _writable_base_cache = fallback_base
    return fallback_base


def _seed_json_files(src_dir: str, dst_dir: str) -> None:
    """将 src_dir 下的 .json 文件补缺复制到 dst_dir

    只复制 .json 文件（天然跳过 TEMPLATE_GUIDE.md 等说明文档）；
    只补缺失、绝不覆盖已有文件。

    Args:
        src_dir: 资源源目录
        dst_dir: 目标目录
    """
    if not os.path.isdir(src_dir):
        logger.warning("播种源目录不存在，跳过: %s", src_dir)
        return
    os.makedirs(dst_dir, exist_ok=True)
    for name in os.listdir(src_dir):
        src_path = os.path.join(src_dir, name)
        if not name.endswith(".json") or not os.path.isfile(src_path):
            continue
        dst_path = os.path.join(dst_dir, name)
        if os.path.exists(dst_path):
            continue
        shutil.copy2(src_path, dst_path)
        logger.info("播种默认配置: %s", dst_path)


def _seed_default_config(config_dir: str) -> None:
    """从打包资源中播种默认配置到目标目录（仅 frozen 模式调用）

    复制内容：顶层 default_settings.json 以及 tracks/、templates/
    等配置子目录（整体遍历，后续新增配置子目录无需改动此函数）。

    "只补缺失、绝不覆盖"带来如下语义：
    - 用户删除某个内置轨迹后重启会自动恢复该文件
    - 用户对已有文件的修改始终保留
    - 删除整个 config 目录即可完全恢复出厂设置

    Args:
        config_dir: 目标配置目录
    """
    seed_root = os.path.join(get_resource_root(), "config")
    if not os.path.isdir(seed_root):
        logger.warning("未找到打包内置配置，跳过播种: %s", seed_root)
        return

    _seed_json_files(seed_root, config_dir)
    for name in os.listdir(seed_root):
        src_sub = os.path.join(seed_root, name)
        if os.path.isdir(src_sub):
            _seed_json_files(src_sub, os.path.join(config_dir, name))


def get_config_dir() -> str:
    """获取配置目录

    源码模式返回 仓库根/config（与收口前行为一致，无任何副作用）；
    frozen 模式返回 可写基目录/config，并先播种默认配置。

    Returns:
        配置目录绝对路径
    """
    if not is_frozen():
        return os.path.join(_get_source_root(), "config")
    config_dir = os.path.join(get_writable_base(), "config")
    _seed_default_config(config_dir)
    return config_dir


def get_output_root() -> str:
    """相对 output_dir 的解析锚点

    源码模式返回当前工作目录（与旧 os.path.abspath 按 CWD 解析的
    行为严格一致）；frozen 模式返回可写基目录。

    Returns:
        锚点目录绝对路径
    """
    if is_frozen():
        return get_writable_base()
    return os.getcwd()
