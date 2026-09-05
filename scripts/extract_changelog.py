#!/usr/bin/env python3
"""从 CHANGELOG.md 提取指定版本段落，用作 GitHub Release 正文。

用法:
    python scripts/extract_changelog.py <tag> [--output FILE]

tag 形如 v3.0.0 或 3.0.0（自动去掉 v 前缀）。段落为
"## [版本号]" 标题行到下一个 "## [" 标题行之间的内容；
顶部 "## [未发布]" 段因不带版本号而永远不会被命中。
找不到版本段或段落为空时，向 stderr 输出错误并以退出码 1 结束。
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

CHANGELOG = Path(__file__).resolve().parent.parent / "CHANGELOG.md"


def normalize_tag(tag: str) -> str:
    """'v3.0.0' -> '3.0.0'（不带前缀的保持原样）。"""
    return tag.strip().removeprefix("v")


def extract_section(text: str, version: str) -> str:
    """返回 text 中 [version] 段落内容（不含本段标题与下一段标题）。

    Raises:
        ValueError: 版本段不存在，或段落内容为空。
    """
    pattern = re.compile(rf"^## \[{re.escape(version)}\](\s|$)")
    lines = text.splitlines()
    start = None
    for i, line in enumerate(lines):
        if pattern.match(line):
            start = i + 1
            break
    if start is None:
        raise ValueError(f"CHANGELOG 中未找到版本段 [{version}]")
    body: list[str] = []
    for line in lines[start:]:
        if line.startswith("## ["):
            break
        body.append(line)
    section = "\n".join(body).strip()
    if not section:
        raise ValueError(f"版本段 [{version}] 内容为空")
    return section


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="从 CHANGELOG.md 提取指定版本段落",
    )
    parser.add_argument("tag", help="git tag 名，如 v3.0.0")
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="写入指定文件而非 stdout",
    )
    args = parser.parse_args(argv)

    try:
        section = extract_section(
            CHANGELOG.read_text(encoding="utf-8"), normalize_tag(args.tag)
        )
        if args.output is not None:
            args.output.write_text(section + "\n", encoding="utf-8")
        else:
            print(section)
    except (OSError, ValueError) as exc:
        print(f"错误: {exc}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
