# API 参考

## CLI 使用

### 基本用法

```bash
# 查看帮助
python main.py --help

# 列出可用轨迹
python main.py --list-tracks

# 列出可用模板
python main.py --list-templates
```

### 生成模式

#### 每日范围模式

```bash
python main.py daily \
  --start-date 2025-01-01 \
  --end-date 2025-01-31 \
  --min-km 2.0 \
  --max-km 5.0
```

可选参数：
- `--min-pace` / `--max-pace` - 配速范围
- `--start-time-min` / `--start-time-max` - 开始时间范围
- `--output-dir` - 输出目录
- `--no-track` - 不生成轨迹点
- `--no-correction` - 不应用坐标修正
- `--no-pace-fluctuation` - 恒定配速
- `--zip` - 打包为 ZIP
- `--track` - 指定轨迹
- `--template` - 应用模板

#### 总公里数模式

```bash
python main.py total \
  --start-date 2025-01-01 \
  --end-date 2025-01-31 \
  --total-km 100
```

额外参数：
- `--weekend-factor` - 周末距离倍数（默认1.5）
- `--rest-days-per-week` - 每周休息天数
- `--min-daily-km` / `--max-daily-km` - 每日距离范围

#### 单文件模式

```bash
python main.py single \
  --date 2025-01-15 \
  --distance 5.0
```

额外参数：
- `--pace` - 指定配速（留空随机）

## Web API

启动 Web 服务器：
```bash
pip install flask
python app.py
```

访问 http://127.0.0.1:5000

### 端点

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/` | 主页面 |
| GET | `/api/tracks` | 列出所有轨迹 |
| GET | `/api/tracks/<id>` | 获取轨迹详情 |
| GET | `/api/templates` | 列出所有模板 |
| GET | `/api/defaults` | 获取默认设置 |
| POST | `/api/generate/daily` | 每日范围生成 |
| POST | `/api/generate/total` | 总公里数生成 |
| POST | `/api/generate/single` | 单文件生成 |
| GET | `/api/download/<job_id>` | 下载生成的文件 |

### 请求示例

#### POST /api/generate/daily

```json
{
  "track_id": "campus_default",
  "template_id": "easy_run",
  "start_date": "2025-01-01",
  "end_date": "2025-01-07",
  "min_km": 2.0,
  "max_km": 5.0,
  "min_pace": 7.0,
  "max_pace": 8.0,
  "include_track": true,
  "apply_correction": true,
  "enable_pace_fluctuation": true
}
```

#### POST /api/generate/total

```json
{
  "start_date": "2025-01-01",
  "end_date": "2025-01-31",
  "total_km": 100,
  "weekend_factor": 1.5,
  "rest_days_per_week": 1,
  "min_daily_km": 2.0,
  "max_daily_km": 8.0
}
```

#### POST /api/generate/single

```json
{
  "date": "2025-01-15",
  "distance": 5.0,
  "pace": 7.5
}
```

### 响应示例

```json
{
  "job_id": "gen_20250115_abc123",
  "status": "complete",
  "total_files": 1,
  "files": [
    {
      "filename": "2025-01-15_5.0km.tcx",
      "date": "2025-01-15",
      "distance_km": 5.0,
      "pace_min_per_km": 7.5,
      "duration_seconds": 2250,
      "calories": 300
    }
  ],
  "download_url": "/api/download/gen_20250115_abc123"
}
```

## 数据模型

### GeoPoint

```python
@dataclass(frozen=True)
class GeoPoint:
    longitude: float  # 经度
    latitude: float   # 纬度
```

### TrackDefinition

```python
@dataclass(frozen=True)
class TrackDefinition:
    id: str
    name: str
    description: str
    base_coordinates: list[GeoPoint]
    coordinate_correction: Optional[CoordinateCorrection]
```

### GenerationConfig

```python
@dataclass
class GenerationConfig:
    track_id: str = "campus_default"
    min_pace: float = 7.0
    max_pace: float = 8.0
    start_hour_min: int = 6
    start_hour_max: int = 8
    output_dir: str = "output"
    include_track: bool = True
    apply_correction: bool = True
    enable_pace_fluctuation: bool = True
    create_zip: bool = False
    points_per_km: int = 50
    max_deviation_meters: float = 2.0
    smooth_factor: float = 0.3
    weekend_factor: float = 1.5
    rest_days_per_week: int = 1
    min_daily_km: float = 2.0
    max_daily_km: float = 8.0
    calories_per_km: float = 60.0
```
