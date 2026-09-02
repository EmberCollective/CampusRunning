---
name: campusrunning-cli
description: >-
    Complete, code-verified guide to the CampusRunning CLI (python main.py)
    for generating Garmin TCX running files. Use this skill whenever the user
    wants to 生成跑步数据 / 生成 TCX / 生成轨迹文件 / 补跑步记录, asks about
    the single / daily / total subcommands or any flag (--track, --template,
    --output-dir, ...), wants to 添加新轨迹或新模板, or hits CLI errors — even
    if they never say "CLI". Do NOT use for Flask web app internals (python
    app.py, web/ routes) or the Keep app import tutorial (guied.md).
---

# campusrunning-cli — CLI 使用指南

> 事实来源：`main.py`（argparse）、`src/`、`config/` 代码阅读 + 实测运行（2026-09）。
> 本 skill 只讲 CLI；Web 应用仅文末一句话带过。

## 需求 → 命令映射

| 需求 | 命令 |
|------|------|
| 补某一天的一次跑步 | `single` |
| 一段日期内每天随机跑 X~Y km | `daily` |
| 一段日期内总计凑满 N km（自动分配） | `total` |
| 查看可用轨迹 / 模板 | `--list-tracks` / `--list-templates` |

## 30 秒上手

```bash
# 在仓库根目录运行。CLI 纯标准库，无需 pip install（README 标称 3.13+，实际 3.9+ 语法均可跑）
python main.py --list-tracks                                                  # 先看有哪些轨迹
python main.py single --date 2026-09-01 --distance 5.0                        # 最小可用
python main.py daily --start-date 2026-09-01 --end-date 2026-09-30 --min-km 2 --max-km 5
python main.py total --start-date 2026-09-01 --end-date 2026-09-30 --total-km 100
```

产物：每个跑步日一个 `YYYY-MM-DD_距离km.tcx`（如 `2026-09-01_5.0km.tcx`），写入
`--output-dir`（默认 `output/`，**相对当前工作目录**，该目录已在 .gitignore 中）。

## 子命令详解

### single — 生成单个 TCX

| 参数 | 必填 | 默认 | 含义 |
|------|:---:|------|------|
| `--date` | ✅ | — | 日期，严格 `YYYY-MM-DD` |
| `--distance` | ✅ | — | 距离（公里，float） |
| `--pace` | | 随机 | 固定配速（分/公里）。指定后不再随机 |
| `--start-time` | | `07:00` | 固定开始时间 `HH:MM` |

共享参数（三个子命令都有）：`--min-pace 7.0`、`--max-pace 8.0`、`--start-time-min 06:00`、
`--start-time-max 08:00`、`--output-dir output`、`--no-track`（不生成轨迹点）、
`--no-correction`（跳过坐标修正）、`--no-pace-fluctuation`（匀速）、`--zip`、
`--track`、`--template`。

```bash
python main.py single --date 2026-09-15 --distance 5.0 --pace 6.5 --start-time 07:30 --track campus_default
```

### daily — 按每日公里数范围

| 参数 | 必填 | 默认 | 含义 |
|------|:---:|------|------|
| `--start-date` / `--end-date` | ✅ | — | 日期区间，两端含 |
| `--min-km` / `--max-km` | ✅ | — | 每日距离抽取范围（**工作日基线**） |

行为：每天 `random.uniform(min_km, max_km)` 取值；**周末（周六日）再 × weekend_factor**（daily 没有对应 CLI 旗标，取自配置 `default_settings.json`，默认 1.5），所以周末文件里的距离会明显大于 max-km，这是特性不是 bug。

### total — 按总公里数自动分配

| 参数 | 必填 | 默认 | 含义 |
|------|:---:|------|------|
| `--start-date` / `--end-date` | ✅ | — | 日期区间 |
| `--total-km` | ✅ | — | 总公里数目标 |
| `--min-daily-km` | | `2.0` | 单日下限 |
| `--max-daily-km` | | `8.0` | 单日上限 |
| `--weekend-factor` | | `1.5` | 周末距离倍数 |
| `--rest-days-per-week` | | `1` | 每周随机剔除的休息日数 |

分配算法（`src/planners/total_km_planner.py`）：按工作日/周末数量算加权平均 →
夹到 [min_daily, max_daily] → 每日 ±20% 抖动 → 剔休息日 → 总偏差 >5% 时整体线性重缩放。
**生成的文件数 < 天数**（有休息日缺口），总里程在目标 ±5% 内。

## 全局参数

| 参数 | 作用 |
|------|------|
| `--list-tracks` | 列出 `config/tracks/*.json` 全部轨迹 ID + 描述，然后退出 |
| `--list-templates` | 列出 `config/templates/*.json` 全部模板 ID，然后退出 |
| `--track` / `--template` | 指定轨迹 / 模板（子命令前后两个位置都接受） |
| `--verbose` / `-v` | 日志降到 DEBUG |

不指定 `--track` 时用 `config/default_settings.json` 的 `default_track_id`（当前为 `campus_default`）。

## 配置优先级

```
CLI 参数  >  模板 generation_config  >  config/default_settings.json 内置默认
```

`--template` 只补齐你没在命令行给的参数，显式 CLI 参数永远赢。

## 轨迹系统（config/tracks/）

- 坐标系是 **GCJ-02（高德）**，不是 WGS-84。从高德地图拾取坐标直接填入即可。
- **`--track` 的值 = 文件名去掉 `.json`**（按文件名查找，JSON 内部的 `id` 字段仅展示用）。
  现有：`campus_default`、`east_campus_stadium`、`gzu_south`、`xiyi_track`（以 `--list-tracks` 实时输出为准）。
- `base_coordinates`：一圈闭合轨迹点（自动闭合首尾、自动强制顺时针方向）。
- `coordinate_correction`（可选）定义平移：`修正后坐标 = 原坐标 + (current_center − target_center)`，
  其中 current_center 是所给坐标的中心、target_center 是实际位置中心。**添加新轨迹时直接填高德实际值，系统自动算偏移，无需手动计算。**
- 字段规格详见 `docs/track_format.md`。

添加新轨迹 = 在 `config/tracks/` 放一个新 JSON（结构照抄 `campus_default.json`），立即生效，无需注册。

## 模板（config/templates/）

- CLI 只读取模板 JSON 的 **`generation_config`** 段，且只认 `GenerationConfig` 已有字段名，
  未知键被**静默丢弃**。
- ⚠️ `config/templates/TEMPLATE_GUIDE.md` 描述的 `daily_config/total_config/single_config`
  多段格式是**旧版格式，CLI 不读取**——别照它写模板。
- 现有：`easy_run`、`long_run`、`interval`、`time_run`、`time_interval`。

## 输出规则与 TCX 细节

- 文件名 `{YYYY-MM-DD}_{距离}km.tcx`，距离保留 2 位小数（如 `3.47km`）。同一日期同距离重跑会**静默覆盖**旧文件；同日期不同距离则两个文件共存。
- 目录不存在会自动创建；默认 `output/` 相对 **CWD**（config/ 则相对 main.py 定位，两者不一致，换目录跑注意产物位置）。
- TCX：Garmin `TrainingCenterDatabase/v2`，单个 `Activity Sport="Running"`；
  时间戳为**本地时间、无时区后缀**；`MaximumSpeed` 硬编码 3.5 m/s；海拔为 ~100 m 模拟值。
- 成功收尾输出：`任务完成！` / `生成的TCX文件: <文件名(single) 或 N个(daily/total)>` / `输出目录: ...` / `包含轨迹: 是|否`。

## 常见坑速查

| # | 坑 | 说明 |
|---|----|------|
| 1 | `--zip` 是 **no-op** | CLI 从不打包 zip（仅 Web 下载接口现场打包）。别向用户承诺 zip 产物 |
| 2 | daily 周末放大 | 周末距离 = 抽取值 × 1.5，总量比预期高是正常的 |
| 3 | 未知 `--track` | 裸 `FileNotFoundError` 堆栈，无友好提示。先 `--list-tracks` |
| 4 | 日期/时间格式 | 必须严格 `YYYY-MM-DD` / `HH:MM`，否则裸 `ValueError` 堆栈 |
| 5 | 模板旧格式 | 见上节 ⚠️；模板未知键静默忽略 |
| 6 | 文档漂移 | `docs/api_reference.md` 的 GenerationConfig 还是旧的 int 小时（实际是 `"HH:MM"` 字符串）；README 链接的 `docs/amap_key_guide.md` 不存在 |
| 7 | `single --pace` | 同时固定 min/max 配速；`--start-time` 固定起止区间，仅秒数随机 |
| 8 | 配速语义 | `--min-pace` 是**最快**（数值小 = 快），别填反 |

## 错误对照表

| 现象 | 原因 | 处理 |
|------|------|------|
| `FileNotFoundError: 轨迹文件不存在: ...` | 轨迹 ID 不存在（按文件名查找失败） | `python main.py --list-tracks` 拿正确 ID |
| `usage: ... error: the following arguments are required` (exit 2) | 缺必填参数 | 补 `--date` / `--min-km` 等 |
| `ValueError: time data ... does not match format` | 日期/时间格式错 | 用 `YYYY-MM-DD`、`HH:MM` |
| `KeyError: 'base_coordinates'` 之类 | 轨迹 JSON 结构缺字段 | 对照 `docs/track_format.md` 修 JSON |

## Web 一句话

`python app.py`（需 `pip install flask`，默认 `0.0.0.0:5000`）与 CLI 共享同一生成引擎、产物完全一致；Web 的 API/路由细节不在本 skill 范围。
