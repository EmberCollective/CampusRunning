# 2026-11-17：重启后添加 B5 立即失败的恢复记录

适用范围：本机 `KeepDevice35`、官方 Android Emulator 37.2.13.0、Android 15 / API 35、Keep 9.1.120、Bumble/Netsim。参见[运行说明](../guides/connection-and-running.md)与[适配范围](../reference/compatibility.md)。

## 直接原因：两端绑定状态不一致

本次 Keep 显示“扫描手环 / 未发现设备”，但原型日志已经出现 `CONNECTED`、通知订阅和 `DEVICE_INFO_SENT`，随后由客户端断开。这个页面不能单独用来判断广播是否存在。

当时 Keep 的装备列表没有 B5，本地 state 仍为 `bound=true`。通过已有 JADX 工具读取此前保存的 Keep 运行时 DEX，确认以下处理链：

1. `KitbitCommonDataService.getDeviceInfo` 将设备信息的 `has_bind=1` 映射为已绑定，`2` 映射为未绑定。
2. `KitbitConnectStrategyFactory` 对 B5 使用 `Kitbit3ConnectStrategy`。
3. `Kitbit3ConnectStrategy` 在添加设备模式下收到“已绑定”，进入 `HAS_BIND` 拒绝分支；绑定完成后的正常重连使用另一条路径。

保留相同模拟器配置复现失败后，停止原型并备份 state，在已核实 Keep 端无 B5 绑定记录的条件下，使用现有 `experiments.keep_device.state --reset-binding` 修正本地残留标记。验证前后只有 `bound` 变化，MAC、配置和运动文件保持原值。再次通过 Keep 正常添加，页面明确显示“绑定成功”。因此本轮握手后立即失败的直接原因是绑定状态冲突。

**不要把重置绑定加入启动流程。** 正常重启须保留 state；仅在已确认 Keep 端解绑、且本地残留已绑定标记时进行受控恢复。不得删除收讫标记来重试。

## 同时发现的环境差异

| 项目 | 本次证据与处理 |
|---|---|
| Android 用户 | 开机后进入用户 0，历史成功环境是用户 11。恢复到原用户后，仍能复现上述状态冲突；用户差异需要纠正，但不能据此宣称已经解决连接问题。 |
| 启动资源 | AVD 默认值为 2 GB / 4 核，与已验证的 3072 MB / 2 核 / software GPU 不同。恢复显式参数。 |
| 原生操作窗口 | 额外冷启动检查中，原生窗口出现 `Failed to load opengl32sw`、回退系统 OpenGL 和崩溃提示。改用已有的无窗口引擎与 scrcpy 后启动成功；未分析原生崩溃转储，不能认定唯一图形根因。 |
| Netsim 端口 | 每次重启重新读取当前 `netsim.ini`，不复用旧端口。 |
| 时区 | 保持 `Asia/Shanghai`，同步前检查客体时区。抽查本批一条新记录，详情时间与生成器的北京时间一致。 |

本次恢复参数：

```text
-avd KeepDevice35 -port 5556 -accel on -gpu software
-memory 3072 -cores 2 -no-snapshot -no-boot-anim -no-audio
-no-window -timezone Asia/Shanghai -packet-streamer-endpoint default
```

`KeepDevice35`、`5556` 和用户 `11` 是本机实验实例的取值，不是其他机器的固定要求。启动后先用 `adb devices -l`、`shell pm list users` 和 `shell am get-current-user` 核对目标；需要时使用 `shell am switch-user <原用户 ID>`。不能为了进入默认用户而重新登录或清理旧用户资料。

使用已有 scrcpy 显示目标模拟器，并通过其 `--serial` 明确选择实例。本次窗口名为 `Keep-Official-Android`。无窗口引擎仍是官方 Android Emulator，蓝牙仍来自 Netsim；scrcpy 只负责显示和操作。

## 本轮验收

| 检查 | 结果 |
|---|---|
| 相同 MAC 重新添加 | Keep 明确显示“绑定成功”，设备页显示“已连接”。 |
| 本批传输 | 43/43 条完整收讫，待同步为 0。 |
| 活动列表与详情 | 多条本批记录显示“Keep 手环 B5”来源；抽查一条详情，时间正确，未见无效标记。 |
| 广播进程停止后再启动 | 保留绑定和收讫状态，Keep 自动重连，待同步仍为 0。 |
| 整个模拟器冷启动 | 使用无窗口参数启动、切回原用户；Keep 中原 B5 保留，打开装备页后连接恢复，无需重新添加。 |
| 收讫文件完整性 | 冷启动前后 43 个收讫文件的 SHA-256 全部相同。 |

上述是一次恢复及有限重启测试，未逐条核验全部活动有效性，也不证明长期稳定、多模拟器隔离、实体蓝牙或 iOS 兼容。原始日志、反编译文件、截图、state 备份及收讫哈希清单均保存在仓库外的私人实验目录。

## 后续启动检查顺序

1. 确认原 AVD、启动参数和 Android 用户，保留 userdata。
2. 确认蓝牙开启、Keep 的附近设备权限和时区。
3. 读取当前 Netsim 端口，复用原 MAC、state、批次和收讫记录。
4. Keep 已有 B5 时进入设备页重连；不要重复走添加流程。
5. 若添加立即失败，先检查是否已有 BLE 连接和设备信息回复，再核对两端绑定状态；不先重装、换 MAC 或清空数据。
