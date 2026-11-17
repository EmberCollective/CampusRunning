# 配速模型、预览与扩展

在生成页的「配速与开始时间」中点击 **预览配速**，可以查看时间曲线和本条样例的配速时间占比。展开「输出方式」下方的「高级设置 / 配速算法」可选择算法及波动强度；模板、CLI 和四种 Web 生成模式使用同一套设置。

预览是算法样例，正式生成重新随机；里程默认取单次里程或当前范围中值，可在预览内修改。预览不生成文件，也不载入设备。分布图按每段实际用时加权，表示本条样例花了多少时间处于某个配速区间，不表示所有跑者的分布或置信区间。页面配速范围控制每次运动的**平均配速**，不限制每个瞬时配速。

## 旧算法的问题与研究边界

- 热身结束时乘数由约 1.10 突然变成 1.00，疲劳阶段也有跳变。
- 最后 10% 每个采样点重新随机选择冲刺或保持，造成交替尖峰。
- 固定正弦波按全程百分比分布，不能表示固定秒数尺度的起伏。
- 平均配速按点数校正，未考虑实际路段长度；关闭波动时按点数均分时间，也不能保证匀速。

参考原始研究（2026-11-17 核对）：

| 原始研究 | 用于本次设计的结论 | 不能据此推出的结论 |
|---|---|---|
| [Selinger 等，2022，Running in the wild: energetics explain ecological running speeds](https://pmc.ncbi.nlm.nih.gov/articles/PMC9169516/) | 4,645 名跑者、37,201 次自由跑步；平均速度与距离的关系不同于竞赛。默认日常模型应允许围绕偏好速度跑步 | 论文的单次平均速度不能确定逐秒噪声幅度或相关时间 |
| [Effects of a 4-week high-intensity interval training on pacing during 5-km running trial](https://pmc.ncbi.nlm.nih.gov/articles/PMC5649866/) | 训练跑者的 5 km 测试可有末段加速；这应是训练情境的选择 | 所有普通人每次慢跑都会冲刺，或每点随机切换冲刺符合真实行为 |

新模型是依据上述边界设计的**模拟模型**，没有用真实逐点轨迹做参数拟合或人群验证。45 秒相关尺度、默认约 2.4% 的随机波动尺度及趋势幅度均为工程参数，不是论文给出的人群统计值。不模拟地形、交通停顿、GPS 测量误差或个人体能。

## 内置算法

| ID | 名称 | 行为 |
|---|---|---|
| `natural` | 自然慢跑（默认） | 平滑进入状态、连续随机起伏、轻微后程变化；末段趋势每次运动只抽取一次 |
| `steady` | 稳定跑 | 围绕平均配速连续起伏，不设固定冲刺 |
| `progressive` | 渐进跑 | 平滑加快的训练样例 |

噪声使用有时间关联的高斯扰动，作用在对数配速上，保证配速为正；不是每点独立抽取高斯配速。相邻点按实际路段长度与目标配速估算的时间间隔更新相关性。强度 `pace_intensity` 为 0–1，默认 0.15；内置算法在 0 时匀速，较大数值仅用于探索，不代表更真实。

每段用时为 `配速（分钟/公里）×路段公里数×60`。系统按实际距离加权归一化，再生成时间戳；最后一个点沿用上一段配速。导出时间保留现有秒级精度，摘要以真实首末点时间为准。

## CLI 与 HTTP

三个 CLI 子命令均支持：

```bash
python main.py single --date 2026-11-17 --distance 3.5 --pace 7.5 --pace-algorithm steady --pace-intensity 0.15
```

生成配置和模板中可保存 `pace_algorithm`、`pace_intensity`。旧模板缺省使用 `natural` / `0.15`；`enable_pace_fluctuation=false` 优先于算法选择。

- `GET /api/pace/algorithms`：已注册算法的 `id/name/description`。
- `POST /api/pace/preview`：JSON 如下；里程限制 0.1–100 km，配速 1–30 min/km，采样密度 50 点/km。`seed` 是 0–4294967295 的整数，仅用于样例复现，不控制正式生成。

```json
{"distance_km":3.5,"pace":7.5,"pace_algorithm":"natural","pace_intensity":0.15,"seed":42,"enable_pace_fluctuation":true}
```

响应包含 `distance_km`、`average_pace`、`pace_algorithm`、`seed`，以及等长的 `times_seconds` / `paces_min_per_km`。非法输入返回 400；预览不消耗主生成流程的全局随机状态。

## 公开 Python 扩展接口

在应用启动前显式注册自己信任的本地 Python 函数。以下是一个只有热身趋势的完整启动样例：

```python
import math
from src.core import PaceAlgorithm, PaceContext, register_pace_algorithm
from web.routes import create_app

def gentle(context: PaceContext, rng):
    return [context.base_pace_min_per_km * math.exp(
        context.intensity * .5 * math.exp(-distance * context.base_pace_min_per_km * 60 / 90)
    ) for distance in context.distances_km]

register_pace_algorithm(PaceAlgorithm("gentle", "缓慢热身", "仅热身趋势的扩展示例。", gentle))
create_app().run(host="127.0.0.1", port=5000)
```

`PaceContext` 是不可变对象：`distances_km` 是每个点的累计公里数，首点为 0；`base_pace_min_per_km` 是目标平均配速，`intensity` 是波动强度。函数返回同样点数的正有限配速（分钟/公里），使用传入的独立 `random.Random` 可保持样例可复现。注册后会出现在页面和算法列表中，也可在同一进程调用生成引擎或 CLI 入口。

ID 仅允许 1–64 个小写字母、数字、下划线或连字符，重复 ID 拒绝注册。输出数量、类型、有限性和正值会校验，系统统一归一化加权平均配速；末点数值由上一段覆盖。接口没有上传代码、按请求导入模块、表达式求值或自动扫描目录的能力。

## B5 边界

实验面板复用上述设置和生成流程。修改不缩放距离字段、不重新转换坐标，不修改 SPORT44 编码或蓝牙流程。原有 `B5Exporter` 仍校验真实末点距离与摘要、首末时间与摘要，并进行 CRC 校验、原子发布和拒绝覆盖。

离线回归覆盖三种算法、关闭波动、强度 0/0.15/1、整公里及部分公里终点，并检查 SPORT44 的四组公里分段数组、点速度/配速单位和步数积分。契约见 [Keep 数据契约](keep-b5/reference/protocol-contract.md)。离线通过不等于官方 Keep 活动有效；新模型尚未进行真实手机同步、云端有效性或 iOS 验收。
