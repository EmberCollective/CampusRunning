#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""src/paths.py 路径锚定单元测试。

源码模式直接断言（CI ubuntu 可运行）；frozen 模式通过 monkeypatch
sys.frozen / sys._MEIPASS / sys.executable 模拟 PyInstaller 环境。
"""

import json
import os
import sys
from pathlib import Path

import pytest

from src import paths

REPO_ROOT = Path(__file__).resolve().parent.parent


def test_source_mode_not_frozen():
    assert paths.is_frozen() is False


def test_resource_root_is_repo_root():
    root = paths.get_resource_root()
    assert os.path.abspath(root) == str(REPO_ROOT)
    # 资源根应能定位到入口脚本与配置目录
    assert os.path.isfile(os.path.join(root, "main.py"))
    assert os.path.isdir(os.path.join(root, "config"))


def test_project_root_is_repo_root():
    root = paths.get_project_root()
    assert os.path.abspath(root) == str(REPO_ROOT)
    assert os.path.isfile(os.path.join(root, "main.py"))


def test_config_dir_is_repo_config():
    assert os.path.abspath(paths.get_config_dir()) == str(REPO_ROOT / "config")


def test_config_dir_no_side_effect(tmp_path, monkeypatch):
    """源码模式下解析配置目录不得在 CWD 下创建任何新目录"""
    monkeypatch.chdir(tmp_path)
    config_dir = paths.get_config_dir()
    # 指向仓库内既有配置目录，而非 tmp_path 下新建目录
    assert config_dir == str(REPO_ROOT / "config")
    assert not (tmp_path / "config").exists()


def test_output_root_follows_cwd(tmp_path, monkeypatch):
    assert os.path.abspath(paths.get_output_root()) == os.getcwd()
    monkeypatch.chdir(tmp_path)
    assert os.path.abspath(paths.get_output_root()) == str(tmp_path)


# ---------------------------------------------------------------------------
# frozen（PyInstaller）模式：monkeypatch 模拟，跨平台可运行
# ---------------------------------------------------------------------------


@pytest.fixture
def frozen_env(tmp_path, monkeypatch):
    """模拟 PyInstaller frozen 运行环境

    构造 _MEIPASS 资源根（含 config 种子）与可写的 exe 目录，
    并清空可写基目录缓存避免跨测试污染。

    Yields:
        (resource_root, exe_dir) 两个 Path
    """
    resource_root = tmp_path / "meipass"
    (resource_root / "config" / "tracks").mkdir(parents=True)
    (resource_root / "config" / "templates").mkdir(parents=True)
    (resource_root / "config" / "default_settings.json").write_text(
        "{}", encoding="utf-8"
    )
    (resource_root / "config" / "tracks" / "t1.json").write_text(
        '{"id": "builtin"}', encoding="utf-8"
    )
    # 非 json 说明文档：播种时应被跳过
    (resource_root / "config" / "templates" / "GUIDE.md").write_text(
        "doc", encoding="utf-8"
    )

    exe_dir = tmp_path / "app"
    exe_dir.mkdir()

    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(resource_root), raising=False)
    monkeypatch.setattr(
        sys, "executable", str(exe_dir / "CampusRunningGen.exe"), raising=False
    )
    monkeypatch.setattr(paths, "_writable_base_cache", None)
    return resource_root, exe_dir


def test_frozen_resource_root_is_meipass(frozen_env):
    resource_root, _ = frozen_env
    assert paths.get_resource_root() == str(resource_root)


def test_frozen_writable_base_is_exe_dir(frozen_env):
    _, exe_dir = frozen_env
    assert paths.get_writable_base() == str(exe_dir)


def test_frozen_config_dir_seeds_defaults(frozen_env):
    """frozen 首次取配置目录：种子 json 补齐到 exe 旁，非 json 不复制"""
    _, exe_dir = frozen_env
    config_dir = paths.get_config_dir()
    assert config_dir == str(exe_dir / "config")
    assert (exe_dir / "config" / "default_settings.json").exists()
    assert (exe_dir / "config" / "tracks" / "t1.json").exists()
    assert not (exe_dir / "config" / "templates" / "GUIDE.md").exists()


def test_frozen_seed_never_overwrites_user_files(frozen_env):
    """播种只补缺：用户已修改的文件内容原样保留"""
    _, exe_dir = frozen_env
    target = exe_dir / "config"
    (target / "tracks").mkdir(parents=True)
    (target / "tracks" / "t1.json").write_text(
        '{"id": "user-modified"}', encoding="utf-8"
    )
    paths._seed_default_config(str(target))
    content = json.loads(
        (target / "tracks" / "t1.json").read_text(encoding="utf-8")
    )
    assert content["id"] == "user-modified"


def test_frozen_output_root_is_writable_base(frozen_env):
    _, exe_dir = frozen_env
    assert paths.get_output_root() == str(exe_dir)
