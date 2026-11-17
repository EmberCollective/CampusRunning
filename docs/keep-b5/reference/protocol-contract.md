# Keep 设备实验接口与数据契约

本文描述当前代码的输入、输出和边界；操作步骤见[连接与运行](../guides/connection-and-running.md)，环境及已测范围见[兼容性说明](compatibility.md)，逆向方法、版本、三组活动对照及原始证据说明见[调研报告](../research/third-party-source-63.md)。它不是 Keep 官方协议或完整固件规范。真机接受范围限定 Android Keep 9.1.120 的本次 B5、1 km 候选。

## 模块与 Python 接口

### 扫码连接

`GET /api/watch/binding-qr?mac=<12位地址>` 返回 PNG，仅接受与当前已确认广播地址一致的参数。停止、未就绪、正在操作、地址未知或不匹配返回 409；所有响应设置 `Cache-Control: no-store`。接口不接受任意二维码内容，不使用业务身份 MAC 代替广播地址，不修改绑定状态。

载荷采用 Android Keep 9.1.120 已恢复的解析契约：`keep://kitbit/bindInfo?mac=<12位MAC>&type=B5`。扫码处理器从 query 读取 `mac` 与大写 `type=B5`，地址不带冒号。二维码仅替代地址输入；解析成功不代表蓝牙发现、绑定或活动同步成功。当前已有用户扫码识别证据，完整扫码绑定未通过验收，不能据此宣称修复既有连接问题或兼容 iOS。

可替换传输接口的设计见[传输接口契约](../design/transport-interface.md)，纯标准库类型位于 [transport.py](../../../experiments/keep_device/transport.py)。现有后端尚未迁移；面板直接复用 Netsim 和 Windows 入口，不表示任意后端或多实例支持已经完成。

| 模块 | 入口 | 输入与输出 / 职责 |
|---|---|---|
| [history.py](../../../experiments/keep_device/history.py) | `encode_workout(data: ExportData) -> bytes` | 将既有导出数据编码为单条 RUN=2 SPORT44；不生成轨迹、不转换坐标、不访问账号或蓝牙 |
| [exporter.py](../../../experiments/keep_device/exporter.py) | `B5Exporter(BaseExporter)` | 构造注入旧生成引擎；校验轨迹末点距离/首末时长与摘要一致，编码后 CRC 校验，原子发布 `.sport44` 且拒覆盖 |
| [dashboard.py](../../../experiments/keep_device/dashboard.py) | `python -m experiments.keep_device.dashboard` | 仅本机的可选 Web 扩展，注入 B5 导出器，管理一个自有 Netsim 或 Windows 启动器子进程和固定文件清单 |
| [files.py](../../../experiments/keep_device/files.py) | `WorkoutFiles(path)` 或 `WorkoutFiles(None, paths=[...])`；`accepts(payload)`；`reply(payload)` | 启动时读取固定快照；请求/回复为 `SID + CID + protobuf`，按 UUID 路由读取并维护每文件接收标记 |
| [state.py](../../../experiments/keep_device/state.py) | `BindingState(path, mac)`；`accepts(payload)`；`reply(payload)` | 保存设备绑定和配置；读写私人 JSON，状态成功落盘后回复 |
| [btcp.py](../../../experiments/keep_device/btcp.py) | `DeviceInfoSession(mac, state=None, model="B3", workout=None)` | 按连接维护设备信息和 B3 发包序号；`reply_packets(request, limit)` 返回通知字节列表 |
| [simple.py](../../../experiments/keep_device/simple.py) | `decode_request(packet)`；`encode_response(payload, request_id, limit)` | B5 校验与分片；解码返回请求 ID 和标准业务载荷，编码返回各通知包 |
| [protocol.py](../../../experiments/keep_device/protocol.py) | `advertisement(name)`；`b3_service(...)` | Bumble 广播和 GATT 服务；历史命名 `b3_service` 同时支持 B3/B5 |
| [emulator.py](../../../experiments/keep_device/emulator.py) | `python -m experiments.keep_device.emulator` | 将共享业务接到 Bumble transport，例如 Android Netsim |
| [windows.py](../../../experiments/keep_device/windows.py) | `python -m experiments.keep_device.windows` | Bless/WinRT 真实蓝牙；有界运行、单订阅客户端、串行通知和退出清理 |
| [windows_mac.py](../../../experiments/keep_device/windows_mac.py) | `python -m experiments.keep_device.windows_mac --tshark PATH` | 从本机 BTVS 的 TShark 解码字段观察实际广播 MAC；不修改蓝牙、绑定或运动文件 |
| [launcher.py](../../../experiments/keep_device/launcher.py) / [start-b5.ps1](../../../experiments/keep_device/start-b5.ps1) | 管理员启动入口，接收 BTVS/TShark、state、可选 SPORT44 和时长 | 按顺序启动地址观察与 B5，在同一窗口显示地址、订阅、业务回复及文件发送进度，并管理本次进程退出 |

`accepts()` 只做路由/形状检查，不代表 protobuf、字段或业务已通过验证。非法输入通常抛 `ValueError`；`UnsupportedRequest` 是其子类；文件和状态读写失败可抛 `OSError`。传输层据此拒绝业务回复，不将异常文本或业务载荷写入诊断日志。

### 可选面板接口

默认 `web.routes.create_app()` 保持 FIT/TCX 页面；实验入口使用 `create_app(exporters={"b5": B5Exporter()})` 显式注入。四个原 `/api/generate/*` 端点复用原规划器，B5 使用严格失败模式，并要求轨迹、WGS-84 转换和步频开启。B5 输出固定在私人面板目录，批次最多 64 天；生成不自动载入或上传。

| HTTP | 用途 |
|---|---|
| `GET /watch` | 面板；`?job=...` 仅显示生成结果的载入预览 |
| `GET /api/watch/status` | running/ready/connected、mac/keep_mac、binding_address、transport、records、total_km、pending/received、error；禁止缓存 |
| `GET /api/watch/logs` | 要求 `X-Watch-Token`，返回 `{ "text": "...", "files": 0 }` 并禁止缓存；本次面板操作最多 100 条，以及本面板私人目录最近 3 个非符号链接 `.log` 的诊断白名单；每个文件最多末尾 64 KiB / 300 行、每行 1500 字，不提供任意路径读取或原始流量 |
| `POST /api/watch/start` / `stop` | 启停面板拥有的广播进程，不接管其他进程 |
| `POST /api/watch/reset-binding` | JSON `{ "keep_unbound": true, "transport": "netsim" }`（实体路线为 `windows`）；必须明确确认 Keep 已解绑、路线与当前配置一致，且广播已停止、没有待完成操作或退出清理。仅通过 `BindingState` 原子清除当前路线的 `bound`，保留 MAC、config、运动文件、选择清单和收讫标记；缺失或损坏的状态文件拒绝操作，不新建、不覆盖，不自动启动广播 |
| `POST /api/watch/load` | JSON `{ "job_id": "..." }`；仅载入本服务生成且校验通过的完整 B5 目录，存在旧待同步记录时拒绝替换 |
| `GET /api/watch/config` / `POST /api/watch/config` | 读取/保存 `transport`、`netsim_ini`、`netsim_state`、`windows_state`、`python`、`btvs`、`tshark`；GET 另返回只读 `config_file`、`data_dir` 保存位置。配置写入私人 `lab/connection.json`，不自动启动；广播或操作未退出时拒绝修改。旧配置缺少 `netsim_ini` 时按未配置处理，状态路径按首次启动参数补齐，可从页面修改 |
| `POST /api/watch/check` | 同样七字段可检查未保存的配置，不修改已保存值；Windows 调用独立 Python 的 `launcher --check`，只读检查版本、管理员权限、默认控制器能力和无线电状态；Netsim 只检查所填 ini 文件存在 |

面板操作和 B5 生成请求要求页面会话的 `X-Watch-Token`；服务绑定 localhost 并校验 Host。页面令牌不是 Keep 凭据。清单来自加载时的不可变字节快照，之后仅按内容哈希校验并刷新收讫标记；外部新增文件不会出现在已加载清单。`connected` 来自本次进程的真实连接/断开事件，并受进程存活状态约束，不等同于 Keep 账号绑定或活动有效。摘要时间以 UTC+08:00 展示，不暴露用户配置或坐标。

已保存的 `netsim_state` / `windows_state` 优先于首次 CLI 状态默认值；路径须在仓库外、彼此不同，不能指向目录或覆盖面板配置、临时配置、清单。切换既有状态不覆盖其内容，新 Netsim 状态经 `BindingState` 创建。Netsim CLI 通过状态旁的 `.lock` 文件持有操作系统进程锁，直到运行结束；面板本地绑定重置使用同一锁，释放不改动状态 JSON。该保护不覆盖旧版本入口、Windows 入口或复制到不同路径的同身份状态，不能代替单模拟器只运行一个广播入口的约束。

`transport` 为 `netsim` 或 `windows`；`binding_address` 为 `{ "value": "AA:BB:CC:DD:EE:FF" | null, "medium": "virtual" | "physical" }`。仅面板拥有的进程仍运行、广播已确认且未进入停止清理时提供地址；Windows 还必须有本轮 BTVS/TShark 的有效 HCI 地址证据。停止、观察失效、退出和前端读取失败时停用旧地址，不用设备身份或永久控制器地址替代。

Windows 操作在后台执行，HTTP 快速返回；`operation` 为 `start/stop/load/null`，`stopping` 表示广播或名称仍在退出清理，`loaded_job` 表示已实际选中的任务。前端继续轮询，不将请求受理视为操作完成。`connected` 在 Windows 仅证明一个通知订阅客户端存在，不证明官方 Keep 身份。配置与检查均不更名或重启蓝牙；只有显式启动/载入才执行现有广播流程。

模拟器 `--stop-file` 必须是已有目录中的新路径；文件出现后正常停止广播。面板退出先通知其子进程，超时只终止自己拥有的进程树。进程强杀或主机断电不能保证正常退出；已持久化的收讫标记保留。

Windows 启动入口面向一轮短期连接与同步，手机只使用官方 Keep；不要求 nRF、USB 调试或系统 SMP 配对。BTVS/TShark 是该 Windows 入口的电脑运行依赖，Bumble/Netsim 不需要它们。Windows 地址变化后可能需要在 Keep 受控解绑并重新添加，不承诺跨重启自动重连。

### ExportData 输入单位

模型定义复用 [src/core/models.py](../../../src/core/models.py)。编码器不会读取 FIT、TCX 或 JSON，也不会重新规划轨迹。

| 输入 | 要求 | 当前线值 |
|---|---|---|
| `trackpoints` | 至少 2 点，保留顺序 | GPS tag 8；数量超过 32767 时分成多个 GPS section |
| 点 `time` | 无时区后缀的 `YYYY-MM-DDTHH:MM:SS`，按 UTC+08:00 解释；允许同秒，不允许倒退 | Unix 秒和相对秒；Unix 秒须在正 int32 范围内 |
| 点经纬度 | 已转换为 WGS-84 的有限数，纬度 ±90、经度 ±180 | 原值 float64；Keep 客户端再转换到 GCJ-02 |
| 点 `altitude` | 米，有限且可表示为 float32 | 原值 float32 |
| 点 `speed` | m/s，有限且非负，不可缺省 | speed=`speed×3.6` km/h；pace=`1000/speed` 秒/km；速度 0 时 pace=0 |
| 点 `distance_meters` | 非负累计米数，不倒退 | Python `round()` 后的 int32，不以摘要距离覆盖 |
| 点 `run_cadence` | 单脚 rpm，整数 0–127，不可缺省 | 乘 2 得到总 spm；按相邻时间差积分总步数 |
| `distance_km` | 有限且为正 | 名义摘要公里数×1000，再取整为正 int32 米数 |
| `duration_seconds` | 有限且为正 | 仅校验；实际摘要时长取首末点之差，须 ≥10 秒且 <7 天 |
| `calories` | 非负整数 kcal | 摘要值×1000，须能表示为 int32 |
| `date`、`start_time` | 既有导出模型字段 | 文件起止时间以轨迹点为准，不用这两个字段覆盖点时间 |

时间线值是标准 UTC Unix 秒，不是把本地钟面直接当 UTC。北京时间 20:00 对应同日 12:00 UTC，凌晨 00:05 对应前日 16:05 UTC；摘要与所有 GPS 点必须保持一致。面板按 UTC+08:00 显示，Keep 端还受 Android 默认时区影响；遇到少 8 小时先按[模拟器时区排查](../guides/connection-and-running.md#时间少了-8-小时先核对模拟器时区)，不能通过整体偏移编码修补显示。

聚合步频/步数复用 `compute_lap_cadence_metrics()`；步数已是双脚合计，不再乘 2。摘要步长取 `摘要米数×100/总步数` 的取整厘米值，0 步时为 0，须能表示为 uint8。文件总长度须不超过 int32，分段数须不超过 32767。输入或计算结果无法表示时拒绝，不截断或平滑源数据。

## 型号、广播与 GATT

| 项目 | B3 | B5 |
|---|---|---|
| 选择参数 | 默认 `--model B3` | 必须显式 `--model B5` |
| 实验名称 | `Keep B3 Lab` | `KeepB5 Lab`，B5 前缀无空格 |
| 应用外层 | BTCP / `A5 A5` | SIMPLE |
| 历史能力 | 未确认常规 SPORT6 会读取历史 GPS；原型拒绝 `--workout` | 原型提供 SPORT44，已在本次真机活动验证 |
| 请求限制 | 完整应用帧，无 ACK / 请求分片 | 单包 REQUEST，status=0，无 ACK / PUSH / 请求重组 |

服务为 `0000190a-0000-1000-8000-00805f9b34fb`：

| 特征 | 方向 | 属性 |
|---|---|---|
| `00000001-0000-1000-8000-00805f9b34fb` | 手机 → 原型 | Write、Write Without Response |
| `00000002-0000-1000-8000-00805f9b34fb` | 原型 → 手机 | Notify；先订阅再处理请求 |

Bumble 的 `--write-characteristic 2` 只用于反向对照，当前已验证方向是默认值 1。Bumble 广播包含 flags、190a 服务和本地名称，须满足传统广播 31 字节限制。Windows 默认保留电脑名，`--keep-name` 才临时切换到所选型号名。

Windows `adapter_address` 用于 DeviceInfo 和 state 文件，空中临时地址由系统管理；手机手动绑定输入的是本次扫描地址，两者不可混用。Bumble 使用本实验生成的随机静态地址；带 `--state` 时必须显式 `--address`，后续复用同一地址。

`windows_mac` 必须在广播启动前连接 BTVS 默认 TCP 端口 24352，通过 TShark 解析 HCI；只在相同广播句柄的配置、190a 服务、随机地址、可连接/可扫描传统广播属性及启用命令均有成功响应后，输出 `AIR_MAC` 和去冒号的 `KEEP_MAC`。失败响应不应用；停止、移除或控制器重置后失效，多组匹配时报告歧义。当前限定单控制器和上述 Windows HCI 模式，不以适配器地址补缺，不保证地址稳定。它不写原始抓包；观察结束后不保证旧输出仍然有效，手机绑定/同步仍须独立验收。BTVS 捕获流须空闲，不能与自动连接的 Wireshark 同时使用；`-Remote off` 不代表只监听 loopback，网络和退出边界见连接与运行说明。

### B3 BTCP

完整帧为 `A5 A5 | A0 | FSN:uint8 | payloadLength:uint16LE | payload | CRC:uint16LE`。载荷长度为 1–32767，精确匹配帧长，不接受尾随字节。CRC-16/XMODEM 初值 0，覆盖帧头到 payload，复用 `binascii.crc_hqx`。

设备信息请求 payload 为 `01 02 03 03`；回复为 `01 02 + DeviceInfo protobuf`。设备发送 FSN 从 0 独立递增并按连接重置，不回显请求序号。B3 回复可按通知长度拆字节块；这不代表支持分片请求。

### B5 SIMPLE

每包有 7 字节头：

| 偏移 | 长度 | 内容 |
|---:|---:|---|
| 0 | 2 | 请求 ID，uint16 LE；回复回显 |
| 2 | 1 | 低 3 位类型，bit 3 为 ACK，高 4 位状态；支持请求 `0x00`、回复 `0x01` |
| 3 | 1 | 末帧索引 |
| 4 | 1 | 当前帧索引 |
| 5 | 1 | SID |
| 6 | 1 | CID |

内部标准业务载荷为 `SID + CID + body`。校验输入为 `requestIdLE16 + typeByte + bodyLengthLE16 + SID + CID + body`；CRC-16/XMODEM 初值 0，校验值以小端附在完整 body 后，随后分片。每片都重复 7 字节头，不能对带分片索引的在线包直接计算整消息 CRC。

B5 设备信息查询接受 `01 02 03 03` 和无正文的 `01 02`；本次手机尝试已观察到通过帧校验的 9 字节无正文查询。两者回复相同的设备信息并保留真实绑定状态；其他正文仍拒绝。此修正的离线通过不代表官方 iOS Keep 绑定或同步已通过。

运行时通知上限为 `min(客户端允许值, 244)`，每片正文容量再减 7；最多 128 片。B5 请求只接受 `type/status/last/current = 0/0/0/0` 的完整单包，请求 body 最多 65535 字节。文件 ID 可能使请求超过默认 MTU 23，客户端仍需协商足够 MTU。

244 是应用协议限制，不是文件块长度。真机曾在较长通知下停止请求后续偏移；244 上限下旧 3280 字节文件连续读完。512 字节文件数据加上 protobuf 和 SIMPLE 开销，对应 244、244、50 三条通知。

## 设备身份、绑定与配置

DeviceInfo 使用自身 MAC 去冒号的大写文本、`LAB` 前缀序列号、硬件版本 `LAB`、固件版本 `0.0.1` 和所选型号名。当前客户端解释 `has_bind=2` 为未绑定、1 为已绑定；资源 proto 的旧注释不作为实现依据。

`--state` 与 `--workout` 独立。没有 state 时只报告未绑定，提供文件不会自动绑定。设备绑定标志不是访问认证；未知命令拒绝也不等于阻止所有 ATT 写入。

| 命令（十六进制 SID/CID） | 当前处理 |
|---|---|
| `01/05`、`01/06` | 绑定/解绑，成功正文 `08 02`；重复绑定正文 `08 01`，为实验策略 |
| `01/04`、`02/02`、`02/03`、`02/04`、`02/21`、`02/23` | 时间、模式、提醒、目标、自动暂停/开始；保存后返回等价 protobuf |
| `02/01`、`02/0b`、`02/11`、`02/13`、`02/15`、`02/19`、`02/1b` | 用户、自动运动识别、晨间/双环/燃脂提醒、血氧开关、运动配置；保存后返回 `08 02` |
| `03/10`、`03/11`、`13/01` | 月里程、心率区间、实验配置；保存后返回 `08 02` |
| `01/03` | 明确的实验电量：voltage=4000、level=80、temp=25，非实测 |
| `03/01–08`、`03/0a–0e`、`08/01` | 日常数据和表盘查询返回空 proto3，未生成心率或历史测量 |

配置请求含 SID/CID 的长度最多 256 字节；未知 protobuf 字段拒绝，晨间提醒字节串最多 45 字节。绑定、解绑及查询要求精确请求形状，未知命令拒绝。保存配置只表示接收参数，未实现真实传感器、提醒或自动运动功能。

state JSON 保存 `schema_version=1`、MAC、bound 和 config。时间/用户配置保存标量，其余支持项保存 protobuf 十六进制。父目录必须已存在；文件缺失时创建，损坏、未知结构或 MAC 不匹配时拒绝。临时文件 flush/fsync 后原子替换成功才更新内存并回复；一份 state 只能由一个进程使用。

Keep 在设备回复成功后才提交服务器绑定，未确认服务器失败时自动回滚设备。断线不清除 bound；解绑保留 config 和运动文件。日常恢复使用同一启动脚本的 `-ResetBinding`（启动器 `--reset-binding`）：仅在用户已于 Keep 解绑后，显式重置本地 bound，保留 config、运动文件与接收标记。默认启动不重置；该参数不能解除账号云端绑定。底层 `state --reset-binding` 保留为诊断接口，日常操作不要求单独调用，顺序见连接与运行说明。

## 文件 RPC 与收讫

请求/回复使用 Google protobuf，字段号见 [files.py](../../../experiments/keep_device/files.py)。请求含 SID/CID 最多 64 字节；未知字段拒绝。

| 命令 | 请求 | 回复与状态 |
|---|---|---|
| `06/01` | `FileType(type:1 uint32)` | `FileSum(file_table:1 repeated)`；每项 uuid:1 uint64、file_size:2 uint32 |
| `06/02` | `GetFileReq(uuid:1 uint64, len:2 uint32, offset:3 uint32)` | `File(status:1 uint32, file_data:2 bytes)`；0 成功、1 长度/偏移无效、2 无待传文件 |
| `06/03` | `FileType` | `FileStatusSum(file_status_table:1 repeated)`；SPORT44 收讫项的 status:3=1，已知空目录返回空结果 |
| `06/07` | `DelOneFile(type:1 uint32, uuid:2 uint64)` | `DelOneFileStatus(status:1 uint32)`；匹配 SPORT44 为 1，其余不存在项为 2 |

目录类型是十进制：44（SPORT_PLUS）返回未收讫文件；`1–6、35–37、41–43、45、47` 返回已确认的空目录，其余类型拒绝。目录类型 44 与正文 section tag 44 属于不同命名空间。

单文件接口保持兼容；显式 `paths` 批量输入为 1–64 个文件、合计不超过 64 MiB，与单文件参数互斥。启动前固定并校验全部快照，重复内容或 UUID 冲突拒绝。64 条限制确保目录及批量收讫响应在 MTU 23 下仍不超过 SIMPLE 的 128 片上限。批量读取、单条收讫均按 UUID 路由，每个文件保留独立标记；批量收讫不是事务，某条落盘失败时不回复成功，已落盘的条目仍保留，重试幂等。日志 `workout_batch total/received/pending` 只统计本次文件集合，不代表有效活动数量；读取日志没有文件序号，不能把不同文件的偏移合并成总进度。

B5 始终挂接文件 RPC，即使未传入 `--workout`。`WorkoutFiles(None)` 表示无待传文件：已支持类型的目录与批量收讫列表为空，读取或单文件收讫返回不存在状态，不创建运动文件或接收标记。此前无文件时拒绝这些请求会阻断初始化中的目录查询；这项修复不改变未知命令、未知类型与非法 protobuf 的拒绝规则。

客户端通常请求 len=2048，原型每次返回至多 512 字节，按实际返回长度推进。offset 从 0 起；len=0 或 offset≥文件长度返回状态 1；UUID 不符或已收讫返回状态 2。读取响应使用 `File.file_data` 字段 2，不是另一发送方向消息 `FileData` 的字段 4。

`WorkoutFiles` 启动时读取不可变快照，校验大小、尾部描述长度与 CRC32；它不代替完整 SPORT44 正文解析。UUID 是文件 SHA-256 前 8 字节按大端解释的 uint64，是实验约定，不是恢复出的真实硬件 ID 编码。

SPORT44 删除请求在原型中表示收讫：先原子写入同目录 `<文件名>.received.json`，再隐藏目录项并回复成功，保留原二进制。标记保存版本、SHA-256、UUID、received=true；重启校验匹配后继续隐藏。写入失败不隐藏、不回复成功；重复收讫幂等。空目录的删除不会修改 SPORT44 队列。

标记只证明客户端确认领取。有效活动需以 Keep 的记录、来源、统计和重开结果核验。文件日志只写命令、类型、偏移、长度、状态和收讫布尔值，不写 UUID、路径、文件名、坐标或原始载荷。

## SPORT44 二进制

全部多字节字段为小端。顺序为：GPS section(s) → 四个分段 section → 78 字节描述区 → 描述长度 int16（78）→ 8 字节候选零值 → CRC32 uint32。CRC32 覆盖之前全部字节，用 `zlib.crc32`；不与 BTCP/SIMPLE CRC16 混用。

每个 section 为 `tag:uint8 + count:int16LE + count个定长元素`。GPS 每节最多 32767 点；四个分段数组长度一致。当前单节 49 点、1 段文件大小为 `3 + 49×65 + 26 + 78 + 14 = 3306` 字节。

### GPS tag 8：65 字节

| 偏移 | 类型 | 当前含义与编码 |
|---:|---|---|
| 0 | float32 | speed，km/h，源 m/s×3.6 |
| 4 | float32 | bearing，当前 0，缺测 |
| 8 | float32 | pressure 原始值，当前 0，单位未完整恢复 |
| 12 | int32 | 运动开始后的相对秒 |
| 16 | float64 | WGS-84 经度 |
| 24 | float64 | WGS-84 纬度 |
| 32 | int32 | 累计运动秒；本原型无暂停，与偏移 12 相同 |
| 36 | uint8 | crossKmMark，当前 0，按累计距离寻找边界 |
| 37 | uint8 | 暂停字段，当前 0；未实现暂停事件 |
| 38 | int16 | accuracy 原始值，当前 0，缺测语义未完整恢复 |
| 40 | int32 | Unix 秒 |
| 44 | float32 | currentPace，秒/km；客户端转 long，可能截断小数 |
| 48 | float32 | 海拔，米 |
| 52 | int32 | 累计距离，米，源值取整 |
| 56 | int32 | 累计总步数，按右端点总 spm×相邻秒数/60 积分后取整 |
| 60 | int32 | 点热量原始值，当前 0，未恢复其尺度 |
| 64 | int8 | locationType=1，可选中已观察的 geographic 分支；精确硬件枚举语义未知 |

客户端将相对秒乘 1000 放入内存 timestamp，上传序列化再除 100，成为 0.1 秒计数；Unix 秒则转毫秒。编码器必须按设备文件单位写入，不能提前使用 HTTP 单位。

### 分段 section

| tag | 类型 | 内容 |
|---:|---|---|
| 40 | int32 | KM_PACE_V2：每段时长，秒；名字虽含 PACE，消费者作为 duration 累加 |
| 43 | int32 | SINGLE_PERIOD_TIME_V2：段间隔秒数，用于采样频率计算；无暂停时与 tag 40 相同 |
| 20 | int16 | SINGLE_PERIOD_DISTANCE：每段米数 |
| 44 | int32 | SINGLE_PERIOD_PACE_V2：每段秒/km，`round(段秒×1000/段米)` |

采用固定 V2 时间/配速标签，避免旧 tag 1/19/21 的 signed int16 溢出。段数取 `ceil(摘要米/1000)`，所有数组同长；不能只写 duration 或让时间数组缺项。

每个公里边界采用与客户端 `K()` 一致的线整数距离：首个 `round(累计米数) ≥ 第n公里×1000` 的点。段秒数/米数取相邻边界差。最后一段无命中时，使用摘要总秒数和米数收尾；若有命中，必须是最后一点且与摘要一致。GPS 终点超过摘要、缺非末公里边界、同点跨多公里形成零时长、段距离非正或超过 int16 等情况明确拒绝。

**隐式补段陷阱：**客户端 `h()` 会在 `摘要距离/1000 == 已有段数+1` 时尝试只补一个正且小于 32767 的剩余 duration，然后 `l()` 才转换 crossKmPoints。缺配速/距离会变成 0。旧 1000 米/411 秒摘要和约 915 米 GPS 因此产生了 `pace=0, distance=0, duration=411`；不能只看 `l()` 的空数组早退便认为 GPS-only 文件不会生成分段。

本次显式四数组 `[411] / [411] / [1000] / [411]` 保留原摘要和 GPS，消除了该矛盾。19:00、20:00、21:00 三组对照支持它是本次无效记录的根因；未取得服务器阈值，也未逐字段消融，详见调研报告。

### 78 字节描述区

| 偏移 | 类型 | 当前值 |
|---:|---|---|
| 0 | int32 | workoutType=2，RUN |
| 4 | int32 | 首末点时长，秒 |
| 8 / 12 | int32 | 首点 / 末点 Unix 秒 |
| 16 | int32 | 摘要距离，米 |
| 20 | int32 | 总步数 |
| 24 | int32 | kcal×1000 |
| 28–75 | 48 bytes | 未提供的可选指标为 0，不猜写 averagePace/maxSpeed |
| 76 | uint8 | 平均总步频，spm |
| 77 | uint8 | 平均步长，厘米/步 |

无心率时 Keep 可能重算热量；没有捏造心率数组。摘要仍使用原 `distance_km`，点累计距离仍是原轨迹。已通过的样本摘要 1000 米、GPS 末点 915 米；这不是所有距离差都被接受的证明。

## 运行与清理边界

模拟器、Windows 的 Python 入口均支持 `--workout-dir`，与 `--workout` 互斥，仅 B5 可用。它按文件名排序选择目录第一层的 1–64 条 `*.sport44`、合计最多 64 MiB，启动后不扫描新文件；不接受 ZIP/FIT，也不将多条运动合并。PowerShell 包装入口仍提供单文件参数。2026-11-16 模拟器本批 44 条、398697 字节已被 Android Keep 逐条领取；未逐条核验全部有效性，也未验收批量断线恢复、Windows 批量或 iOS。

`emulator.py` 直接使用 Bumble `android-netsim` transport，与 Windows 启动器的状态和运行依赖隔离。重启后读取本轮 `netsim.ini` 的 `grpc.port`，显式复用同一实验静态随机地址、state 和指定 SPORT44；保留接收标记，不能把目录为空视为传输故障。该入口输出连接、业务及文件日志，没有 Windows 启动器的汇总进度显示。Netsim 验收不能代替实体蓝牙或 iOS 验收。

2026-11-16 API35 对照在将安装目录的 MSA 库可逆改名后完成，APK 与签名未改、登录数据保留，但安装运行环境有干预；步骤及恢复边界见 [连接与运行](../guides/connection-and-running.md#api35-的-msa-启动故障与可逆隔离)。`0e/13` 为辅助运动联动状态请求，当前仍拒绝，不以猜测应答消除等待；本轮设置随后自行完成。

`launcher.py` 先校验仓库外 state/运动文件与工具路径，确认 BTVS 端口未被占用，再启动本次 BTVS 和 TShark；只有捕获进程存活且 TCP 已接入，才启动 B5。它不接管其他抓包进程，不自动重置绑定或接收标记，不写原始抓包。地址观察中断或未取得有效 MAC 会报错并停止原型，不能把旧地址或适配器地址作为成功结果。

启动器复用 `windows_mac.AdvertisingAddress` 判断广播地址，复用原型日志呈现业务状态。订阅仅证明客户端订阅；业务应答仅证明回复完成。文件进度按已成功回复的读取区间并集计数，不重复累计重读区间；100% 与客户端收讫均不等于 Keep 云端接纳、来源正确或活动有效。

`windows.py --stop-file PATH` 要求路径在已有目录内且启动时不存在；文件出现后结束广播等待，走正常清理。启动器在私人临时目录创建这一信号，退出时等待原型最多 90 秒，然后关闭本次观察进程；清理失败明确报错。它不把系统配对成功当作退出或连接成功条件。

面板另向 `launcher.py --stop-file` 发出外层停止信号，启动器转给上述内部信号，保留名称恢复和自有捕获进程清理顺序。`--events-json` 输出 `WATCH_EVENT` JSON 的 address/advertising/link/stopped/stopping/error；停止及错误先使地址失效，最终以启动器进程退出为清理完成。面板等待最多 100 秒；超时显示失败并继续禁止重启，不强杀正在恢复名称的启动器。

Windows 桥仅允许一个通知订阅客户端，排队/待调度请求上限为 8；订阅切换会使旧任务失效。每条通知定向发送，等待最多 10 秒，同时核对成功状态与实际发送长度。Bless 不提供写入者身份，库可能确认底层 ATT 写入，业务拒绝不是访问认证。

`--keep-name` 先校验输入文件，再用 Bless 更名并重启选定适配器，之后启动新广播子进程。退出时先停止子进程，再恢复原 Local Name 值/类型；原本无覆盖值时写回 Windows 默认电脑名、重启，再移除临时覆盖。缺少 `COMPUTERNAME` 时在改名前拒绝；控制器另有缓存自定义名称的情况不在恢复保证内。

名称恢复后通过 WinRT Radio 刷新广播缓存，只恢复原无线电状态，各步最多等待 10 秒。Ctrl+C 先等子进程清理 10 秒，超时再终止本次子进程树并继续恢复。PnP 失败或返回 3010 会报错，不自动重启电脑；恢复失败不宣称名称已恢复。断电或强杀父进程无法保证清理，最终名称应由手机扫描/HCI 核实。

## 尚未恢复或验收

| 边界 | 当前结论 |
|---|---|
| Windows 稳定重连 | Keep 缓存添加时 MAC，Windows 广播地址可能变化；当前按本轮地址受控重绑，不承诺稳定长连或跨重启恢复 |
| API35 / Netsim | 隔离 MSA 库后，Keep 9.1.120 完成绑定、3306 字节传输/收讫；活动为 Keep 手环 B5 来源、1 km / 411 秒且无无效标记；模拟器重启后保留记录并自动重连，type44 为空且未见本轮重复记录。仅一次恢复，意外退出原因及长期稳定性未解决 |
| 一键入口验收 | 软件 MAC 与 Android 实扫对照一致；2026-11-16 最终 PowerShell 入口在 nRF 停止时由官方 Android Keep 完成绑定、3306 字节传输/收讫及有效设备来源活动入账；在线解绑同步本地 bound=false，退出后无本轮广播/捕获进程残留，名称配置恢复；本轮重开持久性未复测，iPhone 待验收 |
| iPhone | nRF Connect 协议往返通过；官方 Keep 直接绑定/同步未通过，同账号活动显示未验收 |
| 服务器 | 本次有效活动及统计、重开保留已观察；独立 HTTP 重读、阈值、一般去重和来源覆盖规则未知 |
| 泛化输入 | 多公里、长时 V2、重复秒和错误边界有本地测试；无对应真实硬件/云端全面验收 |
| 固件缺口 | opaque8、locationType 精确语义、缺测 bearing/pressure/accuracy/点热量、暂停、GPS_NEW、独立速度段未完整恢复 |
| 传输恢复 | SIMPLE 请求重组、ACK/PUSH、多手机、断线恢复后的完整再次同步未实现或未验收 |
| 产品集成 | 可选 dashboard 复用旧 Web 四模式并注入原生 B5，提供手表管理；默认应用不加载实验依赖，未打包发布 |

凭据、state、SPORT44、接收标记、截图、抓包和反编译产物均留在私人实验目录，不提交仓库。
