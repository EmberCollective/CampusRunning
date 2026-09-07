#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""发版版本号同步工具：从 git tag 生成三处版本号，替代手工同步。

用法（CI 在 PyInstaller 打包前调用）::

    python scripts/sync_version.py v3.1.0-pr.2

同步目标：
1. src/__init__.py    __version__（/api/version 与界面显示）
2. version_info.txt   exe 文件属性四元组与版本字符串
3. installer.iss      #define MyAppVersion 默认值（CI 本有 /D 注入，
                      同步仅为本地构建与仓库一致性）

tag 语义：vX.Y.Z 正式版 → 四元组 (X, Y, Z, 0)；
vX.Y.Z-<pre>.N 预发布（如 -pr.2 / -rc.1）→ 四元组第四位取 N。
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# vX.Y.Z 或 vX.Y.Z-pre.N（pre 为字母标识，N 为数字序号）
_TAG_RE = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)(?:-([A-Za-z]+)\.(\d+))?$")


def parse_tag(tag: str) -> tuple[str, tuple[int, int, int, int]]:
    """解析 tag 为 (版本字符串, 四元组)。

    Args:
        tag: git tag 名，如 v3.1.0-pr.2（v 前缀可省略）。

    Returns:
        (去 v 的版本字符串, PE 四元组)；预发布序号进第四位。

    Raises:
        ValueError: tag 不符合 vX.Y.Z[-pre.N] 格式。
    """
    match = _TAG_RE.match(tag.strip())
    if not match:
        raise ValueError(f"非法版本 tag: {tag!r}（期望 vX.Y.Z 或 vX.Y.Z-pre.N）")
    major, minor, patch, pre, num = match.groups()
    version = f"{major}.{minor}.{patch}"
    quad_tail = int(num) if pre is not None else 0
    if pre is not None:
        version += f"-{pre}.{num}"
    return version, (int(major), int(minor), int(patch), quad_tail)


def _substitute_once(text: str, pattern: str, repl: str, path: Path) -> str:
    """regex 替换且强制恰好命中一次。

    Raises:
        ValueError: 命中次数不为 1（防文件结构与预期不符时静默漏改）。
    """
    new_text, count = re.subn(pattern, repl, text)
    if count != 1:
        raise ValueError(f"{path.name}: 模式 {pattern!r} 命中 {count} 次（期望 1 次）")
    return new_text


def apply_versions(
    repo_root: Path, version: str, quad: tuple[int, int, int, int]
) -> None:
    """将版本写入三处文件（就地修改）。

    Args:
        repo_root: 仓库根目录。
        version: 去 v 版本字符串，如 3.1.0-pr.2。
        quad: PE 版本四元组。
    """
    quad_str = ", ".join(str(n) for n in quad)
    dotted_quad = ".".join(str(n) for n in quad)

    init_py = repo_root / "src" / "__init__.py"
    init_py.write_text(
        _substitute_once(
            init_py.read_text(encoding="utf-8"),
            r'__version__ = "[^"]*"',
            f'__version__ = "{version}"',
            init_py,
        ),
        encoding="utf-8",
    )

    version_info = repo_root / "version_info.txt"
    vi_text = version_info.read_text(encoding="utf-8")
    vi_text = _substitute_once(
        vi_text, r"filevers=\([\d, ]+\)", f"filevers=({quad_str})", version_info
    )
    vi_text = _substitute_once(
        vi_text, r"prodvers=\([\d, ]+\)", f"prodvers=({quad_str})", version_info
    )
    vi_text = _substitute_once(
        vi_text,
        r"StringStruct\('FileVersion', '[^']*'\)",
        f"StringStruct('FileVersion', '{dotted_quad}')",
        version_info,
    )
    vi_text = _substitute_once(
        vi_text,
        r"StringStruct\('ProductVersion', '[^']*'\)",
        f"StringStruct('ProductVersion', '{version}')",
        version_info,
    )
    version_info.write_text(vi_text, encoding="utf-8")

    # installer.iss 必须保持 UTF-8 with BOM（中文注释按 ANSI 解析会乱码）
    iss = repo_root / "installer.iss"
    iss.write_text(
        _substitute_once(
            iss.read_text(encoding="utf-8-sig"),
            r'#define MyAppVersion "[^"]*"',
            f'#define MyAppVersion "{version}"',
            iss,
        ),
        encoding="utf-8-sig",
    )


def main(argv: list[str] | None = None) -> int:
    """CLI 入口：解析 tag 并就地同步三处版本号。"""
    parser = argparse.ArgumentParser(description="从 tag 同步三处版本号")
    parser.add_argument("tag", help="git tag，如 v3.1.0-pr.2")
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    args = parser.parse_args(argv)

    try:
        version, quad = parse_tag(args.tag)
        apply_versions(args.repo_root, version, quad)
    except (ValueError, OSError) as exc:
        print(f"错误: {exc}", file=sys.stderr)
        return 1
    print(f"已同步版本 {version}（四元组 {quad}）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
