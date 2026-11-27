# Keep B5 适配文档（私有版）

本目录集中保存 Keep B5 的使用说明、协议契约、接口设计与研究记录，代码仍位于 [`experiments/keep_device/`](../../experiments/keep_device/)。这些文档和接入代码仅供私有版使用，不随公开仓库发布。

先读[适配范围与环境要求](reference/compatibility.md)，确认使用模拟器还是实体蓝牙，再按[连接与运行](guides/connection-and-running.md)准备环境。手表面板可选择 Netsim 或 Windows 实体蓝牙，Windows 独立入口也保留。虚拟 MAC 不会被附近手机扫描到；Windows 面板的本机检查已通过，手机联调尚未进行。

| 类别 | 文档 | 内容 |
|---|---|---|
| 使用指南 | [连接与运行](guides/connection-and-running.md) | 原生生成、两条广播路线的面板配置、独立 Windows 入口、批量文件、退出及恢复 |
| 环境与验收 | [适配范围与环境要求](reference/compatibility.md) | 具体模拟器版本、实体蓝牙要求、依赖、已测与未测范围 |
| 协议参考 | [接口及协议契约](reference/protocol-contract.md) | 模块入口、输入单位、SPORT44、文件队列、设备命令与面板接口 |
| 接口设计 | [可替换蓝牙传输接口](design/transport-interface.md) | 传输职责、地址与事件、生命周期、接入验收；现有后端尚未迁移 |
| 研究记录 | [第三方来源与 issue #63](research/third-party-source-63.md) | 逆向证据、方案演进、活动无效原因与验收对照 |
| 研究记录 | [MAC 与重连稳定性](research/mac-stability.md) | Windows 地址限制、固定地址候选及取舍 |

研究记录保留当时结论；当前适配状态以环境与验收页为准。文件领取成功不等于活动有效：仍需在 Keep 核对设备来源、有效性、详情和统计。账号、状态、运动文件及原始实验材料存放在仓库外。
