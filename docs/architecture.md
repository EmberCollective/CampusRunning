# 架构说明

## 系统概览

校园跑步数据生成器是一个用于生成模拟跑步TCX文件的Python工具，支持CLI和Web两种使用方式。

## 核心架构

```
用户输入 (CLI / Web)
    │
    ▼
ConfigManager ──加载──▶ config/*.json
    │                    ├─ tracks/      (轨迹定义)
    │                    ├─ templates/   (预设模板)
    │                    └─ default_settings.json
    │
    ▼
TemplateManager ──合并──▶ GenerationConfig
    │
    ▼
GenerationEngine ◄──┬── Planner (daily/total/single)
    │                │
    │                └── TrackGenerator ◄── TrackAnalyzer
    │                                    ├── CoordinateCorrector
    │                                    └── PaceFluctuator
    │
    ▼
Exporter (TCX)
    │
    ▼
输出文件 (.tcx)
```

## 核心模块

### src/core/

| 模块 | 职责 |
|------|------|
| `__init__.py` | 核心模块导出 |
| `models.py` | 数据模型定义（GeoPoint, TrackDefinition, GenerationConfig等） |
| `track_analyzer.py` | 轨迹分析（Haversine距离、Shoelace方向判定） |
| `track_generator.py` | 轨迹生成（插值、随机偏移、平滑处理） |
| `coordinate_corrector.py` | GPS坐标修正 |
| `pace_fluctuator.py` | 配速波动模拟（热身→稳定→疲劳→冲刺） |
| `cadence_generator.py` | 步频/步数生成（速度→步频映射、Lap 级步数积分） |
| `helpers.py` | 通用工具函数 |

### src/planners/

| 模块 | 职责 |
|------|------|
| `__init__.py` | 规划器模块导出 |
| `daily_planner.py` | 每日范围规划（随机距离分配） |
| `total_km_planner.py` | 总公里数规划（工作日/周末分离） |
| `single_planner.py` | 单文件规划 |

### src/exporters/

| 模块 | 职责 |
|------|------|
| `__init__.py` | 导出器模块导出 |
| `base.py` | 抽象导出器接口 |
| `tcx_exporter.py` | TCX格式导出实现 |

### src/

| 模块 | 职责 |
|------|------|
| `config_manager.py` | 配置加载管理 |
| `template_manager.py` | 模板应用系统 |
| `generation_engine.py` | 生成引擎编排层 |

## 数据流

1. **配置加载**：ConfigManager 读取 JSON 配置文件
2. **模板应用**：TemplateManager 合并模板与覆盖参数
3. **规划生成**：Planner 根据策略生成 DailyPlan 列表
4. **轨迹生成**：TrackGenerator 生成 GPS 坐标序列
5. **配速模拟**：PaceFluctuator 生成配速曲线
6. **数据导出**：Exporter 生成 TCX XML 文件

## 关键设计决策

### 1. 依赖注入

TrackGenerator 通过构造函数接受 TrackAnalysis、TrackAnalyzer、CoordinateCorrector，而不是自行创建。这提高了可测试性和灵活性。

### 2. Frozen Dataclass

所有数据模型（除 GenerationConfig 外）都使用 `@dataclass(frozen=True)` 确保不可变性。

### 3. 分离导出层

Exporter 抽象接口允许未来扩展 GPX、FIT 等格式，只需实现 export() 方法。

### 4. 配置即代码

模板系统允许将常用配置保存为 JSON 文件，通过 `--template` 参数加载。
