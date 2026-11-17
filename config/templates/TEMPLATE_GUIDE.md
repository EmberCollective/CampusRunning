# 模板创建指南

## 概述

模板用于保存和复用跑步数据生成配置。支持多模式配置，每种模式（每日范围/总公里数/单文件）有独立的配置节。

## 模板格式

```json
{
  "id": "template_unique_id",
  "name": "模板显示名称",
  "description": "模板描述",
  "track_id": "轨迹ID（可选）",
  "daily_config": {
    "start_date": "2024-03-01",
    "end_date": "2024-05-31",
    "min_pace": 6.0,
    "max_pace": 8.0,
    "start_hour_min": 6,
    "start_hour_max": 8,
    "min_km": 2.0,
    "max_km": 5.0,
    "include_track": true,
    "apply_correction": true,
    "enable_pace_fluctuation": true
  },
  "total_config": {
    "start_date": "2024-03-01",
    "end_date": "2024-05-31",
    "total_km": 50,
    "weekend_factor": 1.5,
    "min_daily_km": 2.0,
    "max_daily_km": 8.0,
    "rest_days_per_week": 1,
    "min_pace": 6.0,
    "max_pace": 8.0,
    "start_hour_min": 6,
    "start_hour_max": 8,
    "include_track": true,
    "apply_correction": true,
    "enable_pace_fluctuation": true
  },
  "single_config": {
    "pace": 6.5,
    "include_track": true,
    "apply_correction": true,
    "enable_pace_fluctuation": true
  }
}
```

## 配置参数说明

### 通用参数

| 参数 | 类型 | 说明 |
|------|------|------|
| `track_id` | string | 轨迹ID，对应轨迹选择下拉框 |
| `min_pace` | float | 最快配速 (min/km)，越小越快 |
| `max_pace` | float | 最慢配速 (min/km)，越大越慢 |
| `start_hour_min` | int | 最早开始时间（小时） |
| `start_hour_max` | int | 最晚开始时间（小时） |
| `start_date` | string | 开始日期 (YYYY-MM-DD格式) |
| `end_date` | string | 结束日期 (YYYY-MM-DD格式) |
| `include_track` | bool | 是否包含轨迹点数据 |
| `apply_correction` | bool | 是否应用坐标修正 |
| `enable_pace_fluctuation` | bool | 是否启用配速波动 |
| `pace_algorithm` | string | `natural`（默认）/`steady`/`progressive`，或本机显式注册的算法 |
| `pace_intensity` | float | 波动强度 0–1，默认 0.15；内置算法在 0 时匀速 |

### 每日模式 (daily_config)

| 参数 | 类型 | 说明 |
|------|------|------|
| `min_km` | float | 每日最低公里数 |
| `max_km` | float | 每日最高公里数 |

### 总公里数模式 (total_config)

| 参数 | 类型 | 说明 |
|------|------|------|
| `total_km` | float | 目标总公里数 |
| `weekend_factor` | float | 周末跑步系数 |
| `min_daily_km` | float | 每日最低公里数 |
| `max_daily_km` | float | 每日最高公里数 |
| `rest_days_per_week` | int | 每周休息天数 |

### 单文件模式 (single_config)

| 参数 | 类型 | 说明 |
|------|------|------|
| `pace` | float | 指定配速 (min/km) |

## 使用方式

### Web界面导出/导入

1. **导出模板**：
   - 填写好表单配置
   - 点击"导出模板"按钮
   - 在弹出窗口中输入模板名称
   - 点击"导出"下载 JSON 文件

2. **导入模板**：
   - 在预设模板下拉框中选择"上传模板..."
   - 选择之前导出的 JSON 文件
   - 模板将自动保存到浏览器本地缓存
   - 刷新页面后本地模板会出现在下拉框中

### 本地模板缓存

导入的模板会自动保存在浏览器 localStorage 中。下次使用时无需重新上传，直接从"本地模板"分组中选择即可。

如需清除本地模板，可在浏览器开发者工具的控制台执行：
```javascript
localStorage.removeItem('template_cache');
```

## 模板示例

### 轻松跑模板

```json
{
  "id": "easy_run",
  "name": "轻松跑",
  "description": "轻松慢跑，适合恢复日",
  "track_id": "",
  "daily_config": {
    "min_pace": 7.5,
    "max_pace": 9.0,
    "max_deviation_meters": 2.5,
    "smooth_factor": 0.4,
    "enable_pace_fluctuation": true
  }
}
```

### 间歇跑模板

```json
{
  "id": "interval",
  "name": "间歇跑",
  "description": "高强度间歇训练",
  "track_id": "",
  "total_config": {
    "min_pace": 4.5,
    "max_pace": 5.5,
    "weekend_factor": 1.2,
    "min_daily_km": 3.0,
    "max_daily_km": 10.0,
    "enable_pace_fluctuation": false
  }
}
```

### 长距离跑模板

```json
{
  "id": "long_run",
  "name": "长距离跑",
  "description": "周末长距离训练",
  "track_id": "",
  "total_config": {
    "min_pace": 6.0,
    "max_pace": 7.5,
    "weekend_factor": 1.5,
    "min_daily_km": 5.0,
    "max_daily_km": 15.0,
    "rest_days_per_week": 1,
    "enable_pace_fluctuation": true
  }
}
```

## 注意事项

1. **ID 唯一性**：每个模板的 `id` 必须唯一
2. **模式选择性**：可以只定义某一模式的配置，导入时会自动跳转到该模式
3. **本地缓存**：模板保存在浏览器本地，切换浏览器或清除缓存后需要重新导入
4. **文件格式**：JSON 格式必须正确，可使用 JSON 验证工具检查
