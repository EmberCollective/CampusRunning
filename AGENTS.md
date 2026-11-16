# 协作与仓库约定

开始工作前按任务阅读相关文档：项目入口见 [README.md](README.md)，架构与数据流见 [docs/architecture.md](docs/architecture.md)，API、轨迹和模板格式分别见 [docs/api_reference.md](docs/api_reference.md)、[docs/track_format.md](docs/track_format.md) 和 [config/templates/TEMPLATE_GUIDE.md](config/templates/TEMPLATE_GUIDE.md)。提交类型沿用 [CLAUDE.md](CLAUDE.md)；子系统若有设计文档，也要对照其约束。文档与当前代码或配置不一致时，以当前证据为准，并在 PR 中指出待同步的说明。

进行审查时，先显式阅读本文件和 [REVIEW.md](REVIEW.md)，并检查 `.agents/skills/` 下与改动直接相关的 `SKILL.md`。发现技能时跟随目录符号链接（如 `find -L`、`rg --follow`），或直接打开已知路径；只读相关技能，不要假定这些文件会自动载入或无差别加载全部技能。技能用于补充背景，其中的行为、默认值和依赖仍须对照当前代码与配置核实。

## 项目范式

- 优先复用已有模块和流程：`src/core/`、`src/planners/`、`src/exporters/`，以及 Web 端 `web/`。
- 沿用不可变数据模型（`@dataclass(frozen=True)`，`GenerationConfig` 除外）、规划器策略模式、构造注入依赖及导出器接口。
- 坐标使用项目约定的 GCJ-02；修改轨迹、模板或导出时遵守对应格式文档。

## Keep 设备适配实验

- 模块位于 `experiments/keep_device/`，与主应用的 CLI、Web 和 FIT/TCX 导出隔离；不要将实验依赖加入主应用依赖。
- 修改前阅读[连接与运行说明](experiments/keep_device/README.md)、[接口及协议契约](experiments/keep_device/CONTRACT.md)；证据与兼容性背景见 [issue #63 调研](docs/research/keep-third-party-source-63.md)。
- `history.py` 将已有、已转换为 WGS-84 的 `ExportData` 编码为 B5 SPORT44；`files.py` 管理单文件队列；`state.py` 管理绑定与配置；`windows.py` / `emulator.py` 分别复用 Bless / Bumble 提供蓝牙传输。不要再次转换坐标或另写蓝牙栈。
- `start-b5.ps1` / `launcher.py` 是 Windows 一键入口，复用 `windows_mac.py` 和电脑端 BTVS/TShark 显示本轮广播 MAC、连接应答及发送进度；通过 `windows.py --stop-file` 正常退出。手机日常只需官方 Keep，不要求 nRF 或系统配对；地址变化后走受控重绑，不承诺固定地址或长期连接。
- `emulator.py` 是独立 Bumble/Netsim 入口，不需要 BTVS/TShark 或实体蓝牙；复用同一实验静态地址、state 和接收标记，每轮读取新的 Netsim 端口。API35 在可逆隔离 MSA 安装库后已通过 B5 绑定、完整传输、设备来源、无无效标记及重启保留；这是修改安装运行环境后的单次恢复证据，不是长期稳定或 iOS 验收，操作与恢复见实验 README。
- B5 未加载运动文件时仍须回应已支持的空目录 RPC，不能因省略 `--workout` 阻断初始化；不自动清空绑定或接收标记来重试。显式 `-ResetBinding` / `--reset-binding` 仅在用户已于 Keep 解绑后重置本地 bound，保留配置与接收标记。
- 接收标记仅代表设备文件已领取，不代表活动有效；涉及协议或导入的修改须区分离线测试、真实连接、完整传输、活动来源与有效性验收。测试入口为 `python -m pytest experiments/keep_device -q`，需使用独立实验环境。
- Android Keep 9.1.120 已完成单条有效活动验收；iOS Keep、稳定重连和批量同步没有通过验收。不得把原型描述为已集成的正式导入功能。
- 2026-11-16 一键入口已通过 Android Keep 绑定、完整传输/收讫、有效活动入账、在线解绑及退出清理；本轮重开持久性未复测。后续测试改用 iPhone，其发现、绑定和同步须独立验收，不能只凭共享数据协议宣称兼容。
- 状态文件含用户配置，运动文件含轨迹。APK/DEX、抓包、日志、截图、状态和生成文件一律存仓库外私人实验目录，不提交。

## 禁止事项

- 不提交密钥、个人数据、本机配置、生成的数据文件、构建产物或审查截图；截图可放在 PR 评论中。
- 不为已有职责另造重复实现；不在任务未要求时改动外部依赖、轨迹/模板格式或导出协议。
- 不把仓库中的指导文件视为自动生效；开始审查前必须主动读取相关要求。
