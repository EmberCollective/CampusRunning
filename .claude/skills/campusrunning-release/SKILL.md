---
name: campusrunning-release
description: >-
    Release playbook for the CampusRunning repo: how to cut a version, write
    CHANGELOG.md, tag main, and let release.yml build and publish the GitHub
    Release. Use this skill whenever the user wants to 发版 / 发布新版本 /
    打个版本 / 打 tag / release / 出一个新版本 / 预发布 / 发布预览版, asks how
    releases work or what CI does on tag push, wants to 更新 CHANGELOG /
    写更新日志 / 记录变更, or hits a failed release workflow — even if they
    never say "发版" (e.g. "把这次的改动发出去"). Do NOT use for generating
    running data (that is campusrunning-cli) or local packaging questions
    (see docs/maintainer/build.md).
---

# campusrunning-release — 发版规程

> 事实来源：`.github/workflows/release.yml`、`scripts/sync_version.py`、`scripts/extract_changelog.py`、CHANGELOG.md 历史版本 + 实际发版经验（2026-11）。
> 人类向全景文档：[docs/maintainer/release.md](../../../docs/maintainer/release.md)。

## 硬规则（先读这个）

1. **授权前置**：push 分支、push tag、`gh release` 等外向动作，必须先向用户说明将执行什么并获得明确同意，不自主发版。
2. **tag 只打在 main 上**：tag 必须指向已合入主仓库（EmberCollective/CampusRunning）main 的提交，**不打 feature 分支**——CI 检出 tag 指向的代码，打在分支上会发布未经合入的内容。tag 推送到主仓库 remote（用 `git remote -v` 找指向 EmberCollective/CampusRunning 的那个）。
3. **禁止手动创建或编辑 Release**：正文由 CI 运行 `extract_changelog.py` 从 CHANGELOG 版本段**原样**提取。永远不要 `gh release create`、不要在 Release 页面手改 notes。正文有误 → 改 CHANGELOG → 删 Release（若已建）→ 删 tag → 重推 tag。
4. **禁止手工改版本号三处**（`src/__init__.py`、`version_info.txt`、`installer.iss`）：CI 打包前 `sync_version.py <tag>` 自动同步，发版只需要打 tag。
5. **CHANGELOG 是 Release 正文的唯一来源**：措辞会被原样发布，写错就是发错（曾有范围描述不实被 code review 抓出）。

## 发版流程

按序执行；每步的外向动作（push）都先过用户授权。

1. **确认待发内容**：`git log` 对比上次 tag；CI（pytest）应为绿。
2. **定版本号**：语义化版本——不兼容变更升 major，新功能升 minor，修复升 patch。先验证再正式发用预发布 `vX.Y.Z-pr.N`。
3. **CHANGELOG 定稿**：把 `## [未发布]` 段改为版本段。**段名必须与 tag（去 v）完全一致**——提取脚本按 `## [<tag>]` 匹配，日期后缀可有可无：
   - 正式版 `v3.2.0` → `## [3.2.0] - YYYY-MM-DD`
   - 预发布 `v3.2.0-pr.1` → `## [3.2.0-pr.1] - YYYY-MM-DD`；后续正式发版时把该段改名为 `## [3.2.0]`（内容可扩充）
   - 日期以实际推 tag 当日为准；段落缺失或为空会让 CI 发版直接失败。
4. **合入 main**：改动经 PR 合入主仓库 main（main 有分支保护，不能直接 push）。
5. **打 tag 并推送主仓库**（在 main 最新提交上）：
   ```bash
   git tag v3.2.0            # 预发布：git tag v3.2.0-pr.1
   git push <主仓库 remote> v3.2.0
   ```
6. **报告 CI 进展**：release.yml 三 job（build-windows / build-macos / release），tag 含连字符自动 `--prerelease`。只想验证构建不想发版：Actions 页 workflow_dispatch 干跑（版本兜底 0.0.0-dev，不建 Release）。
7. **验收 Release**：6 附件（4 产物 + 2 SHA256）、英文显示名带架构标注、预发布带 Pre-release 标记、正文与 CHANGELOG 段一致。
8. **收尾**：CHANGELOG 顶部新开空的 `## [未发布]` 段。该编辑落在受保护的 main 上，同样走 PR 合入（push 前过授权）。

## CHANGELOG 风格规范

- 格式：Keep a Changelog（中文）+ 语义化版本，文件头已声明。
- **中文段名，固定顺序：`新增` → `变更` → `修复`**。（历史 3.1.2 用过英文段名 Feat/Bugfix/Change，属偏差，不再使用。）
- 版本段首一句主题概括本版内容（近版本惯例）。
- 每条变更：
  - 动词开头，写「做了什么 + 对用户的效果/原因」，具体但不冗长；
  - **只写真实发生的变更，不夸大范围**——正文会被原样发布到 Release 页；
  - 有关联 PR/issue 附编号，如 `(#57)`；
  - 技术细节适度：用户可感知的行为放前面，实现手段放后面。
- 日常新变更随手积累在顶部 `## [未发布]` 段，发版时才定稿成版本段。

**条目示例**（摘自 CHANGELOG 3.1.1，供对齐语感）：

> - 预设模板选中后无反应：5 个内置模板迁移到分模式格式（选中后切换生成模式并应用参数），同时保留 generation_config 节兼容 CLI --template (#44)

## CI 会自动做什么

| Job | 一句话 |
|-----|--------|
| build-windows | pytest → sync_version → PyInstaller → 便携 zip → Inno Setup 安装包（/D 注入版本）→ SHA256 |
| build-macos | arm64 强制校验 → pytest → sync_version → PyInstaller .app → 架构/签名/图标/CLI 冒烟验证 → zip + PKG → SHA256 |
| release（仅 tag 触发） | pytest → extract_changelog 生成正文 → 下载双平台产物 → `gh release create`（tag 含连字符自动 `--prerelease`） |

细节与产物清单见 [docs/maintainer/release.md](../../../docs/maintainer/release.md)。

## 故障对照表

| 现象 | 原因 | 处理 |
|------|------|------|
| release job 红 | CHANGELOG 缺 `## [X.Y.Z]` 段或段落为空 | 补段 → 删 tag 重推；Release 已建先 `gh release delete` |
| push tag 后 CI 无反应 | tag 缺 v 前缀（`3.2.0` 不匹配 `v*`） | 删错 tag，重打 `v3.2.0` 再推 |
| Release 正文有误 | 正文 = CHANGELOG 段原样 | 改 CHANGELOG，删 Release 与 tag 后重推；**不手改正文** |
| 版本号三处不一致 | 有人手工改过 | 交给 CI：下个 tag 自动同步回来；本地可跑 `sync_version.py <tag>` 校正 |
