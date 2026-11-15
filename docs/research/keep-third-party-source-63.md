# Keep 设备来源同步调研（issue #63）

调研日期：2026-11-15。目标来自 [issue #63](https://github.com/EmberCollective/CampusRunning/issues/63) 及本次补充说明。

本文保留研究证据与方案演进；当前操作步骤见[实验 README](../../experiments/keep_device/README.md)，模块接口、单位、线格式和拒绝边界以[CONTRACT.md](../../experiments/keep_device/CONTRACT.md)为集中参考。

用户已确认 FIT 文件可以导入，问题是记录明确显示“文件导入”。最终确认的目标是：保留跑步日期、GPS、距离、配速和步频，记录显示设备来源；**Keep 手环/手表也可以，不要求佳明等第三方品牌**。最终需兼容 Android 与 iPhone。研究初期使用电脑模拟器，目前已转到 Android 真机验证。

## 当前结论

**Android 真机官方 Keep 9.1.120 已通过 Windows B5 原型导入分段修正后的 3306 字节 SPORT44：活动显示“Keep 手环 B5”、1 km、411 秒，无无效标记，统计增加 1 km、1 次和 411 秒；重开 App 后记录和统计保留，未新增重复活动。三组对照支持客户端自动补出的零配速、零距离分段是本次故障根因；服务器具体阈值未取得。结果限定本次候选，Windows 稳定重连、服务器独立重读和 iPhone 兼容仍未完成。**

协议研究最初从 Kitbit3/B3 路径入手。后续代码确认 B5 使用 SIMPLE 传输，且会读取含 GPS 的 SPORT44；B3 的常规 SPORT6 同步只确认了配速、心率和步数，不能据类名中的 B3 推定它会读取 GPS。直接 HTTP 上传作为契约研究分支；合作平台账号同步作为备选。修改 FIT 厂商字段或单独发送心率不构成方案。

当前证据分层如下，活动创建与有效性仍需分别验收：

| 层次 | 当前结果 | 边界 |
|---|---|---|
| Android B5 绑定 | 官方 Keep 显示“绑定成功”，随后进入“我的手环 / Keep B5”设备页 | 已验证真实 App 接受本次绑定；尚未独立重读服务器绑定关系或验收重启恢复 |
| B5 历史文件 | 通知上限设为 244 字节后，7 次读取覆盖完整 3280 字节；重组文件与源文件相同，随后收到 `06/07` 接收确认 | 文件接收本身不证明云端有效性 |
| 活动详情 | 19:00 样本显示“Keep 手环 B5”、1.00 km、06:51、平均配速 06′51″、162 spm、步长 0.90 m 和原轨迹 | 提示“平均配速超过当前人类最高纪录”，旧记录无效 |
| 点配速修正 | GPS `currentPace` 已按秒/公里编码；20:00 样本显示平均 06:51、最快 06:46 及合理范围的配速曲线 | 仍出现同一无效提示，单改点配速不足以解决问题 |
| 分段修正 | 21:00 样本明确编码四个对齐数组；记录无无效标记，统计增加 1 km、1 次和 411 秒 | 三组对照支持本次根因；服务器公式和阈值未知，多公里格式尚无真机验收 |
| iPhone BLE | nRF Connect 与 Windows B3 原型完成设备信息交换，抓包通过 CRC/protobuf 解码 | 官方 iOS Keep 直接绑定仍未通过；不能用 Android 结果代替 |
| 重开 App 与重复记录 | 有效活动、来源及统计保留，未新增重复活动；首次领取后再次查 SPORT44 目录为空 | 这是本次 App 持久验收；独立服务器重读及断线重连复传尚未验证 |
| 稳定重连与两端 | 本轮重开 App 后设备页连接失败，原型仍运行但无新订阅 | 未重新抓包核实本次地址，不能确定此次失败原因；iPhone 未验收 |

本轮使用未经修改的 [lasting-yang/frida_dump](https://github.com/lasting-yang/frida_dump/tree/17340629ce267464bc342c31b12b5ecf84b93722) 的 `dexCache_dump.js`、官方 Frida 16.7.19 和 JADX 1.5.6，从官方模拟器存活的 Keep core 进程取得 22 个运行时 DEX（162,680,000 字节）。没有自行实现解壳、DEX 扫描或抓包工具。REA 的 Android provider 在本机尚未稳定工作，因此不能把 JADX CLI 的成功记成 REA 成功。原始产物及日志只保留在仓库外实验目录。

新恢复的方法体补齐了以下结论；下文较早的实验记录应结合这些更新阅读：

- **Android 发现：**手动地址路径匹配 `BluetoothDevice.getAddress()`；上层还要求非空名称、已知设备型号，以及可连接状态不为 false。B3 名称前缀为 `Keep B3` / `Keep-B3`，B5 的配置名称为 `KeepB5`（无空格）。手动绑定允许厂商广播数据及绑定状态为空，但明确的已绑定状态会阻止连接。B5 已通过 Android 真机发现和绑定；这些规则不能直接代替 iOS 规则。
- **绑定检查顺序：**设备连接、读取 DeviceInfo 后才调用 `/kitbit/v2/bindCheck`。因此该 Android 路径的首次发现失败不能归因于这个服务器检查。真实 App 的本次 B5 绑定和一条有效活动已通过；独立服务器重读及恢复仍待验证。
- **绑定状态：**绑定 SID/CID 为 `01/05`，解绑为 `01/06`，成功 protobuf 为 `08 02`。BTCP 将 SID/CID 放在应用载荷前，SIMPLE 将其放在帧头，不能混用。设备回复成功后，Keep 才提交服务器绑定；服务器失败路径没有补偿性设备解绑。原型已实现持久化绑定/解绑及本次初始化涉及的时间、用户、模式、提醒、目标等有界配置；部分命令返回等价配置，不统一回复成功码。支持的配置、查询和空目录见[实验说明](../../experiments/keep_device/README.md)，保存开关不代表实现了对应传感器或提醒功能。
- **历史 GPS：**B5 的 SPORT44 使用 SportPlus 结构。65 字节 GPS 项的经度、纬度分别位于偏移 16、24；偏移 12 是运动开始后的秒，偏移 40 是 Unix 秒，偏移 52 是累计米数。客户端将 WGS-84 转为 GCJ-02，不能把项目原始 GCJ-02 直接放进设备文件。共享 `OutdoorGEOPoint` 与设备字段映射确认偏移 0 为 km/h、偏移 44 为秒/公里、偏移 48 为米。共享模型按总步数 × 60 ÷ 运动秒数计算平均步频，因此适配使用总 spm，本项目单脚 `run_cadence` 不能直接复制。静态上传链已连至 `POST /pd/v5/sportlog`；轨迹相对时间先从设备秒转内存毫秒，再在序列化时转成 0.1 秒计数，随后进行轨迹编码。真机已观察到设备来源活动，但没有独立核验 HTTP 请求及服务器重读；独立速度段的缩放仍未确认。
- **广播能力：**Windows 原生 GATT 广播接口没有厂商数据参数；同时启动独立 Publisher 是否能构成同一可连接设备，尚未实测证明。Linux BlueZ/Bumble 是现成候选，但本机当前 WSL 内核缺少已确认的 RTL8922 支持；未为了未知的 iOS 广播要求升级 WSL 或切走蓝牙控制器。
- **模拟器兼容性：**恢复的 MSA 初始化代码仅捕获 `Exception`，无法捕获实测的 `UnsatisfiedLinkError`；APK 确有相应 ARM64 原生库，不能简单解释为缺库。尚无原签 Keep 与 Netsim 稳定共存的修复，BlueStacks 登录基线保留。

最新 Android 包区分了三种不同身份：

| 身份 | 已找到的证据 | 与目标的关系 |
|---|---|---|
| 第三方心率设备 | 标准 HRS 服务；连接模型使用 `HeartRateType.THIRD_PARTY` | 只能证明心率接入，不是活动来源 |
| Keep 自有穿戴设备 | `KitDataFactory` 显式写入 `OutdoorVendor.VendorSource.KEEP`，类型为 `KEEP_WATCH` 或 `KITBIT`；真机有效活动显示“Keep 手环 B5”并计入统计，重开 App 后保留 | 已证明本次候选可行，两端和稳定重连仍须验收 |
| 第三方活动 | `OutdoorVendor.getSource() == VendorSource.THIRD_PARTY` | 另一个来源模型，不是本次必须达到的品牌类别 |

因此，文件导入入口迁移已经不是当前任务的解决方案。蓝牙“能发现设备”“能读心率”“能同步历史活动”“云端显示第三方来源”也必须分别验收。

## 版本与证据范围

| 对象 | 本次取得的版本 | 证据 |
|---|---|---|
| Android 官网渠道 | 9.1.120，versionCode 50240；下载页标注 2026-11-13 | 官网 APK 与 JADX 解出的 manifest 一致 |
| 腾讯官方移动分发渠道 | 同为 9.1.120 / 50240，分别提供 ARM32 与 ARM64 包 | 两包已下载，版本、ABI、文件哈希和原签名验证通过 |
| 中国区 App Store | 9.1.110，发布时间 `2026-11-09T06:12:08Z`，最低 iOS 14 | Apple lookup 返回；已通过 USB 确认连接的 iPhone 安装 9.1.110 / build 50682，未取得 IPA |
| Android 静态工具 | 官方 JADX 1.5.6 | 资源及部分 DEX 定向反编译 |
| Web 静态工具 | REA | Keep 帮助中心发布的 JavaScript |

“最新”限定上述渠道的本次查询结果，不代表所有应用商店、地区或灰度账号。

Android APK SHA-256：

```text
a7922155d4e2f5bad4e07ef299fc743a2c30cb56900657b58b53d02bae998411
```

上述官网 APK 的原生库目录只有 `arm64-v8a`，但其中加固组件 `libDexHelper-x86.so` 实际为 x86-64 ELF，其余已核对的 `libDexHelper.so`、`libmsaoaidsec.so` 为 AArch64。不能把目录名当作所有库的实际架构。APK 的 Application 是 `com.secneo.apkwrapper.AW`，存在加固；若干关键 DTO 只能看到引用，JADX 找不到其定义。以下静态接口和代码路径不是抓包成功证据。

后续从[腾讯官方移动页](https://a.app.qq.com/o/simple.jsp?pkgname=com.gotokeep.keep)取得同版 ARM32 包，MD5 为 `F5BDC44DB536A8DC508557901CBA1077`，SHA-256 为 `f7d89d2dd9385432b07568a300625b44283f3a08cc7903bdfa85df95831792a5`。官网、腾讯 ARM32、腾讯 ARM64 三包均通过 Google `apksigner` 的 v1/v2/v3 验证，签名证书 SHA-256 一致：`872f838cc1cf7d939a06df095bd985b24b69913e3f96198a53751d2dd8539782`。没有修改或重签 APK。

ARM32 包仍使用同一架构选择逻辑，库改为 ARM32 和 x86。官方 API30 x86 r16 实测支持 `x86,armeabi-v7a,armeabi`，该包安装成功，但首启仍在 `H.load → AW.attachBaseContext` 报 `EM_386 instead of EM_ARM`，尚未到隐私页。因此仅切换位数没有解决官方模拟器的加载冲突。腾讯 ARM64 包中已核对的加固库和设备标识库与官网逐字节相同，也未提供这两处故障已修复的依据。

官方 API31 r14 镜像实测蓝牙服务与 Netsim 链路存在，但 `ro.zygote=zygote64`、32 位 ABI 为空，不能用来安装 ARM32 包。API30 的蓝牙框架显示 ON，HAL 为 `android.hardware.bluetooth@1.1-service.sim`，未验证其能与 Netsim/Bumble 通信。这两项结果不能拼成一个已经可用的环境。

已运行官方 Android Emulator 37.2.13、平台工具 37.0.1，并建立 Android 15/API35 与 Android 14/API34 的 Google APIs x86_64 环境。WHPX 实测可用，无需修改系统虚拟化组件或重启。两环境均能安装官网 Keep 9.1.120，最初启动均遇到兼容性错误；后续 API35 保留隐私同意并完整停止 App 后冷启动，获得了可交互登录基线。用户随后在 API35 和 BlueStacks 均完成登录，API35 的 Keep 已实际连接探针并发出初始化请求；尚未通过绑定、历史同步或上传。逆向与抓包复用 REA、JADX、Frida 系列现成工具及 Netsim；自行编写的代码仅限用户授权的设备原型，不另造分析或抓包工具。

### 真机、模拟器与原型实测

原型位于 [`experiments/keep_device`](../../experiments/keep_device/README.md)，提供 Bumble 0.0.236 / Netsim 与 Bless / Windows 入口。默认保留早期 B3 BTCP 路径，B5 使用 SIMPLE；已实现设备信息、持久化绑定状态、有界初始化配置/查询及可选单条 SPORT44 文件队列。服务为 `190a`，`0001` 写入、`0002` 通知已由实际交互验证。分段修正后的本次候选已完成文件传输、有效活动创建及统计累计。

| 检查点 | 实测结果 | 能证明的范围 |
|---|---|---|
| 早期 Bumble 两端虚拟链路及地址复用 | 当时 49 项测试通过，包括首帧、CRC、protobuf、未订阅拒绝、MTU 分段和重连序号 | 设备信息应答在 Bumble LocalLink 上工作，不证明 Keep 已接受 |
| 早期原型接入 Emulator Netsim | 已广播；登录后的官方 Keep 实际连接、订阅 `0002`，向 `0001` 发出 12 字节 Write Command | 已观察 App 到探针的 GATT 交互；当时尚未实现应用层应答 |
| API35 启动 Keep | 首次启动及服务自动重启发生 `com.bun.miitmdid.e.a()` JNI 异常；明确 force-stop 后冷启动，登录页持续约 335 秒无新增崩溃、可交互 | 获得可重试的登录基线，未证明初始化问题彻底修复或认证成功 |
| 干净 API34 启动 Keep | 未接入 Frida即在 `AW.attachBaseContext → H.load` 崩溃，报告 `libDexHelper-x86.so` 为 EM_X86_64、预期 EM_AARCH64 | 降低系统版本未解决兼容问题，失败早于 OAID 初始化 |
| API34 ARM64 客体 | 内核运行至 `/init` 后 SIGSEGV/panic，ADB offline | 未进入 Android |
| API28 ARM64 客体 | 约 278 秒后 `sys.boot_completed=1`；安装 Keep 时 package 服务断开，随后系统服务重启，未安装成功 | 系统曾开机，但不能作为稳定 App 环境；日志还明确无蓝牙服务 |
| BlueStacks 5.22 / Android 9 | 首次同意隐私时出现 MSA 异常；冷启动恢复后用户登录成功，设备及第三方目录可正常浏览 | 登录和目录导航可用；该模拟器不支持蓝牙 |
| iPhone USB 工具通信 | 已复用配对并读取 Keep 的指定版本字段；iOS 27.0.1，开发者模式未开启 | USB 通信可用，不代表 BLE、HTTPS 明文或活动同步已验证 |
| iPhone nRF Connect 直接连接原型 | 真实发现、连接、订阅、首请求与设备信息通知已验证 | 不代表官方 Keep 接受设备 |
| Android 真机 Keep 9.1.120 → Windows B5 | 显示“绑定成功”，进入正常 B5 设备页 | 本次绑定通过；“正在同步数据”不证明活动同步完成 |
| B5 历史文件 | 离线检查通过；244 字节通知上限下真机读取完整 3280 字节，各块 CRC 和内容正确，收到单文件接收确认 | 证明本次传输成功，未覆盖断线续传或全部硬件格式 |
| 历史活动与来源 | 前两条样本无效；补齐分段后的 21:00 记录显示“Keep 手环 B5”、无无效标记并计入统计 | 限定本次 1 km 候选；服务器独立重读、稳定恢复和 iPhone 尚未验收 |

API34 的加载选择有代码证据：`com.secneo.apkwrapper.H.getRuntimeAbi()` 读取 `/proc/self/exe` 的 ELF machine；检测到 x86-64 后选择 `DexHelper-x86`，实际加载却进入了要求 AArch64 的路径。

也已实测官方 API34 ARM64 镜像（SHA-1 `2fe8b46d419a3400e30f31b0152b241b50c8b99f`）：Windows x64 官方启动器限制跨架构，直接运行随包 aarch64 后端则先遇到 `PCI bus not available`。显式使用现成 QEMU 参数 `-machine virt` 后，内核能运行至 `/init`，但该进程 SIGSEGV 导致 kernel panic；加入 `-cpu max -no-reboot` 仍复现。ADB 始终 offline，未进入 Android、未安装 Keep。已停止失败实例，不能将内核启动描述为模拟器可用于登录。

API35 的 OAID 异常不能仅凭文本归因于 Frida或系统版本。后续独立 Android 用户、非 root adbd、未启动 Frida 的对照仍在同意隐私后复现 `e.a()` JNI 缺失；该轮日志同时确认 `libDexHelper-x86.so` 已由转译层作为宿主库成功加载，故其失败阶段与 API34 不同。MSA 官方 FAQ 也记录过相同方法异常，但其 `minSDK ≥ 23`、`extractNativeLibs=false` 条件不适用于本包（minSDK21、extractNativeLibs=true）。当前没有采用修改 APK、伪造登录成功或替换来源标签的做法。

结合 BlueStacks 的冷启动结果，对 API35 独立用户 11 保留数据再做对照：设备开机后的首次 Keep 启动及自动服务重启仍分别崩溃。随后通过现成 ADB 执行 `am force-stop --user 11 com.gotokeep.keep`，再启动官方 SplashActivity，新主进程及子进程持续约 335 秒，登录页前台稳定，无新增异常或 ANR；切换密码/手机号登录和空白输入框聚焦通过。没有清除数据、修改 APK、root adbd 或注入 Frida。这是本次可复现的恢复步骤，不保证下一次系统开机或登录后的功能稳定。该 AVD 蓝牙为 ON，Netsim 自动启动；Bumble 已重新接入并开始广播，scrcpy 5.0.1 已打开官方模拟器窗口供用户登录，未录屏、未转发音频或自动同步剪贴板。

Netsim 已启用 `--pcap`；运行中输出文件曾为零字节，正常关闭模拟器后已写出有效内容。使用 Scapy 2.6.1 的 PCAP 读取器及 Bumble 的现成 HCI 解码器检查原型捕获：46 包，由 23 条 HCI 命令及 23 条事件组成；设置广播参数、广播数据、启用广播均返回 SUCCESS，没有 ACL 数据包。这是控制器接受广播的证据，不是 Keep 连接或业务协议抓包。

上述 46 包属于登录前的旧实验。登录后的新会话使用 Bumble 自带 `BUMBLE_SNOOPER` 单独捕获，检查时有 108 包，其中 37 个 ACL 包及一条 12 字节 ATT Write Command。通过正常 UI 进入 **我的 → 顶部设备图标 → 添加装备与应用 → 手动添加 Keep 智能装备 → 手环 → Keep 手环 B3 → 手动输入 MAC 地址**，用户输入探针自己生成的随机静态地址，并经系统 UI 授予附近设备权限。Keep 建立连接、订阅通知并写入请求，曾显示“我的手环 / Keep B3 / 正在配置设备”。探针没有实现应答，随后对端以原因 `0x13` 断开，App 显示“扫描手环 / 未发现设备”。这个通用错误页面不能推翻已经捕获的连接事实，但也不能把短暂出现手环主页当作绑定成功。没有上传运动记录。

在设备流程已执行后，用 Android 自带 `am dumpheap` 成功获取运行时堆快照，原进程存活；无需 root adbd 或 Frida。经官方 `hprof-conv` 转换及 Eclipse MAT 1.16.1 定向 OQL 查询，取得 `ProtocolTypeB3` 的 236 项 SID/CID、`ProtocolType` 的 96 项及 `TransmissionType` 的 3 项映射。数据帧对象 `band.btcp.internal.DataFrame.a` 的 12 字节与抓包逐字节一致；控制字段 `d` 为 `0xA0`。快照只留本机实验目录，未读取无关账户字段。

其中 `DEVICE_MANAGE_DEVICE_INFO` 为 SID=1/CID=2，`DEVICE_MANAGE_SET_CONNECT_PARAM` 为 1/1；`TransmissionType` 为 BTCP=0、V1=1、SIMPLE=3。首条请求中出现对应字节，但其他字段含义仍未闭合，不能仅据枚举拼出应答。`KeepHeaderType` 的四项静态引用均为空，`SportPlusDataType` 未见于本次快照；堆快照也不包含方法实现。对实际帧前十字节调用标准库 `crc_hqx`、初值 0，结果与末两字节按小端读取一致；这仍只有一种独特输入，不足以单独确立全协议 CRC 范围。

首轮探针进程随后退出，已通过正常后台启动恢复相同实验地址，并增加 `--address` 支持避免用户重复输入。恢复后的独立捕获再次观察到连接、订阅和完全相同的 12 字节请求，仍因没有应用层应答而断开；没有新增运动记录。不同运行的捕获分开保存，没有覆盖首轮证据。

早期 Frida 路线未取得运行时 DEX，后续成功路径见下文“运行时代码与首条应答”。额外建立 API35 独立 Android 用户可稳定停留在隐私提示，但 `frida-dexdump --realm emulated` 附加后在搜索阶段收到 `script has been destroyed`，系统记录目标自行退出（EXIT_SELF、status 0），未产生 DEX。native realm 对照也未取得 DEX；相关进程和 Frida 服务已停止。该时间关联不足以确定所有启动失败均由分析工具引起。另经官方 UI 进入“不同意，仅浏览”模式可以看到公共首页，但进入“我的”仍要求隐私同意，未开放设备流程。工具、APK、截图和原始日志留在仓库外。

API28 对照使用同一官网最新版 Keep，并未降级 App。系统初始化完成后安装返回 `Failure calling service package: Broken pipe (32)`；后续可见 zygote 重启、媒体服务原生崩溃及 `IVold.mount` 超时。尚不能据此确定是 Watchdog、内存回收还是其他原因导致安装期间系统服务退出。该镜像还打印 `No Bluetooth Service (emulator)`，即使解决稳定性，也只能作为运行时分析基线。所有失败的模拟器实例已停止，保留 AVD 和日志供复查。

### 备用环境的实际边界

研究早期只有 iPhone 可做真机验证，后续已取得 Android 真机并完成 B5 绑定。Windows 平台 API 实测本机蓝牙支持 BLE 中心及外设角色；Bless 0.3.0 在 Python 3.11 独立环境成功广播 `190a`。早期通用驱动只得到主机发出的 HCI 指令，尚不能证明无线正常。按精确硬件 ID 补齐主板官方签名 Realtek 驱动后，现成 Bleak 扫描由 0 个设备变为 14 个；iPhone 随后成功发现、连接并通过 nRF Connect 完成设备信息交换。微软 BTVS 1.14.0 / Wireshark 4.6.9 提供真实请求与通知证据。Windows 会使用空中随机地址，日志中的适配器地址不能当作当前空中地址。

Python 3.11 环境避开 Bless 的 Python 3.13 / WinRT 依赖冲突；缺失的 pysetupdi 依赖使用固定上游提交补装，没有修改库。Windows 入口最初复用 BTCP 设备信息逻辑，现已增加 B5 SIMPLE，通过现成 WinRT 定向通知并核对发送结果。Bless 不提供写入者身份，且可能先确认 ATT 写入，因此实验仅支持单订阅客户端，拒绝业务请求不能等同于返回 ATT 错误。Android 代码会按设备名称选择型号及服务；iOS 是否使用相同规则尚未知。Bless 改广播名会写注册表并重启蓝牙，测试需保存原始值并恢复。

早期 `--keep-name` 的库内刷新未立即改变空中名称。关闭 Bless 独占句柄、用 Windows PnP 工具重载精确适配器、再以新进程启动服务，已实测广播 `Keep B3 Lab`；退出后恢复原注册表状态再重载成功。仅恢复注册表不能证明实时名称已恢复，仍需抓包核对。iOS 系统设置的蓝牙列表不是完整 BLE 扫描器，实际对照使用 Nordic nRF Connect。

正确名称广播下，iPhone Keep 仍报告搜索不到。通过现成 pymobiledevice3 11.55.0 的进程过滤日志确认：Keep 权限为 AllowedAlways，发送扫描请求；bluetoothd 在搜索窗口反复发现含 `180a/190a` 的可连接 `Keep B3 Lab` 广播；两轮记录向 Keep 会话交付 2200/1965 条广播，并约 25 秒后由 Keep 主动停止。计数不是目标设备回调数量，不能证明每条目标进入了应用回调。当前采集过滤范围也不能排除网络校验。故问题已经缩小到结果交付或应用识别规则，仍不能断言缺失厂商数据、MAC 格式或服务器白名单是根因。

已核对 iPhone Keep 为 9.1.110 / build 50682，与当日中国区 App Store 返回一致。正常 USB 接口允许读取共享 Documents，但不提供完整应用容器；指定离线网页资源目录及清单为空，没有可用于补齐原生发现规则的程序包。后续取得的 22 个 Android 运行时 DEX 已补齐手工添加、绑定检查及回调实现，但不能将 Android 规则直接套用于 iOS。

Android 真机验证使用官方 Keep 9.1.120 与 Windows B5 原型。重新通过官方 nRF Connect 扫描当前广播地址，正常连接并发现 `190a`，断开 nRF 后再由 Keep 连接，App 显示“绑定成功”和“继续设置”，随后进入“我的手环 / Keep B5”设备页。此前反复连接失败使用了旧的 nRF 扫描缓存地址，不能据此认定协议被拒绝，或推断必须更改地址类型。初次仅绑定时显示的“正在同步数据”不证明活动已导入；后续提供 SPORT44 后，抓包确认完整传输，活动详情显示设备来源。Windows 管理的广播地址在重启后可能变化，当前仍需受控解绑、重新扫描及绑定，不能宣称稳定自动重连。原始截图及地址只保留在仓库外。

BlueStacks 的 ADB 只读核实发现 BLE/HAL 声明，但当前客体没有可用的 HCI、`/dev/vhci` 或 USB 蓝牙入口。BlueZ btproxy、Bumble 与 bluebinder 均有各自的控制器前置条件；ADB 隧道不能自行补出这些条件。有限上游检索未找到能直接接入本实例的成品桥，保留该已登录实例用于 App 研究，尚未修改 HAL、内核或 root。

后续核对 Microsoft 文档与 Bumble 0.0.236 实现：WinRT Publisher 保留 LocalName 和 Service UUID 等广告类型，GattServiceProvider 可发布服务但没有独立自定义广播名参数；Bumble 没有 WinRT 后端，Windows USB HCI 路线通常需要关联 WinUSB。避免改动现有电脑蓝牙的候选为独立 **nRF52840 DK（PCA10056）+ 官方 Zephyr HCI UART + Bumble serial**，Bumble 官方将该板列为兼容硬件。更小的 **nRF52840 Dongle（PCA10059）** 有 Zephyr 官方 USB CDC ACM 配置和出厂 USB DFU 支持，可经 Windows 自带串口驱动接入；这一具体组合尚未构建或实机验收。现有探针已接受通用 transport 参数，无需另写蓝牙栈。这两种硬件都只补无线连接，不会补出 Keep 绑定与历史同步协议，当前无需先购买才能继续静态核实。

其他路线也作了有界核实：

- MuMu 官网当日版本为 6.8.11，雷电为 14 系列。MSA 文档列出了特定版本支持，但未找到足以确认当前 Windows x86 版本的 Hyper-V 共存、BLE/HCI 或 Netsim 通路的官方依据；没有安装 MuMu 或雷电。蓝牙手柄输入映射不能当作 Android BLE 透传。
- 用户提示后找到本机已有 NoxPlayer 7.0.6.2 并实际启动。窗口停在 95%，提示“虚拟机启动失败”并提供“关闭 hyper-v”按钮；日志有 `vm start failed error_code:187`。用户确认该实例不可用。没有点击关闭 Hyper-V、没有修改虚拟化设置，现有夜神实例已退出。其已下载镜像配置为 32 位，未进入 Android，尚不能核实 ARM64 APK 运行能力。
- BlueStacks 官方明确说明 5.20+ 支持开启 Hyper-V 的 Windows x86 环境，因此安装了 5.22.290.1031，安装器及主程序的 Now.gg 数字签名有效。首次新建的 D 盘实验实例出现客体磁盘 I/O、JBD2 及 kernel panic；经官方卸载流程移除该空实例，重建到 C 盘后观察超过 19 分钟未重现。此结果不能推出 D 盘硬件故障。整个过程保留 Hyper-V，未重启主机。新 Pie64 的原签名 Keep 9.1.120 首次同意隐私时仍发生 MSA JNI 异常；保留同意后 force-stop 并冷启动，主进程持续存活 5 分 46 秒，无新增崩溃或 ANR，登录方式切换和空白输入框聚焦均通过。窗口留给用户登录，未输入凭据。后续认证及 MSA 相关功能尚未验证；BlueStacks 官方明确不支持蓝牙，不能替代 BLE 同步验证。
- `lhns/android-arm-tcg` 的固定提交 `f9eecf6c0d2fcc1e255b5a6d7322b07cbe017ba9` 只提供部分自动化。稳定进入系统所需的框架 OAT 补丁仍要求逐镜像定位，仓库未提供完整可执行补丁；具体 App 安装/运行也不在其保证范围内。没有移植 Linux 偏移或修改系统二进制。为核实备用条件曾后台启动已有 Docker Desktop，但没有拉取、构建或运行实验容器。

当前已建立“Android 真机官方 Keep 正常运行 + Windows B5 绑定、整文件传输及有效设备来源活动”的验证基线，无需先解决模拟器兼容问题才能继续。当前候选已计入统计，重开 App 后仍保留且无重复；独立服务器重读、断线重连后的再次同步和两端验收尚未完成。

### iPhone 与网络工具的实际状态

Apple Devices 已通过微软商店安装，USB 设备通信已恢复，并由 pymobiledevice3 11.55.0 复用既有配对完成 Keep 定向版本查询。此前驱动曾报告等待重启，但后续工具已成功通信，不能继续将其作为当前阻塞。没有执行手机备份、恢复、更新或开启开发者模式。

使用 pymobiledevice3 自带 `pcap --process Keep --count 100` 进行了限定进程的网络捕获尝试，最终文件为零字节，未得到可解析证据；本次捕获及子进程已停止。它采集网络包，不是蓝牙抓包，也不能自行解密 HTTPS。

mitmproxy 12.3.1 已在独立环境安装，内置保存过滤器的 21 项离线检查通过。另短时启动仅监听本机回环的代理，用显式信任实验 CA 的电脑客户端访问 Keep 公开帮助接口，得到 HTTP 200、TLS 校验成功；不在运动/设备保存范围内的请求没有写入捕获文件，代理随后停止。此结果只验证电脑侧工具链：未配置系统、模拟器或手机代理，未在设备上信任 CA，也没有取得 Keep App 的 HTTPS 明文。APK manifest 未声明 `networkSecurityConfig`，不能因资源目录中存在同名空配置就认定它信任用户 CA；证书固定及自定义网络栈仍待验证。

## 来源身份的已知实现

以下路径相对于本次 JADX 输出 `dex9-decoded/sources/`；结合上面的 APK 哈希可复核。行号属于本次工具输出，其他反编译版本可能变化。

| 位置 | 观察 | 限制 |
|---|---|---|
| `jj0/a.java:36` | 根据已连接设备类型选择 `KEEP_WATCH` / `KITBIT` | 属于 Keep 自有设备路径 |
| `jj0/a.java:52` | `setSource(OutdoorVendor.VendorSource.KEEP)` | 不会因为设备广播名称不同就自动进入第三方活动路径 |
| `jj0/a.java:58` | 设置设备型号；下一行 manufacturer 为 `Kit` | 这里的设备元数据不是 FIT 文件中的厂商号 |
| `jj0/a.java:92` | 构造 `TrainingLogVendorData("Keep", "Watch"/"Kitbit", model)` | 只证明这条客户端构造路径 |
| `tr/x.java:204` | 用 `VendorSource.THIRD_PARTY` 判断第三方活动 | 不证明客户端可任意指定、服务器会信任该值 |
| `yr/b.java:61`、`tt0/a.java:180` | 本地摘要另有 `sourceType` 持久化与筛选 | 与活动 vendor、文件元数据不能混为一个字段 |
| `g00/f.java:8` | 列表状态 `import` 映射为 `data_import`；`unauthorized` 映射为 `expired` | 属于第三方列表状态映射，不能直接等同详情页的最终来源文字 |
| `tv/o.java:28` | 第三方列表模型含图标、名称、类型、schema | 具体值、赋值链和当前账号返回项仍需运行证据 |

需要继续区分四层：文件内部设备元数据、手机连接设备的身份、第三方账号授权身份、Keep 保存的活动来源。更改第一层并不能据现有证据推出第四层会改变。

登录后已从正常 UI 核对“添加智能装备与应用”目录：华为运动健康、Garmin 佳明、COROS 高驰、小米运动健康、OPPO 健康、vivo 健康、Suunto ZH、荣耀运动健康、轻牛健康、好体知、其他心率设备、Polar 博能、宜准运动、运动数据文件导入及 Zepp。它们是 15 个入口，并非 15 个已验证可传完整跑步历史的云平台；未进行第三方授权。手环型号页含 B6、BC+、B5 Lite、B5、BC、B4 Lite、B4、B3、B2、B1，手表页显示 Keep Watch Pilot 1。装备展示目录与这个原生连接目录需区分。

## 已定位的 HTTP 契约

以下是最新 APK 中 Retrofit 接口声明，GET/POST/Body 混淆注解已核对。路径是相对路径；本次尚未确认实际基址和完整线上请求。活动上传的部分会话编码与签名逻辑已定位，见下文，但并非已经恢复完整契约。

| 方法 | 路径 | 类型与作用范围 |
|---|---|---|
| GET | `account/v3/thirdpartyclient/linked` | 返回 `ThirdPartyLinkEntity`，第三方连接列表 |
| GET | `feynman/v3/thirdparty/log` | 返回 `CloudOutdoorEntity`，第三方记录列表 |
| POST | `feynman/v3/thirdparty/log/opt` | Body 为 `CloudLogOptParam`；具体操作、字段及语义未恢复 |
| GET | `feynman/v3/thirdparty/log/auto/upload/config` | 返回 `ThirdPartyAutoUploadConfig` |
| POST | `account/v3/thirdpartyclient/auto/upload/config/save` | Body 为 `ThirdPartyConfigParams`，配置保存 |
| GET | `account/v3/connect/garmin/append-scope-guide` | 返回 `GarminDataGuideDialogEntity`，Garmin 授权范围引导 |
| POST | `/pd/v5/sportlog` | Body 为 `OutdoorActivity`，返回 `KeepResponse<SportLogResponseEntity>`；可见活动上传声明 |
| GET | `pd/v3/runninglog/{logId}` | 查询参数含 `source`，返回 `OutdoorLog`；跑步详情读取 |

证据位置：`zq/j.java:181`、`:335`、`:341`、`:527`、`:569`；`zq/a.java:194`；`zq/e0.java:28`；`zq/l0.java:231`。

**不能把 `log/opt` 当作任意 FIT 上传接口，也不能自行补出 `source=garmin` 等请求字段。** 源码中的枚举名不一定等于线上 JSON 值；客户端携带身份字段不意味着服务器接受任意值。

`/pd/v5/sportlog` 值得与正常活动样本对照，但目前没有证据证明它接受第三方来源声明。详情 GET 的 `source` 是查询参数，不能当成修改来源的接口。

现阶段缺失：完整请求 DTO、账号绑定与活动来源的关联、合作方数据进入 Keep 的方向、重复记录规则、允许导入的活动类型，以及最终详情中来源图标/文字的生成位置。

### 上传不只是普通 JSON

`/pd/v5/sportlog` 带 `EnableEnigma` 注解。可见 `wq/c.java` 的拦截器在适用条件下使用当前会话令牌参与编码，将请求体包装为 `enkzip`，并设置 `x-sign`、`x-encrypt-code`；也有对应响应解码。`wq/b.java` 展示签名输入包含请求体、规范化查询参数、路径及编码相关值。

这解释了为什么仅能解密 HTTPS 仍可能看不到明文业务字段，也使“保留官方 App 处理上传”更值得优先验证。静态代码有条件分支，不能推断所有接口都启用、服务器强制程度或仅凭捕获头就能重放；本轮没有复现其编码算法。

Kitbit 专属接口还包括 `POST kitbit/v1/upload`（`KitbitDataParam`）及 `POST kitbit/v1/sync/status/{status}`。`upload` 的名称不足以证明它上传完整跑步轨迹。后续恢复的历史运动转换与上传调用链已连到 `/pd/v5/sportlog`；端点来自静态代码证据。真机已有设备来源活动详情，但尚未独立捕获此次 HTTP 请求。

## 蓝牙协议与模拟器能回答什么

### 运行时代码与首条应答

原始 APK 的定向 JADX 缺类后，使用 Android 官方 `am dumpheap`、`hprof-conv` 与 Eclipse MAT 查询 `Class → DexCache.dexFile`，并用已加载类的 classDef/type 索引和 DexFile cookie 交叉定位。每次重启都重新取快照，旧进程的指针不能复用。

官方 NDK LLDB 曾成功读取一个普通匿名 DEX，但其中没有目标类；后台进程在附加时出现 SIGKILL，未确认具体触发机制。最终用系统 Toybox `dd` 定点读取已经定位的 DexFile 对象及 DEX 头，再按头内 file_size 读取单一代码文件。没有扫描或导出巨大的未知内存区域，没有编写解壳器或抓包器。

目标 DEX 为 8,514,276 字节，SHA256 `0BBB7A6D3096BEB70C80590C7438DE72D64EE310553DA5882165C1D99E948787`。JADX 取得 `DataFrame`、BTCP 实现、`KitbitCommonDataService`、`Kitbit3FileHelper` 和 `SportPlusDataType`。全文件反编译有 28 项错误；下面结论只引用已检查的完整方法，不把整个产物视为无缺失源码。原始堆、代码文件和运行日志保留在本机实验目录，不进入 Git。

| 契约 | 当前代码证据 |
|---|---|
| 完整无 ACK 应用帧 | `DataFrame.a.a`：A5 A5、control A0、FSN、payload 长度 LE16、payload、CRC LE16 |
| 校验 | `internal.p.b`：0x1021 查表、初值 0，覆盖帧头和 payload；低 16 位小端附尾，与捕获首帧吻合 |
| 首条请求 | `KitbitCommonDataService.i0` 的 raw 参数 03 03；`KitbitBcpDataService.m2` 前置 SID/CID 01 02 |
| 设备信息回复 | 01 02 后接 DeviceInfo protobuf：厂商 1、MAC 2、SN 3、硬件版本 4、固件版本 5、绑定状态 6 |
| 未绑定状态 | 当前方法体：1 → true、2 → false、其余 → null；资源 proto 的“0 未绑定”注释过时 |
| 接收关联 | 按 payload 前两个字节关联请求，随后剥除并解析 protobuf；完整无 ACK 帧不要求回复 FSN 等于请求 FSN |
| BLE 切片 | `DataFrame.k` 将完整协议帧按传输长度切片；原型按 ATT MTU - 3 通知，Bumble 默认 MTU 23 验证通过 |
| 设备绑定原语 | 请求 01 05；回复 BandStatus 的 status=2 被解释为 SUCCESS、1 为 HAS_BIND。早期仅恢复契约，后续原型已实现并支持 Android B5 绑定 |

早期 B3 原型使用自身实验 MAC、LAB 前缀 SN、实验厂商名和版本，只回应捕获到的 01 02 03 03。它拒绝未知命令、ACK、协议分片、错误校验和未订阅写入。独立审查复现了未订阅时静默跳过通知却消耗 FSN 的问题，已在生成应答前检查 CCCD，回归检查确认未订阅没有发送成功日志，随后订阅的首条回复仍为 FSN 0。当前 B5 的状态与历史文件能力见下一节，不能将这个早期限制视为现状。

调试结束已脱离 LLDB、移除本次转发并恢复非 root adbd。Android 15 后续冷启动再次出现 MSA/OAID 及播放器 JNI 方法缺失，原先 force-stop 方法不是可靠修复。Android 12 的原签 ARM64 对照安装成功，但启动即因加固库 EM_X86_64/EM_AARCH64 不匹配而失败，已停止该无登录测试实例。BlueStacks 登录会话保留；它的系统堆导出为 0 字节，不能当作有效快照。Android 16/API36 rev7 独立环境启动和蓝牙正常、原签 Keep 安装及隐私页正常，但同意隐私后及再次冷启动都复现 MSA JNI 异常，已停止该失败对照实例。

### B5 SIMPLE 与 SPORT44

`BandDevice.KeepB5` 配置 `deviceName="KeepB5"`、`deviceType="B5"`，沿用 `190a/0001/0002` 服务与特征。`KitbitBleManager → o0 → i0 → KitbitSimpleDataService` 明确为 B5 选择 SIMPLE，不使用 B3 的 A5A5 BTCP 帧。

SIMPLE 帧头为 7 字节：请求 ID（小端 16 位）、类型/状态、末帧索引、当前帧索引、SID、CID；回复回显请求 ID。CRC16-XMODEM 的输入是 `requestIdLE16 || typeByte || bodyLengthLE16 || SID || CID || body`，结果以小端附在正文后再分片；不能直接对含分片索引的在线帧头计算校验。B5 复用 Kitbit3 绑定流程，成功状态 protobuf 正文为 `08 02`。原型已实现上述传输、持久化绑定/解绑及本次初始化涉及的配置和查询，并通过真实 Android Keep 绑定；未实现完整手环的传感器和提醒功能。

GPS 历史同步选择 B5 有明确调用链依据：`WorkoutSyncHandler.n` 先读取 SPORT（6），仅在 `KitbitVersionCompatUtilsKt.V` 成立时再读 SPORT_PLUS（44，即 `0x2C`）。该条件包含固件门槛为 `0.0.0` 的 B5，不包含 B3/B4。`Kitbit3DataServiceConvert.e` 的旧 SPORT6 转换只确认了配速、心率、步数；GPS_FILE（7）虽有枚举，尚未找到常规同步读取它的证据。`GetB3WorkoutLogTask` 的类名不能代替型号能力判断。B5 跑步应使用 RUN（2）；OUTDOOR_RUN（80）在非手表分支映射为徒步，不能按名称直接选择。

当前适配提供一条 SPORT44，以及类型 `1–6、35–37、41–43、45、47` 的已确认空目录，拒绝未知类型。`06/01` 列目录，`06/02` 按偏移读文件，`06/03` 和 `06/07` 处理批量/单条删除。实验将 SPORT44 删除请求解释为接收确认，原子保存接收标记并从待传队列隐藏，保留原文件；空目录的批量删除不生成该标记。标记本身不证明 Keep 已解析或上传活动。文件读取单次最多返回 512 字节，由客户端按实际长度继续请求。内容摘要生成 UUID 的方式已被本次真机传输接受，仍不是完整硬件标识或去重契约。

离线验证覆盖 SIMPLE 校验与通知分段、SPORT44 文件头/描述区/CRC、目录和偏移读取、接收标记及保存失败、Bumble LocalLink 和 Windows 通知路径。真机较长通知对照未推进到后续偏移；B5 回复改按 `min(客户端上限, 244)` 分片后，连续 7 次读取完成 3280 字节。前 6 块各 512 字节，对应通知长度 244、244、50；末块 208 字节。每块 CRC、状态、内容以及重组文件 SHA-256 均核对通过，随后观察到 `06/07 type44` 及成功回复。原型仍只支持单帧、无 ACK 请求，未实现请求重组；此次成功不能外推到任意 MTU、重试或恢复场景。

### 标准心率路线

`hn0/g.java` 使用服务 `0x180D`、特征 `0x2A37`、通知描述符 `0x2902`，发现设备后构造 `HeartRateType.THIRD_PARTY` 模型，并订阅和解析心率。

可用 Google Bumble 现成 `heart_rate_server.py` 加 Android Emulator Netsim 验证扫描、连接、订阅、心率显示。这个实验可验证“被 Keep 识别为第三方心率设备”，不满足历史跑步来源目标，故不作为首个开发任务。

Google 文档要求 Emulator 33.1.4.0 或以后；旧 `android-emulator` transport 已过时，应使用 `android-netsim`。纯 Netsim 是虚拟无线链路，不能替代 iPhone 或真实射频验收。`bumble-hci-bridge` 可桥接 USB 控制器，但属于高级、可能不受正式支持的用法。

### Keep 私有历史文件路线

APK 自带 `file_transfer.proto`，同时存在 `GetB3WorkoutLogTask`（`so0/c.java`）调用链：读取普通/plus 运动文件，转换成 `KitbitWorkoutLog` 并关联文件 UUID 和类型。因此历史文件能力不只是孤立字符串；实际读取哪一种文件受上一节的型号条件限制。

实际解析实现中，`ei/u.java`（SportPlusDataBody）按 tag、两字节数量和元素长度解析数据，分支包含距离、公里配速、实时步频、步幅、GPS/GPS_NEW；`ei/g.java`（GpsPoint）使用小端读取数值。运行时代码已恢复 SportPlus 枚举、65 字节 GPS 的关键单位及 WGS-84 → GCJ-02 转换，详见当前结论。原型据此实现 B5 SPORT44 编码；单改逐点配速未解决无效问题，补齐分段后的本次候选已成为有效设备来源活动。

文件传输外层可使用现成 protobuf 工具，但 SportPlus 正文是自定义二进制，不能靠 `.proto` 自动补全。`iy1/a.java` 确认两字节数量为小端。恢复的枚举确认 GPS=8（65 字节）、DISTANCE=9（4 字节）、REAL_TIME_PACE=10（2 字节）、REAL_TIME_SPEED=11（4 字节）、REAL_TIME_CADENCE=12（1 字节）、GPS_NEW=31（6 字节）。已确认的 65 字节 GPS 契约不能外推为 GPS_NEW 或独立速度段也已完全恢复。

`Kitbit3FileHelper.n` 实际请求 `GetFileReq(uuid, offset, len=2048)`，按返回的 fileData 长度推进，要求 File.status=0。它区分普通文件头、尾置文件头和可变长度 SportPlus 描述区；因此不能统一照搬旧注释里的 36 字节描述。文件级 CRC 与传输层 BTCP/SIMPLE 校验相互独立，仍需结合真实活动验证整个载荷。

早期为排除只反编译 `classes9.dex` 造成的遗漏，对原始完整 APK 的 9 个 DEX 使用 JADX 逐类查找：BandDevice、KeepHeaderType、SportPlusDataType、KitbitCommonDataService、Kitbit3FileHelper、WorkoutLog 及相关混淆类共 9 项均返回 `Input class not found`，而 `di.a` 阳性对照成功并注明来自 `classes8.dex`。这确认的是原始加固包的静态缺类边界；后续运行时 DEX 已补齐相关实现。内存不足的失败尝试未计入缺类结论。

公开检索取得 Keep 官方 MIT 库 [Taira](https://github.com/Keep-Tech/Taira/tree/8aef16cbf4c462ca80e7946413c3eac2e92bf0fd)，它提供通用二进制序列化能力，未提供完整 B3 绑定或历史同步实现。其默认大端序不能覆盖本 APK GPS 解析器明确使用的小端序，也不能推出缺失的帧头或 SportPlus 枚举值。检索到的其他 linkprotocol 分包实现尚无 B3 调用链证据，未移植到原型。

JADX 定向取得的 `classes8.dex` 中 `di.a`（BandConst.kt）第 62–88 行给出服务 UUID `0000190a-0000-1000-8000-00805f9b34fb`，以及 `00000001-0000-1000-8000-00805f9b34fb`、`00000002-0000-1000-8000-00805f9b34fb` 两个特征。后续型号配置和真实交互已确认 B3/B5 使用这些 UUID，方向为 `0001` 写入、`0002` 通知。

| 契约片段 | 已知内容 | 尚未明确 |
|---|---|---|
| 设备信息 | 厂商、MAC、SN、软硬件版本、绑定状态；Android B5 本次绑定通过 | 独立服务器重读、重启恢复及其他身份的接纳范围 |
| 登录消息 | `account`、`password` 字段 | 值的来源与算法；不能认为是用户 Keep 密码 |
| 文件目录 | UUID、文件字节数；单条 SPORT44 队列、已确认空目录及接收标记已用于真机同步 | 完整生命周期与云端去重 |
| 文件请求 | 真机请求 2048 字节，按实际返回的最多 512 字节推进，已完整传输 3280 字节 | 请求分片、重试和恢复 |
| 文件类型 | B5 先读 SPORT `0x06`，再读 SPORT_PLUS `0x2C`，后者已在线接收；GPS `0x07` 仅见枚举 | 不能据 GPS 枚举认定 B3 会同步 GPS |
| 完整性与 GPS | 文件 CRC、65 字节 GPS 及完整传输已核对；本次分段修正候选有效且计入统计 | 服务器判定公式及全部字段的独立持久化核验 |

原始注释有“data description 36 bytes”和后续字段表长度不一致的问题，不能照抄成实现。仅凭 FileData 注释不能判断历史读取上限；新取得的 `Kitbit3FileHelper.n` 调用才证明当前历史请求 len=2048，这也不是单个 BLE 通知的长度。

这条路线的来源构造是 `KEEP`，符合用户最终接受 Keep 手环/手表的范围。运行时代码已将历史文件任务、设备来源工厂、运动转换和 `/pd/v5/sportlog` 上传连成静态调用链；真机已显示有效的“Keep 手环 B5”活动并计入统计。该结果已经超过文件领取或详情展示层；但没有独立 HTTP 抓包和服务器重读证据，不能宣称已恢复服务器全部契约。

### 无效活动与配速修正

19:00 旧样本完整传输后，活动显示 1.00 km、06:51、平均配速 06′51″、162 spm、步长 0.90 m 和原轨迹；热量由源数据 57 kcal 变为 78 kcal，与无心率时客户端可能重算的路径相符，但未独立核验此次重算过程。无效提示为“平均配速超过当前人类最高纪录”。

`PaceUtils` 使用时间差毫秒除以距离差米，数值为秒/公里；`KitbitWorkoutLogUtils.s` 将 GPS @44 原值转 long 写入 `currentPace`。原型此前把此处留为 0，现改用 `1000 / 源速度(m/s)`，零速度使用无值 0。摘要仍按 411 秒 / 1000 米得到 411 秒/公里；上传 serializer 会删除 aggregate `averagePace` 等字段，却保留编码后的点数据，因此界面平均配速正确不能证明服务器使用了同一个字段判定。

分段契约补查更正：KM_PACE（tag 1/40）进入 `kmDurations`，SINGLE_PERIOD_PACE（tag 21/44）进入段配速，SINGLE_PERIOD_DISTANCE（tag 20）为段距离。此前仅查看 `KitbitWorkoutLogUtils.l()` 的空数组返回分支，遗漏了先执行的 `h()`。`h()` 在 `摘要距离/1000 == 已有段数+1` 且剩余秒数为正并小于 32767 时，会只补公里时长。旧样本 1000 米/411 秒和空数组因此变为 `[411]`；`l()` 再因缺少段配速和段距离而填 0。`K()` 既找不到 crossKmMark，也找不到累计距离达到 1000 米的点，最终产生配速 0、累计距离 0、累计时长 411 秒的分段。故“该 GPS-only 样本不会生成零分段”的旧结论不成立。

20:00 新样本保持全部源坐标、速度、距离、步频、高度和相对时间。字节差异仅为绝对时间平移一小时、逐点配速及 CRC；点配速为约 406.50–515.46 秒/公里。真机数据页显示平均 06:51、最快 06:46、合理范围的配速曲线及 150–172 spm，支持客户端已正确读取新字段；但仍提示“平均配速超过当前人类最高纪录”。单独补齐点配速未解决问题，不能将原来的零值认定为唯一原因。

对原数据绘图并逐段核算：49 点的时间差为 7–10 秒，坐标球面距离合计 914.612384 米，与源累计距离逐段吻合；原速度按实际时间作梯形积分为 914.985 米。坐标距离/时间的速度范围为 1.9425–2.5853 m/s，最快约 6:26.8/km，没有异常高速。与末点 speed 的平均绝对差为 0.0846 m/s、最大 0.2660 m/s；最大相邻点配速变化约 49.73 秒/公里，不能称为完全平滑。摘要距离比坐标累计多 85.39 米（8.54%），对应摘要配速 6:51 与坐标总配速约 7:29.37 的差异。图表和逐段数据只保存在私人实验目录，未平滑或改写轨迹；尚无服务器判定证据，不能据此断言摘要差异就是无效原因。

分段编码现已补齐：固定使用 V2 tag 40（段秒数）、43（段间隔秒数）、44（秒/公里配速）的 int32 LE，以及 tag 20（段米数）的 int16 LE，四数组长度一致。21:00 样本分别为 `[411]`、`[411]`、`[411]` 和 `[1000]`，新增 26 字节，总长 3306 字节；与 20:00 样本相比，其他差异仅为绝对时间平移一小时及 CRC。所有源点、速度、步频、累计距离和摘要指标均保留。客户端分段变为 411 秒/公里、1000 米、411 秒；真机列表显示“Keep 手环 B5”、1 km、411 秒且无无效标记，总里程、次数和时长分别增加 1 km、1 次和 411 秒。

三组对照构成了本次根因证据：19:00 缺点配速和完整分段时无效；20:00 只修正点配速仍无效；21:00 保留同一轨迹、速度和摘要并补齐分段后有效、计入统计。结合恢复出的 `h() → l() → K()` 调用链，支持零配速、零距离分段是本次故障根因。尚未取得服务器判定公式与阈值，也未单独对各段字段逐一消融；结论限定当前 Android Keep 9.1.120 与该候选，不能外推为所有格式或活动均已兼容。

重开 Keep 后，21:00 活动仍存在、无无效标记，统计维持首次增加后的值，未新增重复活动；首次领取后同轮再次查询 `06/01 type44` 已返回空目录。活动持久验收通过。另一次进入设备页则显示连接失败，原型进程仍运行但没有新通知订阅；本轮未重新抓包扫描地址，因此保留稳定重连未通过的结论，不把它认作本次无效修复失败，也不宣称断线后的完整再次同步已验收。

一般多公里记录的段数取摘要公里数向上取整；中间边界按 `K()` 的同一规则，选线整数累计距离首次达到该公里的 GPS 点，段秒数和米数用相邻边界增量。未命中的最后一段使用原摘要收尾，配速按 `段秒数×1000/段米数` 取整数。若最终公里被非末点命中、GPS 超过摘要、缺少非末公里边界、段时长/距离非正或字段越界，则明确拒绝编码。完整实验回归为 389 项通过、5 个子测试通过；这证明编码与本地行为，不替代服务器有效性验收。

设备身份还涉及服务器：`zq/b0.java` 声明 `bindCheck(sn, mac, kitSubType, firmwareVersion)`、`bind(mac, sn, kitType, firmwareVersion)`、`keygen(seed, kitSubType)` 和设备连接上报。本次没有绕过 App 直接调用这些接口；官方 App 的 B5 绑定界面已成功，但一般性的序列号校验、密钥用途、活动来源覆盖规则仍未知。其中 `bind` 虽声明为 GET，语义是修改绑定关系，不能作为只读探测。

## 实际验证方案与退出条件

### 主方案：让官方 App 处理虚拟设备的历史记录

目标链路如下；虚线表示仍待验证的衔接：

```mermaid
flowchart LR
    A[CampusRunning 跑步数据] -->|离线编码已验证| B[SPORT44 适配与 Windows B5 原型]
    B -->|绑定和整文件传输已通过| C[Android 真机官方 Keep]
    C -->|已显示 Keep 手环 B5| D[设备来源活动详情]
    D -->|本次候选有效并计入统计| E[有效设备来源活动]
    E -->|重开 App 后保留且无重复| F[本次持久验收通过]
    F -. 稳定重连与 iPhone 待完成 .-> G[跨平台日常使用]
```

1. **保留已通过的运行基线。** 使用 Android 真机官方 Keep 9.1.120 与 Windows B5 原型，记录当前广播地址、连接及绑定步骤。真实绑定已通过，模拟器兼容性不再是继续历史同步验证的前置条件。
2. **保留已通过的文件传输。** 本次初始化配置、244 字节通知分片、完整文件读取和确认/删除已有真机证据。继续用现成工具核对新请求和恢复路径；不把一次成功外推为完整手环兼容。
3. **保留三组对照与复现路径。** 21:00 样本补齐完整段时长、距离和配速后，无无效标记并计入统计。复现入口是现有 `history.encode_workout(ExportData)`，再将生成文件传给 Windows B5 的 `--workout` 参数；调用示例见[实验说明](../../experiments/keep_device/README.md)。无需新增 CLI 或修改主应用导出器。保留原轨迹和样本，以后续候选单独扩展验证范围。
4. **保留已通过的持久验收边界。** 重开 App 后记录、来源和统计保持，未新增重复活动；首次领取后的同轮目录查询为空。独立服务器重读及断线重连后的再次同步仍需后续验证，不能把它们写成本轮已完成，也不因此否定本次有效记录修复。
5. **分别验收两端。** Android 真机上传成功后，验证同一记录能在 iPhone 正确显示；若要求 iPhone 也直接连接电脑虚拟设备，再独立测试 iOS 绑定、同步和上传。前者不能代替后者，当前 iOS 直接绑定尚未通过。

本次 B5 身份、文件接收、设备来源、候选有效性和重开 App 后保留已经通过真实 App 验证，活动也计入统计；稳定恢复和 iPhone 路径仍有缺口。当前结论足以证明 Android 路线可行，不代表已具备两端正式发布能力。Bumble 提供 BLE 基础能力，不自带完整 Keep 手环仿真。研究工具继续复用现成项目，不自写抓包、解壳和通用协议分析工具。

有限检索未找到可直接复用的 Kitbit/B3 历史同步模拟器。Gadgetbridge 的“Keep Health”页面对应 LIGE/C60 设备，不能当成 gotokeep 的 Keep 手环支持；qdomyos-zwift 的 Keep Bike 实现也不能替代手环协议。此结论只覆盖本次检索范围，不代表不存在其他实现。

### 备选：用现有授权平台验证来源传递

先在最新版 Android Keep 的第三方连接列表中确认当前账号实际支持的平台，再选择支持接收运动文件的平台作为候选。Garmin 有当前 APK 的授权接口证据，适合优先检查，但尚不能承诺它会把手动导入的 FIT 转发给 Keep。

通过模拟器和现成 HTTP 抓包工具（mitmproxy、HTTP Toolkit 或 Charles）采集三组对照：

1. **文件导入记录**：用户已经确认可用，作为来源显示的基线。
2. **正常第三方同步记录**：来自已授权平台，确认其在 Keep 中的真实来源标识、活动详情和同步过程。
3. **手动导入候选平台的测试记录**：验证平台是否接收、是否向 Keep 发送、Keep 是否保存，以及来源最终怎样显示。

重点跟踪第三方列表、授权状态、待同步列表、操作请求和最终活动详情。合作方到 Keep 的传输可能发生在服务器之间，手机抓包未必能看到其全部过程，应使用平台侧记录和 Keep 侧最终记录交叉验证。

如果对照 2 成功、对照 3 不出现，就不能把“FIT → 合作平台 → Keep”作为可用功能。继续区分转发规则、时间范围、历史回补限制和来源过滤；没有证据前不要靠修改品牌元数据宣称解决。

验收至少要求：重开 Keep 后记录仍存在，日期/GPS/距离/配速/步频正确，来源稳定显示为实际合作来源；同一记录在 Android 与 iPhone 均核对通过。不能只以 HTTP 200、上传完成提示或本地详情页面变化为准。

### HTTP 分支：定位来源字段的完整契约

通过正常设备同步样本追踪来源字段、平台/客户端标识、设备信息、活动 ID 和授权关系。字段名与值以实际响应、序列化实现为准。只有证明直接上传仍满足绑定、编码签名与来源要求，才考虑缩短为 HTTP 路线；不因已找到 `/pd/v5/sportlog` 就跳过这些验证。

加固阻挡静态分析时，使用 REA 支持的运行证据或现成专业分析工具继续定位；不自写解壳器、抓包器或通用协议分析工具。用户授权的设备适配代码只实现已有证据支持的契约。HTTPS 证书信任、证书固定和应用内代理行为均需实测，当前没有证据证明 Keep 使用或不使用某种固定策略。

只有证明当前账号可按完整契约产生目标来源记录，才考虑加入 CampusRunning；仅找到 `THIRD_PARTY` 字符串、设置函数或旧版本脚本不足以开始产品实现。

手机能发现设备、GATT 连接成功、文件传完、生成活动、云端持久化、来源正确，是六个独立检查点。最终目标为 Keep 设备来源即可，不需要把 `source` 改成 `THIRD_PARTY`。

## 跨平台与项目改动范围

主方案当前使用 Android 真机与 Windows B5 完成协议验证，同账号在 iPhone 显示本次活动尚需另行检查；两端直接蓝牙连接电脑需要独立验收。账号同步备选若通过，主要数据传递发生在平台与 Keep 之间，也需核对两端授权和显示。Android 绑定和活动创建成功不算 iPhone 连接验收。Apple 的官方模拟器运行于 Mac，并要求对应的应用构建；当前 Windows 不能用它代替 App Store Keep 真机测试。

本项目可复用 `ExportData → FitExporter → FIT/ZIP`。目前厂商号是 `255`（development）、产品号 `1`，产品名为 Campus Running Data Generator；没有 Keep 账号绑定或上传模块。不要把网络同步副作用塞进 `BaseExporter.export()`，也不要为了显示品牌而先改现有 FIT 厂商信息。

设备路线应复用已有 `ExportData` / `TrackpointData`，只补已验证设备格式的必要适配；不重写轨迹生成，也不假定设备历史文件就是 FIT。现成工具负责研究及传输验证，编码与传输的最终集成方式在契约完整后确定。若备选平台路线可用，则复用现有 FIT 输出即可。凭据不进入配置模板、生成文件、日志或仓库。

现有 FIT 导出相关 14 项测试通过，覆盖解码、坐标、时间、步频、步幅和聚合。这证明本项目输出结构的既有检查通过，不能证明 Keep 接纳或来源标签正确。新增代码限于独立实验目录，未修改主应用及导出器。

## 来源与后续交接

- [Keep 官网 Android 下载页](https://show.gotokeep.com/app?t=keep_homepage___default&type=android)
- [本次分析的官方 APK](https://dl-android.keepcdn.com/release/apk/keep_keep_homepage___default_9.1.120_09ef3cc8.apk)
- [Apple 中国区版本查询](https://itunes.apple.com/lookup?id=952694580&country=cn)
- [JADX 官方发布](https://github.com/skylot/jadx/releases/tag/v1.5.6)
- [Nordic nRF Connect Android 官方仓库](https://github.com/nordicsemi/Android-nRF-Connect) 与 [4.29.1 发布页](https://github.com/nordicsemi/Android-nRF-Connect/releases/tag/version_4.29.1)：本轮 Android 扫描、GATT 连接及服务发现工具。
- [Keep 官方帮助中心](https://echo.gotokeep.com/help)；[当前 FAQ 数据](https://api.gotokeep.com/babel/v1/helpCenter/question/list)
- [官方自动生成记录说明](https://echo.gotokeep.com/help#/question/5ecf6e3d6dd98b32b139625f)：涉及华为步数、Apple 健康已爬楼层，不能扩展成接受任意 HealthKit 跑步及 GPS 的证明。
- [Google Bumble Android 说明](https://github.com/google/bumble/blob/main/docs/mkdocs/src/platforms/android.md)
- [MSA 官网](https://www.msa-alliance.cn/)；[官方 FAQ v3.7](https://16054554.s21i.faiusr.com/61/ABUIABA9GAAg0vXi0QYolvm5VQ.pdf)：JNI 异常案例需要核对适用条件，不能仅凭异常文字套用修复。
- [Bumble 心率示例](https://github.com/google/bumble/blob/main/examples/heart_rate_server.py)
- [Bumble 硬件兼容清单（固定提交）](https://github.com/google/bumble/blob/34def7f112f970cf1cb46233b8b71d6af1ba9f81/docs/mkdocs/src/hardware/index.md)
- [Zephyr HCI UART 样例（固定提交）](https://github.com/zephyrproject-rtos/zephyr/blob/7cd4b562b30a9bcd76a7288ad90d5e71dd6f87d2/samples/bluetooth/hci_uart/README.rst) 与 [PCA10059 板级烧录说明](https://github.com/zephyrproject-rtos/zephyr/blob/7cd4b562b30a9bcd76a7288ad90d5e71dd6f87d2/boards/nordic/nrf52840dongle/doc/index.rst)
- [Gadgetbridge Keep Health](https://gadgetbridge.org/gadgets/wearables/keephealth/)：对应其他厂商设备，不是本次 Keep/Kitbit 协议。
- [旧 Emulator transport 弃用说明](https://github.com/google/bumble/blob/main/docs/mkdocs/src/transports/android_emulator.md)
- [Windows GATT Server](https://learn.microsoft.com/en-us/windows/uwp/devices-sensors/gatt-server)：物理外设能力需另检查适配器支持，Web 页面不会自动变成 BLE 外设。
- [Windows 广播字段限制](https://learn.microsoft.com/en-us/uwp/api/windows.devices.bluetooth.advertisement.bluetoothleadvertisementpublisher?view=winrt-26100)：LocalName 等字段由系统保留，不能直接用普通 Publisher 覆盖。
- [Bless Windows 服务实现](https://github.com/kevincar/bless/blob/3d639708c373a31de746d5cefe6ab512e3887386/bless/backends/winrt/server.py) 与[适配器名称设置](https://github.com/kevincar/bless/blob/3d639708c373a31de746d5cefe6ab512e3887386/bless/backends/winrt/ble/adapter.py)：需核对系统副作用和写响应语义，不能直接当成 Bumble 的可互换后端。
- [ARM TCG 项目的必需补丁说明](https://github.com/lhns/android-arm-tcg/blob/f9eecf6c0d2fcc1e255b5a6d7322b07cbe017ba9/patches/oat-patches.md#L7) 与[缺补丁时的启动逻辑](https://github.com/lhns/android-arm-tcg/blob/f9eecf6c0d2fcc1e255b5a6d7322b07cbe017ba9/scripts/40-bringup.sh#L57)。
- [Apple 模拟器与真机说明](https://developer.apple.com/documentation/xcode/running-your-app-on-simulated-or-physical-devices)
- [Keep_EDA 2026-11-14 固定提交](https://github.com/rain-lei/Keep_EDA/blob/f1a24dafd2ec13becb84aaa26596d6dcaa533494/README.md)：报告 9.1.110 的文件导入仍可用，只作为历史调研线索；用户已确认该路线不满足来源目标。
- [qdomyos-zwift Keep Bike 实现](https://github.com/cagnulein/qdomyos-zwift/blob/5c52ec0c0178e6beb2e6d21ec21015de650115c9/src/devices/keepbike/keepbike.cpp#L686)：私有单车协议的参考，不是历史跑步来源方案。
- [Garmin Activity API](https://developer.garmin.com/gc-developer-program/enterprise/activity-api/) 与 [FAQ](https://developer.garmin.com/gc-developer-program/enterprise/program-faq/)：说明设备活动经 Garmin Connect 向合作方提供数据，没有证明手动上传 FIT 必定转发给 Keep。

REA 对帮助中心 JS 的父证据为 `ev_7cfa4c4cc32bfe924117bf1a8c1d5d73a878a43951f772edc2629344e3ba7aac`；该证据范围不包含 Keep 全应用。

Android 路线已证明本次候选可导入为有效的“Keep 手环 B5”来源活动、计入统计，并在重开 App 后保留且未重复；零分段修复有三组对照及客户端调用链支持。后续补齐独立服务器重读、断线重连复传、Windows 稳定恢复和 iPhone 验收，再决定主应用集成与发布范围。
