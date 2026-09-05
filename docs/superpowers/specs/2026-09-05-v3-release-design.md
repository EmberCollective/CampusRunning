# v3.0.0 发布准备设计文档

- 日期：2026-09-05
- 分支：`release/v3.0.0`（基于 `main` @ `8eebf49`，即 PR #10 合并后）
- 状态：待用户审阅

## 背景

PR #10（FIT 导出器 + 步频/步数生成）已合并 main，默认输出格式从 TCX 变更为 FIT——对使用者是破坏性变更，据此发布 **v3.0.0**。发布需要补齐三块缺失内容：

1. CHANGELOG（项目从未有过）
2. CI 与打 tag 自动 release（仓库无 `.github/` 目录、无任何 GitHub Release）
3. README 重构（Web 优先详写，CLI 一笔带过，突出 Agent Skill）

已确认的决策：

- 方案 A（自研提取脚本），不用第三方 changelog action，不做 semantic-release
- tag 统一 `v` 前缀（`v3.0.0`）；历史 tag `2.1.0`/`2.1.1` 不带前缀，不影响新触发规则
- CHANGELOG 全中文，Keep a Changelog 1.1 格式，顶部保留 `[未发布]` 段
- README Web 部分配真实界面截图（browser-use 自动化截取，存 `assets/readme/`）
- 新增 `requirements.txt`（CI 安装依赖用）
- 发布内容在 `release/v3.0.0` 分支完成，走一个 PR 合入 main，之后打 tag 触发 release

## 目标

- CHANGELOG.md 全量补齐 v1.0.0 → v3.0.0 五个版本
- push/PR 自动跑测试；push tag `v*` 自动创建 GitHub Release，正文为 CHANGELOG 对应版本段
- README「快速开始」Web 前置详写、CLI 压缩、Agent Skill 独立成段
- 提取脚本自身有测试覆盖

## 非目标

- 不做 PyPI 打包、不做语义化提交强制校验、不做多 OS 测试矩阵
- 不重发历史版本的 Release（2.1.0/2.1.1 不补）
- 不改动任何业务代码（src/、web/、main.py 等一概不动）

## 设计

### 1. CHANGELOG.md

位置：仓库根。结构如下（完整草稿见附录 A）：

```markdown
# 更新日志

本项目所有显著变更记录于此。格式遵循 Keep a Changelog，
版本遵循语义化版本（SemVer）。

## [未发布]

（当前无未发布变更；新变更先积累在此，发布时改写为版本号段落。）

## [3.0.0] - 2026-09-05

### 新增
- …
### 变更
- …
### 修复
- …

## [2.1.1] - 2026-06-08
…
## [2.1.0] - 2026-05-28
…
## [2.0.0] - 2026-05-15
…
## [1.0.0] - 2025-12-05
…
```

版本段落规则：

- 标题格式 `## [版本号] - YYYY-MM-DD`，tag 名与版本号一一对应（`v3.0.0` ↔ `[3.0.0]`）
- 子分组用 `### 新增` / `### 变更` / `### 修复` / `### 文档`，组内无内容则省略该组
- `[未发布]` 段固定保留在顶部；提取脚本只匹配带版本号的段落，天然忽略它
- 版本归组按内容逻辑而非严格 tag 边界：`7eb4f87`（发布 2.0.0 重构版本）与 `78631ab` 归入 [2.0.0]，尽管 tag `v2.0.0` 打点在它们之前

### 2. CI 与自动 release

#### 2.1 `requirements.txt`（新建）

```
flask
garmin-fit-sdk
pytest
```

不锁版本（项目无任何锁文件惯例；CI 出问题再钉）。运行依赖与开发依赖合一个文件——项目体量小，拆分无收益。

#### 2.2 `.github/workflows/ci.yml`（新建）

```yaml
name: CI
on:
  push:
    branches: [main]
  pull_request:
    branches: [main]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.13"
          cache: pip
      - run: pip install -r requirements.txt
      - run: python -m pytest
```

单 OS（ubuntu）单版本（3.13）：42 个纯逻辑测试、0.2s 跑完，Windows 矩阵只拖慢不增信。

#### 2.3 `.github/workflows/release.yml`（新建）

```yaml
name: Release
on:
  push:
    tags: ["v*"]

permissions:
  contents: write

jobs:
  release:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.13"
          cache: pip
      - run: pip install -r requirements.txt
      - run: python -m pytest                      # 发布前再验一次
      - run: python scripts/extract_changelog.py "${GITHUB_REF_NAME}" --output release_notes.md
      - env:
          GH_TOKEN: ${{ secrets.GITHUB_TOKEN }}
        run: gh release create "${GITHUB_REF_NAME}" --title "${GITHUB_REF_NAME}" --notes-file release_notes.md
```

默认 `GITHUB_TOKEN` 即可创建 Release（`contents: write` 已声明）。

#### 2.4 `scripts/extract_changelog.py`（新建，约 40 行）

接口：

```
python scripts/extract_changelog.py <tag> [--output FILE]
```

- `<tag>` 形如 `v3.0.0`；脚本同时接受 `3.0.0`（去前缀归一）
- 在 `CHANGELOG.md` 中定位 `## [3.0.0]` 行，截取到下一个 `## [` 行（不含）为止
- trim 首尾空白后输出到 stdout 或 `--output` 文件
- 版本段不存在、或段落为空 → 打印明确错误到 stderr、退出码 1（workflow 立即红，不会发出空正文 Release）

#### 2.5 `tests/test_extract_changelog.py`（新建）

用例（pytest，tmp_path 造临时 CHANGELOG）：

1. 提取命中：多版本文件中截取目标段，内容精确
2. tag 带/不带 `v` 前缀均可命中
3. 版本不存在 → SystemExit(1) 且 stderr 有版本号
4. 段落为空（两个版本标题相邻）→ SystemExit(1)
5. 提取 `[未发布]` 之下的第一个版本段不受未发布段干扰

### 3. README 重构（Web 优先）

只动「快速开始」及其相邻小节，其余保持。

调整后的快速开始结构：

```
## 快速开始
├── 安装：pip install flask garmin-fit-sdk（合并为一个代码块，CLI/Web 共用）
├── ### Web（推荐，详写）
│   ├── 启动：python app.py → http://127.0.0.1:5000
│   ├── 截图两张（见「Web 截图」小节）：工作台首页、轨迹编辑器
│   └── 功能展开（各 1-2 句）：
│       ├── 三种模式（daily/total/single）表单化操作，指定日期批量生成
│       ├── 模板：表单填好 → 导出/应用，一键复用
│       ├── 轨迹编辑器：高德地图标点、画笔绘制、实时环线距离，保存即入 config/tracks/
│       └── 结果一键 ZIP 下载
├── ### CLI（一笔带过）
│   ├── 3 条示例：single 验证 / daily 整月 / --template+--zip 组合
│   └── 「完整参数见 API 参考」链接
└── ### 让 AI 替你跑（Agent Skill，独立小节）
    └── 现 README 第 64 行段落原样迁出并稍作强化：
        提到 .claude/skills/campusrunning-cli/，示例指令一句
```

其余修订点：

- 「它能做什么」四层真实感机制 → 五层，新增**真实步频/步数**（#8 能力，现版未提）

#### Web 截图（实施时生成）

| 文件 | 内容 | README 位置 |
|------|------|-------------|
| `assets/readme/web_workbench.png` | 工作台首页：表单默认状态 | Web 小节启动命令之后 |
| `assets/readme/track_editor.png` | 轨迹编辑器：Leaflet 地图 + 画笔工具栏 + 一条已绘制的操场环线 | 「添加轨迹」方式一（推荐）处 |

截图流程（browser-use 自动化）：

1. `python app.py` 启动（127.0.0.1:5000）
2. 首页：视口 1600×1000 直接截图
3. 轨迹编辑器：进入编辑器页 → 用画笔沿操场点若干点画出环线（左侧工具栏可见、右侧实时距离读数有值）→ 截图
4. 保存至 `assets/readme/`，README 以 `<img>` 引用并设 `width="100%"`

可行性已验证：轨迹编辑器默认 Leaflet 档**无需高德 Key** 即可显示地图与绘制；官方高德档（需 Key）仅作可选增强，截图用 Leaflet 档即可。
- 「文档」列表追加 CHANGELOG 链接
- hero SVG、免责声明、「天下苦校园跑久矣」、配置节、项目结构表：不动

## 测试计划

- `python -m pytest`：现有 42 + 新增 ~5（提取脚本）全部通过
- 两张截图人工核对：画面完整（地图/表单/工具栏可见）、无遮挡、尺寸合理
- `python scripts/extract_changelog.py v3.0.0` 手工验证输出
- `python -m py_compile app.py main.py`：确认 README 之外的文件未被误改（防御性检查）
- CI 上绿 → 打 tag → 验证自动 Release 正文与 CHANGELOG 段落一致

## 发布流程（实施完成后的操作序列）

1. PR 合入 main（本分支全部工作）
2. `git tag v3.0.0 && git push origin v3.0.0`
3. Release workflow 自动：pytest → 提取 `[3.0.0]` 段 → 创建 GitHub Release
4. 人工核对 Release 页面

## 风险与备注

- 旧 tag（`2.1.0`、`2.1.1`）不带 `v` 前缀，不匹配 `v*` 触发模式——无需处理，也不重发历史 Release
- CHANGELOG 历史版本条目由 git log 提炼，日期取 tag 指向提交的提交日期；如与实际发布日有出入，以用户复核为准
- requirements.txt 不锁版本，若 garmin-fit-sdk 未来大版本破坏 API，CI 会第一时间红——届时再钉版本

## 附录 A：CHANGELOG.md 完整草稿

```markdown
# 更新日志

本项目所有显著变更记录于此。格式遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，
版本遵循[语义化版本](https://semver.org/lang/zh-CN/)。

## [未发布]

（当前无未发布变更；新变更先积累在此，发布时改写为版本号段落。）

## [3.0.0] - 2026-09-05

### 新增

- FIT 导出器：基于 garmin-fit-sdk 输出含完整步频/步数数据流的 FIT 文件 (#8, #10)
- 步频/步数自动生成：按配速与里程生成符合真实分布的步频曲线，TCX 导出同步写入 (#8)
- Web 轨迹编辑器：高德地图标点与画笔绘制、橡皮擦、撤销/重做、z20 深度缩放，保存即入轨迹库 (#3)
- Web 前端重构为专业工作台风格 (#7)
- 指定日期批量生成（CLI 与 Web UI） (#9)
- 内置 campusrunning-cli Agent Skill，AI 编码工具对话式直接调用 (#6)
- 新增东区南操场轨迹
- 项目采用 MIT License

### 变更

- **默认输出格式从 TCX 改为 FIT**：Keep 导入推荐 FIT（含步频/步数）；需要 TCX 时加 `--format tcx` (#8, #10)

### 修复

- Keep 导入时步数/步幅校验不通过的问题 (#8)
- 指定日期批量生成的阻断问题（code review 发现） (#9)

## [2.1.1] - 2026-06-08

### 新增

- 东区操场轨迹

### 变更

- 最早/最晚开始时间的粒度从小时精确到分钟

### 修复

- issue #1：部分情况下不能正确生成文件的问题

## [2.1.0] - 2026-05-28

### 新增

- TimeRangePlanner 时间范围规划器
- 时间间歇跑、时间跑两类预设模板
- 西一区操场轨迹

## [2.0.0] - 2026-05-15

### 新增

- Flask Web 应用：表单化操作，与 CLI 生成结果一致
- 配速波动机制：热身 → 稳定 → 疲劳 → 冲刺四阶段，拒绝匀速直线

### 变更

- CLI 入口重构为子命令形式（daily / total / single）

## [1.0.0] - 2025-12-05

### 新增

- 首个版本：三种生成模式（每日范围 / 总公里数 / 单文件）
- 基于操场坐标的顺时针 GPS 轨迹生成与 GCJ-02 坐标修正
- 轨迹库与预设模板系统
- TCX 导出
```
