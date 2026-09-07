#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""scripts/sync_version.py 版本号同步单元测试。"""

from pathlib import Path

import pytest

from scripts.sync_version import apply_versions, parse_tag


@pytest.mark.parametrize(
    ("tag", "version", "quad"),
    [
        ("v3.1.0", "3.1.0", (3, 1, 0, 0)),
        ("3.2.0", "3.2.0", (3, 2, 0, 0)),
        ("v3.1.0-pr.2", "3.1.0-pr.2", (3, 1, 0, 2)),
        ("v3.2.0-rc.1", "3.2.0-rc.1", (3, 2, 0, 1)),
    ],
)
def test_parse_tag(tag, version, quad):
    assert parse_tag(tag) == (version, quad)


@pytest.mark.parametrize(
    "bad",
    ["v3.1", "v3.1.0.4", "vX.Y.Z", "3.1.0-pre", "v3.1.0-beta.x", ""],
)
def test_parse_tag_rejects_invalid(bad):
    with pytest.raises(ValueError):
        parse_tag(bad)


def _make_repo(root: Path) -> None:
    """构造含三处版本号占位的最小仓库结构。"""
    (root / "src").mkdir()
    (root / "src" / "__init__.py").write_text(
        '__version__ = "0.0.0"\n', encoding="utf-8"
    )
    (root / "version_info.txt").write_text(
        "filevers=(0, 0, 0, 0)\n"
        "prodvers=(0, 0, 0, 0)\n"
        "StringStruct('FileVersion', '0.0.0.0')\n"
        "StringStruct('ProductVersion', '0.0.0')\n",
        encoding="utf-8",
    )
    # installer.iss 为 UTF-8 BOM 文件
    (root / "installer.iss").write_bytes(
        "﻿#define MyAppVersion \"0.0.0\"\n".encode("utf-8")
    )


def test_apply_versions(tmp_path):
    _make_repo(tmp_path)
    apply_versions(tmp_path, "3.1.0-pr.2", (3, 1, 0, 2))

    init_text = (tmp_path / "src" / "__init__.py").read_text(encoding="utf-8")
    assert '__version__ = "3.1.0-pr.2"' in init_text

    vi_text = (tmp_path / "version_info.txt").read_text(encoding="utf-8")
    assert "filevers=(3, 1, 0, 2)" in vi_text
    assert "prodvers=(3, 1, 0, 2)" in vi_text
    assert "StringStruct('FileVersion', '3.1.0.2')" in vi_text
    assert "StringStruct('ProductVersion', '3.1.0-pr.2')" in vi_text

    iss_bytes = (tmp_path / "installer.iss").read_bytes()
    assert iss_bytes.startswith(b"\xef\xbb\xbf"), "BOM 必须保留"
    assert '#define MyAppVersion "3.1.0-pr.2"' in iss_bytes.decode("utf-8-sig")


def test_apply_versions_fails_on_missing_pattern(tmp_path):
    """目标行缺失时必须报错而非静默跳过。"""
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "__init__.py").write_text(
        "# no version line\n", encoding="utf-8"
    )
    (tmp_path / "version_info.txt").write_text("x\n", encoding="utf-8")
    (tmp_path / "installer.iss").write_text("x\n", encoding="utf-8")

    with pytest.raises(ValueError):
        apply_versions(tmp_path, "1.0.0", (1, 0, 0, 0))
