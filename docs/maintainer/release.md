# 发版流程（维护者）

> 手册：[构建与打包](build.md) · 发版流程 · [工具速查](tools.md)

本文是本仓库的发版指南：涵盖变更如何记入 CHANGELOG、打 tag、CI 自动构建，直到 GitHub Release 发布与验收的完整流程，并逐个 job 解读 `release.yml` 在做什么。适合需要发布版本的维护者；本地构建与打包细节见[构建与打包](build.md)。用 AI 编码工具（Claude Code 等）操作本仓库时，内置的 `campusrunning-release` 技能可按本流程代为执行。

## 版本号规则

- **单一来源**：`src/__init__.py` 的 `__version__`。CI 打包前自动运行 `scripts/sync_version.py <tag>` 同步三处（`src/__init__.py`、`version_info.txt`、`installer.iss`），**不要手工修改这三处版本号**——发版只需要打 tag。
- **tag 格式**：正式版 `vX.Y.Z`；预发布 `vX.Y.Z-pre.N`（pre 为字母标识，如 `-pr.1` / `-rc.1`）。预发布序号进 Windows PE 版本四元组第四位：`3.1.0-pr.1` → `(3, 1, 0, 1)`。
- **语义化版本**：不兼容变更 → 升 major；向后兼容的新功能 → 升 minor；修复 → 升 patch。

## 发版全流程（checklist）

1. **日常积累**：每个显著变更随手记入 `CHANGELOG.md` 顶部的 `## [未发布]` 段（格式遵循文件头声明的 Keep a Changelog 中文惯例）。
2. **定版本号**：按语义化版本判断本次是 X.Y.Z 哪一位升级；需要先验证再正式发时用 `-pr.N` 预发布。
3. **CHANGELOG 定稿**：把 `## [未发布]` 改为版本段。**段名必须与 tag（去 v 前缀）完全一致**——提取脚本按 `## [<版本>]` 匹配，日期后缀可有可无：正式版 `v3.2.0` → `## [3.2.0] - YYYY-MM-DD`；预发布 `v3.2.0-pr.1` → `## [3.2.0-pr.1] - YYYY-MM-DD`，正式发版时再把该段改名为 `## [3.2.0]`。日期以实际推 tag 当日为准；段落缺失或内容为空会让 CI 发版直接失败（见「常见故障」）。
4. **合入 main**：改动经 PR 合入主仓库 main（main 有分支保护，不能直接 push）。
5. **打 tag**：在**合入后的 main 提交**上打 tag 并推送到主仓库。tag 必须指向 main 上的提交，**不要打在 feature 分支上**——CI 检出的是 tag 指向的代码，打在分支上会发布未经合入的内容：

   ```bash
   git tag v3.2.0              # 预发布示例：git tag v3.2.0-pr.1
   git push <主仓库 remote> v3.2.0    # 用 git remote -v 找指向主仓库的 remote
   ```

6. **等待 CI**：`release.yml` 三个 job 全绿后 Release 自动创建（各 job 详解见下节）。只想验证构建不想发版，用「触发与干跑」。
7. **验收**：打开 Release 页面核对——
   - 6 个附件齐全：4 个产物 + 2 个 SHA256 校验文件
   - 附件显示名为英文并标注架构（如 `Windows Installer (x86_64, recommended)`）
   - 预发布版本带 Pre-release 标记
   - 正文与 CHANGELOG 版本段一致
8. **收尾**：在 `CHANGELOG.md` 顶部新开空的 `## [未发布]` 段，供下个版本积累。该编辑落在受保护的 main 上，同样经 PR 合入。

## CI 流程解读

`.github/workflows/release.yml` 共三个 job。

### 触发与干跑

- **push tag `v*`**：触发完整发版（构建 + 创建 Release）。
- **`workflow_dispatch` 干跑**：Actions 页面手动触发，不打 tag 验证双平台构建。版本号兜底为 `0.0.0-dev`，release job 自动跳过、**不创建 Release**；产物可从 Actions 页面下载检查。

### build-windows（windows-latest）

| 步骤 | 内容 |
|------|------|
| 依赖与测试 | 安装 requirements + requirements-desktop，跑 pytest |
| 版本同步 | `sync_version.py <tag>` 写三处版本号（干跑跳过） |
| 打包 | `pyinstaller campus_running.spec`（双入口 exe，便携目录） |
| 便携 zip | `Compress-Archive` 整目录压缩 |
| 安装包 | choco 装 Inno Setup，`ISCC /DMyAppVersion=<tag> installer.iss` 注入版本 |
| 校验 | 生成 `SHA256SUMS-windows.txt`（zip + 安装包） |
| 上传 | upload-artifact，供 release job 汇总 |

### build-macos（macos-15）

强制校验 runner 为原生 arm64（若 GitHub 标签改回 x64，宁可构建失败也不发架构不符的产物）→ pytest → sync_version → PyInstaller 出 `.app` → 产物验证（双 CLI 可执行、`lipo` 确认 arm64、Info.plist 引用图标、`codesign` 完好、CLI 冒烟 `--list-tracks`）→ ditto zip + pkgbuild PKG → SHA256。

> 冒烟测试用裸 COLLECT 目录的 CLI 而非 `.app` 内的：CLI 首跑会把默认配置播种到 exe 旁，在签名之后向 `.app` 添加文件会破坏资源封印，用户侧表现为 Gatekeeper「已损坏，应移到废纸篓」（v3.1.0 / v3.1.1 即受此影响）。

### release job（ubuntu-latest，仅 tag 触发）

等两个构建 job 完成后：pytest → `extract_changelog.py <tag>` 提取 CHANGELOG 版本段作为 Release 正文 → 下载双平台产物 → `gh release create` 附件与正文一步发布。

**tag 含连字符（即预发布）时自动加 `--prerelease`**，防止预发布抢占 latest 徽章。

## Release 页面规范

- **附件显示名**为英文并标注架构，由 CI 固化：

  | 附件 | 显示名 |
  |------|--------|
  | Windows 安装包 | `Windows Installer (x86_64, recommended)` |
  | Windows 便携包 | `Windows Portable (x86_64)` |
  | macOS 安装包 | `macOS Installer (arm64, recommended)` |
  | macOS 便携包 | `macOS Portable (arm64)` |
  | 校验文件 | `SHA256 Checksums (Windows x86_64)` / `SHA256 Checksums (macOS arm64)` |

- **正文 = CHANGELOG 版本段原样**，中文、保持简短。不要在 Release 页面手动编辑正文——要改内容就改 CHANGELOG 后重新打 tag。

## 常见故障

| 现象 | 原因 | 处理 |
|------|------|------|
| release job 红 | CHANGELOG 缺 `## [X.Y.Z]` 段，或段落内容为空（`extract_changelog.py` 退出码 1） | 补全版本段后删 tag 重推；若 Release 已创建，先 `gh release delete vX.Y.Z` 再重推 tag 重建 |
| push tag 后无反应 | tag 不匹配 `v*`（如打成 `3.2.0`，缺 v 前缀） | 删掉错 tag，重打 `v3.2.0` 再推 |
| Release 正文有误 | 正文从 CHANGELOG 原样提取，CHANGELOG 写错 | 修 CHANGELOG，删 Release 与 tag 后重推；不要手改正文 |
| CI 中文输出崩溃 | 历史 Windows runner 编码问题（cp1252），已在 workflow 固化 `PYTHONIOENCODING: utf-8` | 已解决；新增会输出中文的 Python 步骤时记得同样设置 |
