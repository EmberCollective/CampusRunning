# CLAUDE.md - 校园跑步数据生成器

## 项目类型
- Python CLI + Flask Web 应用
- 跑步轨迹数据生成器 (TCX格式)

## 技术栈
- Python 3.13+
- Flask
- garmin-fit-sdk（FIT 导出，Keep 导入必需；`pip install garmin-fit-sdk`）

## 关键命令

### 运行
```bash
python main.py --help
python app.py
```

### 开发
- Web 服务器: `python app.py` (默认 0.0.0.0:5000)
- CLI: `python main.py <command>`

## 目录结构
- `src/core/` - 核心模块（轨迹生成、配速波动、坐标修正）
- `src/planners/` - 规划策略
- `src/exporters/` - 导出器
- `web/` - Flask Web 应用
- `config/` - 配置文件
- `experiments/keep_device/` - 独立 Keep B3/B5 蓝牙设备适配实验（不接入主 CLI/Web）

## Keep 设备适配模块

分类入口见 [Keep B5 文档](docs/keep-b5/README.md)，具体模拟器、硬件及依赖要求见[适配范围](docs/keep-b5/reference/compatibility.md)。完整流程见[连接与运行](docs/keep-b5/guides/connection-and-running.md)，Python 接口、蓝牙命令、文件布局及单位见[协议契约](docs/keep-b5/reference/protocol-contract.md)，研究证据见 [issue #63 调研](docs/keep-b5/research/third-party-source-63.md)。

| 模块 | 职责 |
|------|------|
| `transport.py` / [传输接口契约](docs/keep-b5/design/transport-interface.md) | 可替换蓝牙接口及生命周期契约；当前仅定义，现有运行入口尚未迁移 |
| `history.py` | `encode_workout(ExportData) -> bytes`，编码 SPORT44；输入坐标已是 WGS-84 |
| `exporter.py` | 原生 `B5Exporter`，构造注入旧引擎，严格摘要校验、原子发布与拒覆盖 |
| `dashboard.py` / `templates/watch.html` | 复用旧 Web 四模式，提供可选手表管理面板、固定清单/里程、MAC 和真实连接状态；仅本机运行 |
| `files.py` | 单文件或固定批量目录，按 UUID 读取与逐文件持久接收标记；保留源文件 |
| `state.py` | 设备绑定、解绑、配置及查询应答 |
| `btcp.py` / `simple.py` | B3/B5 会话与帧、CRC、B5 通知分片 |
| `protocol.py` / `emulator.py` | Bumble 服务及 Android Netsim 实验入口 |
| `windows.py` | Bless/WinRT 实体蓝牙入口与临时名称恢复 |
| `windows_mac.py` | 复用 BTVS/TShark 观察本轮实际广播 MAC |
| `launcher.py` / `start-b5.ps1` | Windows 一键启动、地址/订阅/业务应答/传输进度显示；通过 `--stop-file` 通知原型正常退出 |

独立环境中运行 `python -m pytest experiments/keep_device -q`；Windows 蓝牙环境使用 Python 3.11 和模块内 `requirements-windows.txt`，Bumble/测试环境依赖见模块内 `requirements.txt`。不得混入主应用环境。

可选面板依赖见 `requirements-dashboard.txt`。`GenerationEngine(config_manager, exporters=None, strict=False)` 保留默认流程；面板注入 B5 并严格失败。主应用不导入实验包，四模式不另写一套。面板中生成、预览不上传，显式“载入并开始同步”才切换本面板拥有的广播；不得把连接或收讫当作活动有效性。

模拟器 `emulator.py` 与 Windows `launcher.py` / `windows.py` 的 `--workout-dir` 在启动时固定 1–64 条 SPORT44、总计最多 64 MiB，与单文件参数互斥；PowerShell 包装入口保持单文件。面板可保存两条路线的连接配置，Windows 使用独立 Python 3.11 和设备状态，通过只读检查后才能启动；面板接入的手机联调和 Windows 批量传输尚未验收。2026-11-16 模拟器已确认 Android Keep 领取 44/44 条，且运动列表显示本批 B5 来源记录；未逐条验收全部活动有效性或批量中断恢复。每文件保留独立收讫标记，重启不重发已领取记录。

已在 Android Keep 9.1.120 验证 B5 绑定、完整文件传输、设备来源及有效活动入账。Windows 自动重连仍不稳定，iOS Keep 尚未通过；文件领取成功不能代替活动有效性验收。所有账号配置、生成记录与研究原始材料留在仓库外。

当前使用流程为启动脚本、在官方 Keep 输入软件显示的本轮 MAC、完成短期同步；手机不需 nRF、USB 调试或系统配对。电脑需 BTVS/TShark 与独立 Windows 实验环境。地址变化后先于 Keep 解绑，再用同一脚本的 `-ResetBinding` 显式恢复本地绑定标记；默认不清空 bound，恢复也保留配置与接收标记。不承诺固定 MAC 或稳定长连。未加载运动文件的 B5 也要响应已支持的空目录查询。

2026-11-16 一键入口已在 nRF 停止的条件下通过官方 Android Keep 绑定、3306 字节完整传输/收讫、有效“Keep 手环 B5”来源活动及统计增加。在线解绑同步本地 bound=false，退出完成名称配置恢复且无本轮进程残留。本轮未复测重开 App 持久性；后续测试改用 iPhone，不能把共享 B5 数据协议视为其发现、绑定和同步已通过验收。

模拟器使用独立 `emulator.py` / Bumble / Netsim 入口，不需要 Windows 的 BTVS/TShark 或实体蓝牙。固定复用实验静态地址、state 和接收标记，每轮读取 Netsim 当前端口。2026-11-16 API35 在可逆隔离 MSA 安装库后完成 B5 绑定、传输/收讫、设备来源及无无效标记验收，重启后记录保留并自动重连；APK 与签名未改，但安装运行环境有干预。长期稳定及 iOS 未通过，隔离和恢复步骤见连接与运行说明。

## Commit 规范

| Type | 含义 | 使用场景 |
|------|------|----------|
| `feat` | 新功能 | 新增功能、模块、API端点 |
| `core` | 核心模块变更 | track_generator, pace_fluctuator 等核心算法 |
| `fix` | 修复 | Bug 修复 |
| `web` | Web应用变更 | web/ 目录下的变更 |
| `refactor` | 重构 | 代码重构（不改变功能） |
| `docs` | 文档 | 文档更新 |
| `test` | 测试 | 测试相关 |
| `chore` | 杂项 | 配置、构建、依赖更新 |

## 关键约定
- 不可变数据模型 (`@dataclass(frozen=True)`)
- 策略模式 (planners)
- 依赖注入 (TrackGenerator)

## 坐标系说明

轨迹配置使用**高德坐标系（GCJ-02）**；FIT/TCX 导出前系统会自动逐点转换为 WGS-84。旧版 `coordinate_correction` 仅作兼容读取，不参与转换。

添加新轨迹时，只需填入高德坐标的实际值，无需手动计算偏移。
