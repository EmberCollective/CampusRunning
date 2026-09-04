"""CHANGELOG 段落提取器单元测试。

被测对象: scripts/extract_changelog.py
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from extract_changelog import extract_section, main, normalize_tag  # noqa: E402

SAMPLE = """# 更新日志

## [未发布]

（新变更先积累在此段落，发布时改写为版本号并补充日期。）

## [3.0.0] - 2026-09-05

### 新增

- FIT 导出器

### 修复

- Keep 步数校验

## [2.1.1] - 2026-06-08

### 新增

- 东区操场轨迹

## [2.0.0] - 2026-05-15

### 新增

- Web 应用
"""


def test_extract_target_section():
    section = extract_section(SAMPLE, "3.0.0")
    assert "FIT 导出器" in section
    assert "Keep 步数校验" in section
    # 不包含相邻版本与未发布段的内容
    assert "东区操场轨迹" not in section
    assert "新变更先积累" not in section
    assert "Web 应用" not in section


def test_unreleased_does_not_leak():
    section = extract_section(SAMPLE, "2.1.1")
    assert "东区操场轨迹" in section
    assert "新变更先积累" not in section


def test_missing_version_raises():
    with pytest.raises(ValueError, match="9.9.9"):
        extract_section(SAMPLE, "9.9.9")


def test_no_false_prefix_match():
    # 版本 3.0.0 不得误匹配 3.0.01
    text = "## [3.0.01] - 2026-10-01\n\n内容\n"
    with pytest.raises(ValueError, match="3.0.0"):
        extract_section(text, "3.0.0")


def test_empty_section_raises():
    text = "## [1.0.0] - 2020-01-01\n\n## [2.0.0] - 2020-02-02\n\n内容\n"
    with pytest.raises(ValueError, match="内容为空"):
        extract_section(text, "1.0.0")


def test_normalize_tag():
    assert normalize_tag("v3.0.0") == "3.0.0"
    assert normalize_tag("3.0.0") == "3.0.0"
    assert normalize_tag("  v2.1.1 ") == "2.1.1"


def test_main_accepts_v_prefix(tmp_path, monkeypatch, capsys):
    changelog = tmp_path / "CHANGELOG.md"
    changelog.write_text(SAMPLE, encoding="utf-8")
    import extract_changelog as ec

    monkeypatch.setattr(ec, "CHANGELOG", changelog)
    assert ec.main(["v3.0.0"]) == 0
    assert "FIT 导出器" in capsys.readouterr().out


def test_main_exit_code_on_missing(tmp_path, monkeypatch, capsys):
    changelog = tmp_path / "CHANGELOG.md"
    changelog.write_text(SAMPLE, encoding="utf-8")
    import extract_changelog as ec

    monkeypatch.setattr(ec, "CHANGELOG", changelog)
    assert ec.main(["v9.9.9"]) == 1
    assert "9.9.9" in capsys.readouterr().err
