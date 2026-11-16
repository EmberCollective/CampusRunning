# 适配范围与环境要求

核验日期：**2026-11-16**。以下版本是本次实测基线，不表示后续最新版自动兼容。当前为独立实验原型，尚未打包为正式导入功能。

## 当前适配到哪里

| 路线 | 当前入口与广播范围 | 实测结果 | 尚未通过或未接入 |
|---|---|---|---|
| 官方 Android Emulator / Netsim | `emulator.py`，可选 `dashboard.py` 的 `/watch`；只在虚拟无线环境内广播 | Android 15 / API 35、Keep 9.1.120 完成单条有效 B5 活动、重启保留及一次自动重连；批量 44 条完整领取，列表看到本批 B5 来源记录 | 安装运行环境有 MSA 库隔离；44 条未逐条验收有效性，批量中断恢复、长期稳定及多模拟器隔离未验收 |
| Windows 实体蓝牙 → Android 真机 | `start-b5.ps1` → `launcher.py` / `windows.py`，Bless/WinRT 真实射频广播 | Android Keep 9.1.120 完成绑定、单条完整传输、有效 B5 来源活动及统计增加；一键入口完成在线解绑和退出清理 | 当前一键入口只加载一条；未接入 `/watch`，不承诺固定 MAC 或稳定自动重连 |
| Windows 实体蓝牙 → iPhone | 同一 Windows 原型 | nRF Connect 可发现、连接和完成设备信息交互 | iOS Keep 9.1.110 直接发现、绑定与同步未通过；不能作为可用路线 |
| BlueStacks | 可运行并登录 Keep | 仅应用运行对照 | 当前环境没有可用 BLE/Netsim 桥，未完成 B5 同步；ADB 连接不等于蓝牙透传 |
| 夜神（Nox） | 未形成可用入口 | 启动遇虚拟化兼容问题 | 未完成验证 |
| 其他模拟器、Linux/BlueZ、USB HCI/Bumble、bleno | 研究候选或接入方自行实现 | 无完整接入验收 | 不属于当前已支持环境 |

例如 `E2:37:46:91:48:63` 是此前 Netsim 的实验虚拟地址，附近真实手机看不到它。要让手机搜索到设备，必须使用实体广播路线；修改面板 MAC 或连接 ADB 不会把虚拟广播变成实体广播。

共享 B5 数据协议不保证发现路径相同：iOS 与 Android 的扫描、地址匹配及绑定行为需分别验收。当前没有真实 B5 原厂广播作完整对照，不把 iOS 失败归结为已经证实的单一原因。

## 官方模拟器要求

| 项目 | 本次实测配置或必要条件 |
|---|---|
| 主机 | Windows 11 专业版，build 26200；其他系统/构建未完成同等验收 |
| 模拟器 | Google 官方 Android Emulator **37.2.13.0**，build **16740729**；不是 BlueStacks 或夜神 |
| AVD | `KeepDevice35`（本次实例名，可自行命名），Google APIs **Android 15 / API 35 / x86_64**；本次兼容处理需要允许 `adb root` 的实验镜像 |
| 加速与资源 | 硬件虚拟化和 WHPX 加速正常；本次分配 **3072 MB 内存、2 核、software GPU**，这是已跑通配置，不是测出的最低要求；主机还需保留自身运行内存 |
| SDK 工具 | 本次 platform-tools 37.0.1；`adb` 用于准备和排障，Netsim 用于虚拟蓝牙 |
| 启动与连接 | 启动带 `-packet-streamer-endpoint default`；客体开启蓝牙，Keep 获附近设备权限；每次重启重新读取 `netsim.ini` 中的 `grpc.port` |
| Python | 独立 Python 3.13 环境，安装模块内 [requirements.txt](../../../experiments/keep_device/requirements.txt)：Bumble 0.0.236、grpcio 1.85.1、protobuf 7.36.2 等，以依赖文件为准 |
| 可选面板 | 另用 [requirements-dashboard.txt](../../../experiments/keep_device/requirements-dashboard.txt)；复用旧 Web 四模式，先生成，再显式载入；原子发布要求文件系统支持硬链接，本机 NTFS 已验证 |
| Keep | Android **9.1.120**，自行登录；本次需可逆隔离安装目录内的 MSA 原生库后才完成同步 |
| 蓝牙硬件 | **不需要**实体蓝牙适配器、BTVS、TShark 或 nRF Connect；虚拟广播只在 Netsim 环境内生效 |

本次启动还使用 `-accel on -gpu software -memory 3072 -cores 2 -no-snapshot -no-boot-anim -no-audio -no-window`；无窗口是当前运行方式，不是功能要求，需要登录时可显示窗口。启动、连接、批量载入命令见[模拟器运行步骤](../guides/connection-and-running.md#官方模拟器与-bumblenetsim)。

MSA 故障为安装库的 JNI 兼容问题；本次保留 APK 与签名，改名隔离安装目录中的库以触发已有回退逻辑。操作和还原条件见[MSA 可逆隔离](../guides/connection-and-running.md#api35-的-msa-启动故障与可逆隔离)。**这不是原版无干预验收**，升级或重装后不能照搬旧安装路径。无需为了本路线关闭 Hyper-V。

当前只验收单实例。多个模拟器同时运行时，`netsim.ini` 中的端口不能单独证明目标实例及无线环境已经隔离；不要仅按窗口名或不同 MAC 判断。API 34 未完成全流程，API 36 rev7 对照仍遇 MSA 崩溃，均不能替代 API 35 已测基线。

## 实体蓝牙要求

| 项目 | 要求与已测范围 |
|---|---|
| 主机与系统 | 本次 Windows 11 专业版，build 26200；使用 Windows 原生蓝牙栈 / WinRT |
| 蓝牙适配器 | 必须同时得到硬件和驱动的 **BLE Peripheral / GATT Server** 支持；仅能连接耳机、鼠标或扫描其他设备不够 |
| 已测硬件 | 本机设备管理器显示 **Realtek Bluetooth Adapter**，当前状态 OK；此证据不构成对所有 Realtek 芯片、驱动或 USB 蓝牙棒的兼容认证，尚无通用型号白名单 |
| 射频条件 | 驱动正常、外接天线正确连接（如适配器需要）；本次手机距电脑约 1 米。未测最大距离与复杂干扰环境 |
| Python 与依赖 | 独立 **Python 3.11**，按 [requirements-windows.txt](../../../experiments/keep_device/requirements-windows.txt) 安装 Bless 0.3.0、Bleak 3.1.0 等；固定 Git 提交的 pysetupdi 需要 Git。不要混装到主应用环境；早期 Bless/Python 3.13 组合有兼容问题 |
| 当前 MAC 查询 | 电脑端必须有微软 **BTVS** 与 Wireshark **TShark**；它们是当前一键入口的运行依赖，用于观察本轮实际广播 MAC |
| 权限与控制器数量 | 当前一键流程用管理员 PowerShell；地址观察按单蓝牙控制器验收。临时更名会重启适配器并短暂断开电脑其他蓝牙连接 |
| 手机 | 已登录的官方 Android Keep，本次版本 9.1.120；蓝牙开启并允许蓝牙/附近设备权限。日常无需 USB、USB 调试、nRF Connect 或系统配对 |
| 数据与并发 | 当前 Windows 一键入口单文件、一个活跃客户端；状态、SPORT44 及独立收讫标记保留在仓库外 |

Windows 管理的广播 MAC 可能每轮变化，以启动器显示的本轮有效地址为准；永久控制器地址、业务 DeviceInfo MAC 都不能替代。地址失效就停止使用旧值，需要重绑时先在 Keep 解绑，再按[受控重连步骤](../guides/connection-and-running.md#7-停止与受控重连)处理；不清除收讫标记强制重发。

本次一键入口完成完整传输及有效活动，但该轮未重新验证重开 App 持久性；此前独立 Windows 单条实验验证过记录保留，设备自动重连仍有失败。这两项不能混为“长期稳定”。BTVS 监听和退出边界见[运行说明](../guides/connection-and-running.md#瓶颈未测项与自证)，不为它开放额外远程访问。

## 抽象接口与验收边界

[`B5Transport`](../../../experiments/keep_device/transport.py) 目前是接口定义，现有 Windows / Netsim 入口尚未迁移，面板也没有任意后端切换能力。选择模拟器实例、物理控制器与隔离方式由接入方负责，具体事件和接入条件见[传输接口契约](../design/transport-interface.md)。

换模拟器、驱动、硬件或手机平台后，分别验证：广播可见 → 官方 Keep 绑定 → 文件完整读取/收讫 → B5 来源 → 活动有效和统计 → 重开保留。离线测试、连接成功及收讫标记只能证明各自阶段，不能替代后续验收。批量 44 条全部有效、批量断线恢复、多客户端及长期运行仍未验收。
