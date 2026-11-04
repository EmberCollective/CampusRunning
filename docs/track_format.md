# 轨迹配置格式

## 轨迹定义文件

轨迹定义存储在 `config/tracks/` 目录下，JSON格式。

### 文件结构

```json
{
  "id": "track_id",
  "name": "轨迹名称",
  "description": "轨迹描述",
  "base_coordinates": [
    {"longitude": 106.6591, "latitude": 26.4513},
    {"longitude": 106.6590, "latitude": 26.4516},
    ...
  ]
}
```

### 字段说明

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `id` | string | 是 | 轨迹唯一标识符 |
| `name` | string | 是 | 轨迹显示名称 |
| `description` | string | 是 | 轨迹描述信息 |
| `base_coordinates` | array | 是 | 基础坐标点列表 |
| `coordinate_correction` | object | 否 | 旧版兼容字段；当前版本读取后不参与坐标转换 |

### base_coordinates 格式

```json
{
  "longitude": 106.6591413213796,
  "latitude": 26.45129327365839
}
```

- `longitude`: 经度
- `latitude`: 纬度

### 坐标系

`base_coordinates` 必须使用 GCJ-02（高德/火星坐标系）坐标。生成 FIT/TCX 时，程序会按每个点所在位置将 GCJ-02 转换为 WGS-84；不要在配置文件中手工预扣偏移。
转换使用公开的 GCJ-02 正向偏移公式，并通过数值迭代求逆；回归测试会正向回代校验残差。这不是官方偏移数据表，GCJ-02 公式本身的模型误差无法离线消除。
迭代结果与 [kikkimo/WgsToGcj](https://github.com/kikkimo/WgsToGcj) 的 SimpleIteration 参考实现做过数值比对；本项目未复制其代码。
Keep 导入后轨迹偏移的问题背景见 [issue #64](https://github.com/EmberCollective/CampusRunning/issues/64)。

### 旧版 coordinate_correction 格式

```json
{
  "current_center": {"longitude": 106.6594, "latitude": 26.4518},
  "target_center": {"longitude": 106.6630, "latitude": 26.4482}
}
```

该字段来自旧版的“固定中心点平移”方案。GCJ-02 与 WGS-84 的偏移随地域变化，不能把一个校园的中心点差值复用到另一个城市；当前版本会忽略该字段，并在轨迹编辑器重新保存时将其移除。

## 添加新轨迹

1. 在 `config/tracks/` 创建新 JSON 文件
2. 收集轨迹的 GPS 坐标点（顺时针方向）
3. 生成时默认转换 GCJ-02 为 WGS-84

### 示例：添加新操场

```json
{
  "id": "track_2",
  "name": "第二操场",
  "description": "田径场跑道",
  "base_coordinates": [
    {"longitude": 106.6600, "latitude": 26.4520},
    ...
  ]
}
```

使用新轨迹：
```bash
python main.py single --track track_2 --date 2025-01-01 --distance 5.0
```

## 坐标转换说明

轨迹配置使用高德地图可直接拾取的 GCJ-02 坐标；FIT/TCX 运动文件按 GPS 语义使用 WGS-84 坐标：

```
导出坐标 = GCJ02_TO_WGS84(轨迹坐标)
```

`--no-correction` 会跳过该转换并保留 GCJ-02 原值，导入 Keep 等运动应用时会出现区域性偏移。

## 模板格式

预设模板存储在 `config/templates/` 目录下。

```json
{
  "id": "template_id",
  "name": "模板名称",
  "description": "模板描述",
  "generation_config": {
    "min_pace": 7.0,
    "max_pace": 8.0,
    "enable_pace_fluctuation": true
  }
}
```

可配置项参考 `GenerationConfig` 的所有字段。
