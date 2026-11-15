# Keep B5 设备同步实验

Android 真机官方 Keep 9.1.120 已通过 Windows 蓝牙原型导入一条 1 km / 411 秒活动，来源显示 **“Keep 手环 B5”**，无无效标记并计入统计；重开 App 后记录和统计保留，未新增重复活动。当前是独立研究原型，没有接入主应用界面；iOS 兼容和 Windows 稳定重连尚未通过。

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

先停止旧原型。下例在**管理员 PowerShell**中运行，临时广播 `KeepB5 Lab`，广播开始后持续 600 秒：

```powershell
& $windowsPython -m experiments.keep_device.windows --model B5 --duration 600 --keep-name --state $statePath --workout $workoutPath
```

`--keep-name` 会更名并重启选定的蓝牙适配器，短暂断开电脑其他蓝牙连接；退出时恢复名称和无线电状态。若已独立确认广播名具有 `KeepB5` 前缀，可省略该参数，默认入口保留电脑当前名称。清理过程见[运行与清理契约](CONTRACT.md#运行与清理边界)。

等到日志出现 `ADVERTISING` 再操作手机。`adapter_address` 是设备信息与 state 使用的电脑适配器身份，**不是手机要输入的当前空中地址**。`--state` 和 `--workout` 独立；提供文件不会自动把设备设为已绑定。

## 4. 手机扫描与绑定

1. 用 nRF Connect 等现成扫描工具重新扫描，确认本次可连接的 `KeepB5 Lab` 和 `190a` 服务，记下当前地址。不要沿用旧扫描缓存。
2. 断开扫描工具的连接，再打开 Keep，避免两个客户端抢占通知订阅。
3. 进入 **我的 → 顶部设备图标 → 添加装备与应用 → 手动添加 Keep 智能装备 → 手环 → Keep B5 → 手动输入 MAC 地址**。
4. 输入当前扫描地址去掉冒号后的 12 位十六进制字符，核对输入框自动加空格后的全部字符。
5. 确认 Keep 明确显示“绑定成功”并进入 B5 设备页。“添加穿戴设备”的社交装备目录不是这个入口。

设备回复成功后 Keep 才提交云端绑定，失败不保证自动回滚本地 bound。不要直接删除 state 重试；恢复方法见第 7 步。

## 5. 同步单条活动

在 B5 设备页等待同步。文件目录先给出一条 SPORT44，客户端按偏移读取，每次原型最多返回 512 字节；B5 通知另受 244 字节上限约束。日志可观察 `file_transfer` 的 entries、offset、returned_length 和 status。

收到客户端收讫请求后，原型先写同目录 `<文件名>.received.json`，再隐藏待传条目；原文件保留。后续 `06/01 type44 entries=0` 表示该队列已空。**接收标记和 `FILE_REPLY_SENT` 都不能单独证明活动有效或已计入统计。**

没有期望结果时按故障层定位：

| 现象 | 检查位置 |
|---|---|
| 无 `ADVERTISING` | 默认适配器是否支持外设角色、依赖和更名/重启报错 |
| Keep 搜不到或无法连接 | 当前扫描地址、`KeepB5` 名称、蓝牙权限；先断开 nRF Connect |
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

本轮 21:00 分段修正候选通过前四项：1 km / 411 秒，统计增加 1 km、1 次和 411 秒。19:00 缺完整配速/分段、20:00 只修点配速均无效，21:00 补齐分段后有效；三组对照支持隐式零分段是本次根因。服务器阈值和全部来源规则未知，不能将单候选成功外推为任意活动兼容。

## 7. 停止与受控重连

按 Ctrl+C 或等待 `--duration` 到期，等待 `STOPPED` 和父进程清理完成，再关闭终端。`--keep-name` 路径会先等待本次子进程退出，再恢复名称并刷新广播缓存；不要强杀父进程。异常报错时用手机扫描核对实际名称，不凭退出码宣称恢复成功。

Windows 管理的空中地址可能在重新广播后变化，保存 state 不能固定它。本轮重开 App 后活动仍有效，但设备页连接失败；原型仍在却没有新订阅，未独立重抓当次地址，具体失败原因未确认。

需要重新绑定时：先在 Keep 受控解除账号的设备绑定，停止原型，再核对本地状态。若 Keep 已解绑而设备 bound 仍残留，可使用**现有**恢复入口；地址取 state 中的设备身份，不使用新扫描的空中地址：

```powershell
$deviceMac = (Get-Content -LiteralPath $statePath -Raw | ConvertFrom-Json).mac
& $windowsPython -m experiments.keep_device.state --state $statePath --address $deviceMac --reset-binding
```

该命令只重置本地 bound，保留用户配置、运动文件和接收标记，不修改云端。之后重启原型，重新扫描当前地址，再走第 4 步。多次自动重连和断线恢复后的完整再次同步尚未验收。

## 其他连接方式

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

开启客体蓝牙后，在另一个终端重新设置 `$toolPython` 和 `$workoutPath` 的完整路径，再运行原型。PORT 从当前 `%LOCALAPPDATA%/Temp/netsim.ini` 的 grpc.port 取得；多实例时核对目标。地址必须是本实验生成的合法随机静态地址，首次生成后固定复用，不能照搬真实设备身份。

```powershell
# 只在首次运行时生成；重启须使用此前保存的 $labAddress。
$labAddress = (& $toolPython -c 'from bumble.hci import Address; print(Address.generate_static_address())').Trim()
& $toolPython -m experiments.keep_device.emulator 'android-netsim:127.0.0.1:PORT' --model B5 --address $labAddress --state 'C:/path/to/private-lab/netsim-b5.json' --workout $workoutPath
```

Netsim 是虚拟无线链路，不能替代手机射频验收。官方模拟器的 Keep 曾能连接探针，但存在冷启动 MSA/OAID JNI 故障；BlueStacks 可作界面和静态分析对照，当前实例没有可用蓝牙桥。日常复现优先使用已通过的 Android 真机 + Windows 路线。

## 瓶颈、未测项与自证

| 项目 | 当前状态 |
|---|---|
| Windows 持续重连 | 未通过；空中地址受系统管理，受控重绑可继续实验 |
| iOS | nRF Connect 设备信息往返通过；官方 Keep 直接绑定/同步未通过，同账号活动显示未验收 |
| 数据覆盖 | 本次 1 km 候选有效；多公里、长时和边界输入仅离线测试 |
| 服务端契约 | 统计和重开保留已观察；独立 HTTP 重读、一般去重/阈值未知 |
| 其他固件功能 | 暂停、请求重组、ACK/PUSH、多手机、未知传感器字段尚未实现或验证，详见 CONTRACT |
| 产品交付 | 尚无一键生成/同步 UI，没有改动主应用 FIT/TCX 或配置模板 |

完整实验回归为 **389 项通过、5 个子测试通过**，由独立实验环境手动执行。现有 `pytest.ini` 的 `testpaths=tests` 不会自动发现本目录，现有 CI 的 `python -m pytest` 也不覆盖这些实验测试；必须显式指定目录。在装有 Bumble 和 pytest 的实验环境运行：

```powershell
& $toolPython -m pytest experiments/keep_device -q
```

Windows 抓包使用微软 [BTVS](https://learn.microsoft.com/en-us/windows-hardware/drivers/bluetooth/testing-btp-tools-btvs) 与 Wireshark，`-Remote off` 限本机。本次完整核验曾开启 Full Packet Logging，未开启 SSP Debug；结束后关闭本次捕获并清理本次日志覆盖设置。没有旧基线时只报告恢复默认，不能宣称精确还原原值。

Bumble 可在启动前设置 `BUMBLE_SNOOPER=pcapsnoop:file:C:/path/to/private-lab/new-capture.pcap`；父目录须存在，文件名须新建以避免覆盖。使用现成解码工具检查，文件非空不等于业务成功。日志、截图、堆快照和原始抓包仅留本机；不把真实轨迹、身份或凭据写进仓库。
