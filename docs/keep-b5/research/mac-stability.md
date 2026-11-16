# B5 广播 MAC 稳定方案调研

调研日期：2026-11-16。范围为现有 Windows/Bless 原型及可复用的蓝牙外设项目；目标是手机仅使用官方 Keep，尽量不改电脑运行环境。

返回[文档目录](../README.md)；本文为方案研究，当前已接入环境及硬件要求见[适配范围](../reference/compatibility.md)，操作见[连接与运行](../guides/connection-and-running.md)。

## 结论

**本次未找到保留 Windows 原生蓝牙驱动、只改 Bless 参数就能固定实际广播 MAC 的公开方案。** 当前较小的变更仍是保留已跑通的 Windows 传输，获取本次实际广播地址；它可以满足用户已调整后的“有当前 MAC 即可”要求。

这不是单纯的 Bless 版本问题：[Bless #107](https://github.com/kevincar/bless/issues/107) 提出了同样的随机地址和当前地址查询问题，维护者在 2025-12-26 回复未找到相应接口，建议由 central 扫描识别设备。[微软维护者的说明](https://github.com/microsoft/BluetoothLEExplorer/issues/14#issuecomment-384726932)明确表示，不允许应用关闭 LE privacy。较旧的回复还须结合当前 API 检查；本次查到的 [GattServiceProviderAdvertisingParameters 属性](https://learn.microsoft.com/en-us/uwp/api/windows.devices.bluetooth.genericattributeprofile.gattserviceprovideradvertisingparameters?view=winrt-26100)仍只有连接性、可发现性、ServiceData 和 PHY 设置，没有地址或隐私开关。

## 现成项目对比

| 项目 / 路线 | 可复用能力与证据 | 对现有原型的实际改动 |
|---|---|---|
| Bless / WinRT | [当前 WinRT 后端](https://github.com/kevincar/bless/blob/92e3501066292b531f2a9c0ea8b664e40e591d82/bless/backends/winrt/server.py#L133)将名称、连接性和可发现性交给 Windows，没有固定地址参数。升级 Bless 不会凭空增加 WinRT 地址控制能力。 | 保留环境时，可做当前地址获取；没有已证实的固定 MAC 小改。 |
| Bumble / 直接 HCI | [Device 实现](https://github.com/google/bumble/blob/34def7f112f970cf1cb46233b8b71d6af1ba9f81/bumble/device.py#L2974)在关闭 LE privacy 时使用配置的随机静态地址，并发送 `HCI_LE_Set_Random_Address`。现有实验入口已经支持显式 `--address`。 | 业务代码可继续复用；但必须先让 Bumble 真正控制物理 HCI。[Windows 官方说明](https://github.com/google/bumble/blob/c2959dadb470b32075173e151aaf34b998802155/docs/mkdocs/src/platforms/windows.md)要求将目标 USB 蓝牙设备关联到 WinUSB，不能与 Windows 原生蓝牙栈同时管理同一控制器。 |
| BlueZ / Linux | [BlueZ 配置](https://github.com/bluez/bluez/blob/26f84a524adbb70c41b9c8243495cd695db22ac1/src/main.conf#L72)有 `Privacy = off`；[管理协议](https://github.com/bluez/bluez/blob/26f84a524adbb70c41b9c8243495cd695db22ac1/doc/mgmt-protocol.rst#L1809)支持 Set Static Address，且说明设置需在控制器断电状态进行。双模控制器通常使用自己的 public identity，静态地址是否生效受控制器模式约束。 | 现成地址控制能力存在，但属于 Linux 管理的物理控制器，需要切换电脑端运行环境并验收广播；不是 Windows/Bless 的配置开关。 |
| bleno / HCI socket | [HCI 实现](https://github.com/abandonware/bleno/blob/4d72805a8cd9433485051d2692cdf7d36ffb7069/lib/hci-socket/hci.js#L276)显式使用 public own-address type。[Windows 安装说明](https://github.com/abandonware/bleno/blob/d419c1bcceeecfe353aa74f85bb33a804b9e8f66/README.md#windows)同样要求 WinUSB / Zadig。 | 没有绕过原生 Windows 的限制，还需迁移现有 Python GATT 对接；相较复用 Bumble，变动更大。 |

单独增加 `BluetoothLEAdvertisementPublisher` 也没有已证实的捷径：[其 `IsAnonymous` 属性](https://learn.microsoft.com/en-us/uwp/api/windows.devices.bluetooth.advertisement.bluetoothleadvertisementpublisher?view=winrt-26100)决定是否携带地址，不选择或固定地址；该对象没有将指定地址绑定到现有 GATT 服务的公开参数。

## 配对和“地址稳定”不是同一件事

微软上述说明区分了三种情况：连接存续期间随机地址不会改变；断开或睡眠恢复后可能变化；已经进行蓝牙配对并交换 IRK 的设备可以解析变化的 RPA，恢复身份识别。**IRK 解决可识别性，不保证扫描时看到的 12 位 MAC 永远相同。**

当前实验的应用层 B5 绑定标志不能证明已经完成系统 SMP 配对或 IRK 交换；不能据此承诺官方 Keep 会自动按绑定身份重新找到变化后的地址。增加加密、配对和密钥持久化也超出“显示当前 MAC”的最小改动，且需要真实 Keep 验收。

适配器 public address、DeviceInfo 中保存的 MAC、操作系统设备 ID 和本次实际广播地址应分别标注。固定前三者不能证明第四者已固定。

## 当前建议与验证边界

当前只实现实际广播 MAC 获取与显示，不切换蓝牙栈、不替换驱动、不修改未经证实的 Windows 注册表隐私项。若以后重新要求跨进程、睡眠及重启后的字面 MAC 都稳定，优先复用现有 Bumble 与实验专用随机静态地址；主要前置条件是可控物理 HCI 和对应固件，而不是再写一套 B5 协议。

本次只核对公开源码、接口文档和项目 issue，没有安装、换驱动、改系统隐私配置或执行真机稳定性测试。未取得官方资料或实测支持的 Windows 注册表开关不列为方案；上述结论也不覆盖所有厂商私有驱动。任何候选仍须用实际广播或 HCI 记录核对地址，并分别验证官方 Keep 的发现、绑定和重连。
