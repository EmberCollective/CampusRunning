# Keep B5 设备同步实验

官方 API35 模拟器现也完成一次 B5 活动同步及重启保留对照，但需要可逆隔离 MSA 安装库；运行环境已有干预，长期稳定未通过。模拟器步骤与恢复边界见[其他连接方式](#其他连接方式)。

Android 真机官方 Keep 9.1.120 已通过 Windows 蓝牙原型导入一条 1 km / 411 秒活动，来源显示 **“Keep 手环 B5”**，无无效标记并计入统计；重开 App 后记录和统计保留，未新增重复活动。当前是独立研究原型，没有接入主应用界面；iOS 兼容和 Windows 稳定重连尚未通过。

2026-11-16 已通过 `start-b5.ps1` 完成新一轮真实验收：脚本启动、显示 MAC、仅官方 Android Keep 绑定、3306 字节完整传输及收讫、有效设备来源活动入账。随后用户在 Keep 解绑，电脑 bound 同步变为 false；正常退出并完成名称配置恢复，未遗留本轮广播或捕获进程。该轮未重新验收重开 App 后的持久性；后续测试改用 iPhone，其官方 Keep 绑定与同步仍未通过验收。

当前使用目标是**启动电脑端脚本，在官方 Keep 输入本轮 MAC，完成一轮连接和数据传输**。手机不需要 nRF Connect、USB 调试或系统蓝牙配对；下文“绑定”指 Keep 内的设备绑定。电脑仍需独立实验环境、BTVS 和 TShark。不承诺地址固定、跨重启自动重连或长期保持连接。

- **照步骤运行：**本文按 Windows 真机路线说明准备、生成、连接、同步和退出。
- **查模块、接口和格式：**[CONTRACT.md](CONTRACT.md)。
- **查证据、方案取舍和三组对照：**[issue #63 调研报告](../../docs/research/keep-third-party-source-63.md)。

```mermaid
flowchart LR
    A[GenerationEngine] -->|原有轨迹与坐标转换| B[ExportData]
    B -->|history.encode_workout| C[SPORT44 文件]
    C -->|WorkoutFiles 单文件队列| D[Windows B5 蓝牙原型]
    D -->|官方 App 绑定并读取| E[Keep 活动]
    E -->|来源 有效性 统计 重开检查| F[本次验收结果]
```

## 1. 准备环境

在仓库根目录操作。需要 Windows 支持 BLE Peripheral 的蓝牙适配器、Python 3.11、Git，以及已登录并获蓝牙权限的 Android Keep。手机与电脑通过蓝牙连接，不需要 USB；同一时刻只连接一部手机。

Windows 传输使用 [Bless](https://github.com/kevincar/bless)，独立环境不要装进主项目虚拟环境。Bless 0.3.0 在 Python 3.13 有兼容问题；依赖清单从固定 Git 提交补齐 pysetupdi，因此需要 Git。

电脑另需微软 [BTVS](https://learn.microsoft.com/en-us/windows-hardware/drivers/bluetooth/testing-btp-tools-btvs) 和 Wireshark 随附的 TShark，用于读取实际广播地址；它们是运行依赖，不只是开发时的抓包工具。下面的启动脚本不会替换蓝牙驱动或自动安装这些工具。

```powershell
$windowsEnv = Join-Path $env:TEMP 'campusrunning-keep-windows'
py -3.11 -m venv $windowsEnv
$windowsPython = Join-Path $windowsEnv 'Scripts/python.exe'
& $windowsPython -m pip install -r experiments/keep_device/requirements-windows.txt

$env:KEEP_LAB_DIR = Join-Path $env:LOCALAPPDATA 'CampusRunningKeepLab'
New-Item -ItemType Directory -Path $env:KEEP_LAB_DIR -Force | Out-Null
$statePath = Join-Path $env:KEEP_LAB_DIR 'device-b5.json'
```

`KEEP_LAB_DIR` 只用于下方示例。state 包含 Keep 下发的身体配置；运动文件、接收标记和抓包也留在该私人目录，不提交仓库。同一 state 和运动文件只能由一个原型进程使用。

## 2. 从生成流程取得 SPORT44

蓝牙入口只读取已有 SPORT44，不会自动生成，也不能直接接收 FIT、TCX 或 JSON。输入复用项目的 `ExportData`，坐标已是 WGS-84，包含原有速度和步频；编码器不再转换或平滑轨迹。

下面是可在仓库根目录运行的**临时研究脚本**：它通过 `BaseExporter.export()` 取得生成器实际传入的 `ExportData`，调用现有 `encode_workout()`。`GenerationEngine` 没有公开的 `register_exporter`；这里注入私有 `_exporters` 仅限研究进程，不是正式注册 API，也不会改变主应用导出器。

样例生成昨天 07:00 的一条实验记录，新建输出子目录并拒绝覆盖文件。它复用现有轨迹、规划和坐标转换；若已有自己的 `ExportData`，直接调用 `encode_workout(data)` 即可，无需再生成。

```powershell
@'
import os
import random
from datetime import date, timedelta
from pathlib import Path
from uuid import uuid4

from src.config_manager import ConfigManager
from src.core.models import GenerationConfig
from src.exporters.base import BaseExporter
from src.generation_engine import GenerationEngine
from experiments.keep_device.history import encode_workout
from experiments.keep_device.files import WorkoutFiles

class Sport44LabExporter(BaseExporter):
    def export(self, data, output_path):
        self.data = data
        encoded = encode_workout(data)
        with Path(output_path).open("xb") as output:
            output.write(encoded)
        return output_path

    def get_file_extension(self):
        return ".sport44"

output_dir = Path(os.environ["KEEP_LAB_DIR"]) / ("candidate-" + uuid4().hex[:8])
config = GenerationConfig(
    track_id="campus_default", min_pace=7.5, max_pace=7.5,
    start_time_min="07:00", start_time_max="07:00",
    output_dir=str(output_dir), output_format="fit",
    include_track=True, apply_correction=True,
    enable_cadence=True, enable_pace_fluctuation=True, points_per_km=50,
)
engine = GenerationEngine(ConfigManager("config"))
exporter = Sport44LabExporter()
engine._exporters["fit"] = exporter  # Research-only injection; no public registration API.
random.seed(2026111563)
result = engine.generate_single(date.today() - timedelta(days=1), 1.0, config)
workout_path = Path(result.filepath)
assert workout_path.is_file() and exporter.data.trackpoints
WorkoutFiles(workout_path)  # Validate the file without marking receipt or uploading.
print(workout_path)
print(f"{len(exporter.data.trackpoints)} GPS points, {workout_path.stat().st_size} bytes")
'@ | & $windowsPython -
```

当前样例应输出一个新 `.sport44` 路径、49 个 GPS 点和 3306 字节。生成失败时检查异常，不把空结果当成功；其他轨迹若触发分段边界拒绝，按[输入契约](CONTRACT.md#exportdata-输入单位)检查，不修改源点来凑统计。示例只作一次活动试验；后续候选应明确设置新的日期/开始时间，不通过删除接收标记重送已同步记录。

将刚打印的完整路径赋给 `$workoutPath`。不要自动选择目录里“最新文件”，以免把另一条活动交给手机。

```powershell
$workoutPath = 'C:/path/to/private-lab/candidate/2026-11-14_1.0km.sport44'
```

## 3. 启动 Windows B5

### 一键入口

在**管理员 PowerShell**中执行，工具路径替换为本机实际路径：

```powershell
& ./experiments/keep_device/start-b5.ps1 `
    -Python $windowsPython `
    -Btvs 'C:/path/to/BTP/btvs.exe' `
    -Tshark 'C:/path/to/Wireshark/tshark.exe' `
    -State $statePath `
    -Workout $workoutPath `
    -Duration 3600
```

`start-b5.ps1` 负责路径与 UTF-8 输出，调用 `launcher.py`；后者依次启动 BTVS、等待 TShark 接入、启动虚拟 B5，并在同一窗口显示本轮 MAC、订阅、业务应答及运动文件进度。使用前关闭旧实验实例和占用 BTVS 的抓包程序；端口已被占用时入口会拒绝启动，不接管其他进程。

只检查连接时可省略 `-Workout`。此时 B5 仍回应已支持的文件目录请求，目录为空；不会生成或上传活动。要发送运动文件，应在启动前明确选择 SPORT44。state 与运动文件必须位于仓库外，已存在的绑定和接收标记默认不会清空；仅在已于 Keep 解绑后，可按第 7 步显式使用 `-ResetBinding`。

等窗口显示“当前广播 MAC”和“Keep 输入”后，按第 4 步操作手机。MAC 来自 Windows 的广播配置及控制器成功响应，不以适配器身份地址代替。若地址不可用或观察中断，不继续使用旧输出。

| 窗口状态 | 能证明什么 |
|---|---|
| 蓝牙客户端已订阅 | 某个客户端订阅了通知，尚不能确认是 Keep 或已绑定 |
| 设备信息／绑定请求已应答 | 原型完成该业务回复；Keep 云端绑定仍以手机结果为准 |
| 运动文件已发送的字节数／百分比 | 已完成通知发送的文件区间，重复读取不会重复计入进度 |
| 手机已确认领取运动文件 | 客户端发来收讫；活动来源、有效性和统计仍须按第 6 步核对 |

以下独立命令保留给诊断使用；正常运行不需要逐个启动它们。

### 独立观察当前广播 MAC

手机只需官方 Keep，无需 USB 连接或安装扫描软件。电脑端复用微软 [BTVS](https://learn.microsoft.com/en-us/windows-hardware/drivers/bluetooth/testing-btp-tools-btvs) 和 Wireshark 随附的 TShark；它们不加入主应用依赖，也不修改蓝牙驱动。当前查询入口支持**单蓝牙控制器、随机地址、可连接且可扫描的传统 190a 广播**。

先停止旧原型，再启动 BTVS 的 Wireshark 模式，使用默认端口 24352 和 `-Remote off`，保持 **Full Packet Logging** 和 **Debug Mode** 关闭。当前便携版环境下，BTVS 若提示找不到自动启动的 Wireshark，关闭该提示后即可继续。TCP 捕获流必须空闲：已自动打开并连接的 Wireshark 或其他捕获程序不能与 TShark 同时占用；查询入口不接管已有捕获。

在独立终端设置实验环境的 `$windowsPython`，运行下面的观察命令；将 TShark 路径换为电脑上实际位置：

```powershell
& $windowsPython -m experiments.keep_device.windows_mac --tshark 'C:/path/to/Wireshark/tshark.exe' --duration 660
```

等 TShark 出现 `Capturing on 'TCP@127.0.0.1:24352'` 且无连接错误，再在另一个终端运行下方原型命令。**捕获须在原型开始广播前启动**，否则缺少本轮广播配置，程序不会猜测地址。

观察窗口在控制器成功启用匹配广播后输出 `AIR_MAC=... KEEP_MAC=...`；前者带冒号，后者可直接填入 Keep。它按同一广播句柄核对 190a 服务、广播属性、随机地址和成功响应，排除 Windows 的其他广播及无名称的扩展广播。停止后输出 `AIR_MAC_UNAVAILABLE reason=not-advertising`，地址变化时输出新值；多组匹配时报告歧义，不任取一个。

本入口不写抓包文件、state 或运动文件；BTVS 本身的网络监听和退出边界见文末。观察超时、连接失败或缺少配置时不宣称查询成功。地址仍受 Windows 管理，原型重启后须读取新值；稳定地址和自动重连不在本次变更范围内。

### 独立运行原型

先停止旧原型。下例在**管理员 PowerShell**中运行，临时广播 `KeepB5 Lab`，广播开始后持续 600 秒：

```powershell
& $windowsPython -m experiments.keep_device.windows --model B5 --duration 600 --keep-name --state $statePath --workout $workoutPath
```

`--keep-name` 会更名并重启选定的蓝牙适配器，短暂断开电脑其他蓝牙连接；退出时恢复名称和无线电状态。若已独立确认广播名具有 `KeepB5` 前缀，可省略该参数，默认入口保留电脑当前名称。清理过程见[运行与清理契约](CONTRACT.md#运行与清理边界)。

等到日志出现 `ADVERTISING`，且观察窗口出现本轮 `AIR_MAC` 后再操作手机。`adapter_address` 是设备信息与 state 使用的电脑适配器身份；手机输入观察窗口中的 `KEEP_MAC`。`--state` 和 `--workout` 独立；提供文件不会自动把设备设为已绑定。

## 4. 手机扫描与绑定

1. 从电脑观察窗口取得本轮 `KEEP_MAC`；确认原型仍在广播，没有后续 `AIR_MAC_UNAVAILABLE` 提示。
2. 在官方 Keep 进入 **我的 → 顶部设备图标 → 添加装备与应用 → 手动添加 Keep 智能装备 → 手环 → Keep B5 → 手动输入 MAC 地址**。
3. 输入 `KEEP_MAC` 的 12 位十六进制字符，核对输入框自动加空格后的全部字符。
4. 确认 Keep 明确显示“绑定成功”并进入 B5 设备页。“添加穿戴设备”的社交装备目录不是这个入口。

设备回复成功后 Keep 才提交云端绑定，失败不保证自动回滚本地 bound。不要直接删除 state 重试；恢复方法见第 7 步。

## 5. 同步单条活动

在 B5 设备页等待同步。文件目录先给出一条 SPORT44，客户端按偏移读取，每次原型最多返回 512 字节；B5 通知另受 244 字节上限约束。日志可观察 `file_transfer` 的 entries、offset、returned_length 和 status。

未加载运动文件时，已支持的目录请求返回空目录、读取不存在文件返回相应状态，不再因缺少 `--workout` 拒绝文件 RPC。这样仅绑定测试也能完成初始化中的目录查询；空目录不代表运动已同步。

收到客户端收讫请求后，原型先写同目录 `<文件名>.received.json`，再隐藏待传条目；原文件保留。后续 `06/01 type44 entries=0` 表示该队列已空。**接收标记和 `FILE_REPLY_SENT` 都不能单独证明活动有效或已计入统计。**

没有期望结果时按故障层定位：

| 现象 | 检查位置 |
|---|---|
| 无 `ADVERTISING` | 默认适配器是否支持外设角色、依赖和更名/重启报错 |
| Keep 搜不到或无法连接 | 本轮 `AIR_MAC`、`KeepB5` 名称、蓝牙权限；关闭其他占用通知订阅的客户端 |
| 仅绑定成功、读取不推进 | 文件是否显式加载、SIMPLE 请求/通知长度、后续 offset；不要扩大通知上限 |
| 目录为空 | 是否已有匹配的 `.received.json`；不要为重试删除已收讫标记 |
| 有活动但无效 | 按契约核对点配速与完整分段；详情配速正常不代表段字段完整 |
| state 或 receipt 校验失败 | 保留文件并检查原始输入；程序不会静默清除损坏状态 |

## 6. 验收活动与持久化

依次核对：

1. 运动列表和详情出现目标活动，来源为“Keep 手环 B5”。
2. 日期、地图、距离、时长、配速、步频符合源数据及其单位，记录无无效标记。
3. 总里程、次数和时长有相应增加，不只看设备页同步进度。
4. 重开 Keep，记录、来源和统计仍保留，没有新增重复活动。
5. 将设备重连另外记录；活动保留不代表蓝牙自动重连成功。

2026-11-15 的 21:00 分段修正候选通过前四项：1 km / 411 秒，统计增加 1 km、1 次和 411 秒。19:00 缺完整配速/分段、20:00 只修点配速均无效，21:00 补齐分段后有效；三组对照支持隐式零分段是该次无效记录的根因。服务器阈值和全部来源规则未知，不能将单候选成功外推为任意活动兼容。

2026-11-16 的新入口验收由 `start-b5.ps1` 启动 BTVS、TShark 和 B5。该轮 nRF 完全停止，手机只在官方 Android Keep 输入软件显示的 MAC 后绑定成功。3306 字节文件按最多 512 字节分块发送，窗口进度到 100% 后收到客户端收讫；设备页显示已连接、电量 80%，同步结束。活动列表出现当日新记录，1 km / 411 秒、来源“Keep 手环 B5”，无无效标记，总跑步里程和次数分别增加 1 km、1 次；详情日期、时长和步频与候选一致。电量 80% 是原型固定实验值，不是电脑电池测量。该轮尚未重开 App 核验持久性。

## 7. 停止与受控重连

按 Ctrl+C 或等待 `-Duration` 到期，等待停止和名称恢复提示，再关闭终端。启动器使用私人临时目录中的 `--stop-file` 通知 B5 正常退出，随后等待名称恢复并关闭本次 TShark/BTVS。该参数属于 `windows.py` 的进程控制接口，不需要日常手动设置；不要强杀父进程。异常报错时应核对本次进程和实际广播名称，不凭退出码宣称恢复成功。

Windows 管理的空中地址可能在重新广播后变化，保存 state 不能固定它。2026-11-15 重开 App 后活动仍有效，但设备页连接失败；原型仍在却没有新订阅，未独立重抓当次地址，不能将那一次失败直接归因为地址变化。

需要重新绑定时：先在 Keep 解除旧设备绑定，再停止旧脚本。若原型仍保留旧绑定标记，用**同一个启动脚本**加 `-ResetBinding` 重新运行；不需要另行运行状态模块：

```powershell
& ./experiments/keep_device/start-b5.ps1 `
    -Python $windowsPython `
    -Btvs 'C:/path/to/BTP/btvs.exe' `
    -Tshark 'C:/path/to/Wireshark/tshark.exe' `
    -State $statePath `
    -Workout $workoutPath `
    -ResetBinding
```

`-ResetBinding` 对应启动器的 `--reset-binding`，表示你已在 Keep 解除旧绑定；它只重置本地 bound，保留用户配置、运动文件和接收标记，不修改云端。默认启动不重置 bound。等待软件显示新 MAC 后，再走第 4 步；已收讫的同一运动文件不会因重绑再次发送。不需要安装扫描应用来取得日常使用地址，多次自动重连和断线恢复后的完整再次同步尚未验收。

### 为什么本次保留受控重绑

Android Keep 将添加时输入的 MAC 保存为重连目标，并按地址匹配扫描结果；Windows 则可能在重新广播后更换空中地址。保存设备 state 或只改 DeviceInfo 的 MAC 都不能固定这条发现路径。另一个独立问题是 Keep 已解绑、原型仍保留 bound，重新添加时会被视为已绑定；因此只在确认 Keep 已解绑后重置本地标记，不能每次启动自动清空。

这些证据不说明硬件协议随软件更新发生变化。当前选择是复用已通过的 Windows/Bless 传输，显示本轮地址并完成短期同步，不加入系统配对或固定地址驱动。系统配对试验只到手机显示配对码，电脑未出现确认，未完成且已停止，不属于使用步骤。

2026-11-16 的独立核验确认软件读取的广播 MAC 与 Android nRF 实扫地址一致；后续一键入口验收在 nRF 完全停止的情况下由官方 Android Keep 完成绑定和传输。nRF 仅用于地址对照，不是 Keep 的连接代理。旧调研中的手动扫描步骤是历史验证过程，日常流程已改为读取启动器显示的 MAC。

## 其他连接方式

### 官方模拟器与 Bumble/Netsim

2026-11-16，官方 API35 模拟器在隔离 MSA 原生库后，以原签 Keep 9.1.120 完成 B5 绑定、3306 字节 SPORT44 传输及收讫。活动显示“Keep 手环 B5”、1.00 km、6 分 51 秒，无无效标记；详情配速 6′51″/km、平均步频 162，单段数据一致。模拟器重启后原登录态和记录保留，Bumble 自动重连，已收讫文件目录为空，未观察到本轮重复记录。该过程修改了安装运行环境，且模拟器曾意外退出、原因未明；一次恢复成功不代表长期稳定或正式兼容修复。

Bumble/Netsim 路线使用独立 Python 3.13 环境和 [requirements.txt](requirements.txt)。安装后启动支持 Netsim 的现有 Android Emulator：

```powershell
$toolEnv = Join-Path $env:TEMP 'campusrunning-keep-tools'
py -3.13 -m venv $toolEnv
$toolPython = Join-Path $toolEnv 'Scripts/python.exe'
& $toolPython -m pip install -r experiments/keep_device/requirements.txt

$sdkRoot = 'C:/path/to/Android/Sdk'
$avdName = 'YourExistingAVD'
& "$sdkRoot/emulator/emulator.exe" -avd $avdName -packet-streamer-endpoint default
```

开启客体蓝牙，在模拟器内自行登录 Keep 并授予附近设备权限。在另一个终端重新设置 `$toolPython` 和 `$workoutPath` 的完整路径，再运行原型。PORT 从当前 `%LOCALAPPDATA%/Temp/netsim.ini` 的 `grpc.port` 取得；每次模拟器重启都重新读取，多实例时核对目标。地址必须是本实验生成的合法随机静态地址，首次生成后固定复用，不能照搬真实设备身份。使用独立于 Windows 入口的私人 state 和地址文件：

```powershell
$netsimLab = 'C:/path/to/private-lab'
$addressPath = Join-Path $netsimLab 'netsim-b5-address.txt'
# 仅首次生成；父目录须已存在，重启后读取同一文件。
if (-not (Test-Path -LiteralPath $addressPath)) {
    & $toolPython -c 'from bumble.hci import Address; print(Address.generate_static_address())' |
        Set-Content -LiteralPath $addressPath -Encoding ASCII
}
$labAddress = (Get-Content -LiteralPath $addressPath -Raw).Trim()
Get-Content -LiteralPath (Join-Path $env:LOCALAPPDATA 'Temp/netsim.ini')
# 将 PORT 替换为上面本轮 grpc.port；显式指定已有 SPORT44 的完整路径。
& $toolPython -m experiments.keep_device.emulator 'android-netsim:127.0.0.1:PORT' --model B5 --address $labAddress --state (Join-Path $netsimLab 'netsim-b5.json') --workout $workoutPath
```

在模拟器 Keep 的手动添加页面选择 B5，输入本轮 `ADVERTISING` 输出地址去掉冒号后的 12 位文本。`CONNECTED` 只证明链路连接；完整读取及收讫后，还需在 Keep 核对来源、有效性和详情。此入口没有 Windows 启动器的进度汇总界面，文件传输查看原型日志。停止时使用 Ctrl+C；恢复时保留 AVD userdata、同一 state、地址和 `.received.json`，重新读取 Netsim 端口后启动。已收讫文件返回空目录是正常行为，不删除标记来强制重传。

此路线不需要实体蓝牙、BTVS/TShark 或 nRF Connect，也不能替代手机射频及 iOS 验收。BlueStacks 可作界面和静态分析对照，当前实例没有可用蓝牙桥。

### API35 的 MSA 启动故障与可逆隔离

本轮原环境连续三次在 `com.bun.miitmdid.e.a()` 报 JNI 缺失并崩溃；已有 Frida 16 spawn 尝试失败且导致 `system_server` 重启，没有安装 hook。实际恢复使用 Android 自带工具：先停止目标 Keep，通过 `adb root` 进入支持 root 的实验 AVD，核对当前包安装路径及已解压的 `lib/arm64/libmsaoaidsec.so`，记录 SHA-256，再将该文件在同目录改名为 `libmsaoaidsec.so.keep-lab-disabled`，保留原文件和权限。原始路径缺库后走 Keep 已有 `MdidManager.u` 加载失败 fallback，随后可进入原登录态。本轮重启后冷启动耗时约 3916 ms。

恢复原环境时，先停止 Keep，核对备份文件哈希及原路径未被更新安装重新占用，再把该文件改回原名；不得覆盖更新后的库。重装或升级可能改变安装目录，不能复用旧路径。此操作只用于本次实验 AVD，不是实体手机的使用步骤；未修改 APK、签名或登录数据，但确实修改了安装运行环境，不能称为原版无干预验收。SDK 修复只补缺失文件并保留 userdata，无需关闭 Hyper-V。

本轮 `0e/13` 辅助运动联动状态请求仍被拒绝，约 30 秒后设置自行完成；没有据此新增猜测应答，也不能把全部等待都归因于该命令。

## 瓶颈、未测项与自证

| 项目 | 当前状态 |
|---|---|
| Windows 持续重连 | 未通过，不是当前短期同步入口的承诺；地址变化后受控重绑 |
| 一键入口 | 地址对照、Android Keep 绑定、3306 字节传输/收讫、有效活动入账、在线解绑与退出清理通过；本轮未复测重开持久性，iPhone 待验收 |
| API35 / Netsim | MSA 库隔离后绑定、完整传输/收讫、设备来源、无无效标记及重启保留通过；一次自动重连并返回空目录，长期稳定未验收，曾意外退出 |
| iOS | nRF Connect 设备信息往返通过；官方 Keep 直接绑定/同步未通过，同账号活动显示未验收 |
| 数据覆盖 | 本次 1 km 候选有效；多公里、长时和边界输入仅离线测试 |
| 服务端契约 | 统计和重开保留已观察；独立 HTTP 重读、一般去重/阈值未知 |
| 其他固件功能 | 暂停、请求重组、ACK/PUSH、多手机、未知传感器字段尚未实现或验证，详见 CONTRACT |
| 产品交付 | 尚无一键生成/同步 UI，没有改动主应用 FIT/TCX 或配置模板 |

包含显式重绑恢复参数及启动诊断修复的完整回归为 **431 项通过、5 个子测试通过**。离线检查、真实绑定、文件收讫和有效活动入账分别验收，不能互相替代。现有 `pytest.ini` 的 `testpaths=tests` 不会自动发现本目录，现有 CI 的 `python -m pytest` 也不覆盖这些实验测试；修改后必须显式运行完整目录。在装有 Bumble 和 pytest 的实验环境运行：

```powershell
& $toolPython -m pytest experiments/keep_device -q
```

Windows 抓包使用微软 [BTVS](https://learn.microsoft.com/en-us/windows-hardware/drivers/bluetooth/testing-btp-tools-btvs) 与 Wireshark。独立诊断示例的 `-Remote off` 会尝试启动本机 Wireshark；启动器使用 `-Remote on` 避免额外启动图形客户端，再让本次 TShark 接入。两种参数都**不保证 TCP 仅监听本机接口**；本次观察到 BTVS 监听全部接口，而查询入口只连接 `127.0.0.1`。保持现有防火墙限制，不为查询开放远程访问，结束后关闭本次观察进程和 BTVS。MAC 查询不需要 Full Packet Logging 或 SSP Debug；早前完整活动核验曾开启 Full Packet Logging 并在结束后清理覆盖设置，没有旧基线时只报告恢复默认，不能宣称精确还原原值。

固定地址的现成项目与环境成本见[独立调研](../../docs/research/keep-b5-mac-stability.md)；当前优先保留 Windows/Bless，显示本轮实际地址。

Bumble 可在启动前设置 `BUMBLE_SNOOPER=pcapsnoop:file:C:/path/to/private-lab/new-capture.pcap`；父目录须存在，文件名须新建以避免覆盖。使用现成解码工具检查，文件非空不等于业务成功。日志、截图、堆快照和原始抓包仅留本机；不把真实轨迹、身份或凭据写进仓库。
