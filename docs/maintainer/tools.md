# 常用工具速查（维护者）

> 手册：[构建与打包](build.md) · [发版流程](release.md) · 工具速查

本文是维护者的工具速查表：仓库自带三个脚本（版本号同步、Release 正文提取、图标生成）各自做什么、怎么用、失败时什么表现，以及打包链路涉及的外部工具一览。需要改版本号、更新图标或排查发版失败时查这里；构建命令的完整上下文见[构建与打包](build.md)。

## 仓库脚本

### scripts/sync_version.py — tag → 三处版本号

```bash
python scripts/sync_version.py v3.1.0-pr.2
```

- **做什么**：从 git tag 生成版本号，写入 `src/__init__.py` 的 `__version__`、`version_info.txt`（PE 四元组）、`installer.iss` 的 `MyAppVersion` 三处，替代手工同步。
- **tag 语义**：`vX.Y.Z` → 四元组 `(X, Y, Z, 0)`；`vX.Y.Z-pre.N` → 第四位取 `N`（如 `3.1.0-pr.2` → `(3, 1, 0, 2)`）。v 前缀可省略。
- **参数**：`tag`（必填）；`--repo-root`（默认按脚本位置推算仓库根）。
- **失败**：tag 不合法，或目标文件结构与预期不符（替换命中次数 ≠ 1，防静默漏改）→ 退出码 1。
- **谁在用**：`release.yml` 打包前自动调用；本地构建可用它同步，或直接给 ISCC 传 `/D` 注入（见[构建与打包](build.md)步骤 3）。

### scripts/extract_changelog.py — CHANGELOG → Release 正文

```bash
python scripts/extract_changelog.py v3.1.0 --output release_notes.md
```

- **做什么**：从 `CHANGELOG.md` 提取 `## [版本号]` 段（到下一个 `## [` 标题为止），用作 GitHub Release 正文。
- **参数**：`tag`（`v` 前缀自动去掉）；`--output`（写入文件，缺省打印到 stdout）。
- **失败**：版本段不存在或内容为空 → 退出码 1。`## [未发布]` 段因不带版本号永远不会被命中。
- **谁在用**：`release.yml` 的 release job。发版前 CHANGELOG 必须有对应 `[版本]` 段，否则发版失败。

### scripts/make_icon.py — 应用图标生成

```bash
python scripts/make_icon.py                      # 程序化绘制（无设计稿时的默认模式）
python scripts/make_icon.py --source 图片.png     # 以现有图片为底：居中裁正方形、抠白底
python scripts/make_icon.py --ico-source assets/icon.ico
                                                 # 以现有 ICO 最大帧为母版重建全部尺寸
```

- **做什么**：生成 `assets/icon.ico`（Windows）与 `assets/icon.icns`（macOS Dock 图标）。
- **平台**：iconutil 仅存在于 macOS，非 darwin 平台自动跳过 icns 生成。
- **依赖**：Pillow，属开发工具依赖，**不进入运行时依赖**。
- **产物被谁引用**：`campus_running.spec`（ico/icns）与 `installer.iss`（ico）。改图标设计后重跑并提交产物。

## 外部工具链

| 工具 | 用途 | 获取 |
|------|------|------|
| PyInstaller | 桌面打包（`campus_running.spec`） | `requirements-desktop.txt`；用法见[构建与打包](build.md) |
| Inno Setup 6 | Windows 安装包（ISCC + `/D` 版本注入） | [官网](https://jrsoftware.org/isinfo.php)或 `choco install innosetup` |
| pkgbuild / ditto / iconutil | macOS PKG、zip 与 icns | 随 macOS 自带 |
| Pillow | `make_icon.py` 依赖 | 开发环境 `pip install pillow` |
| pytest | 测试（CI 每次构建与发版必跑） | `requirements.txt` |
| gh | CI 中创建 Release | 无需本地安装（CI 提供） |
