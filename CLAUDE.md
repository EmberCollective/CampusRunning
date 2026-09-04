# CLAUDE.md - 校园跑步数据生成器

## 项目类型
- Python CLI + Flask Web 应用
- 跑步轨迹数据生成器 (TCX格式)

## 技术栈
- Python 3.13+
- Flask
- garmin-fit-sdk（FIT 导出，Keep 导入必需；`pip install garmin-fit-sdk`）

## 关键命令

### 运行
```bash
python main.py --help
python app.py
```

### 开发
- Web 服务器: `python app.py` (默认 0.0.0.0:5000)
- CLI: `python main.py <command>`

## 目录结构
- `src/core/` - 核心模块（轨迹生成、配速波动、坐标修正）
- `src/planners/` - 规划策略
- `src/exporters/` - 导出器
- `web/` - Flask Web 应用
- `config/` - 配置文件

## Commit 规范

| Type | 含义 | 使用场景 |
|------|------|----------|
| `feat` | 新功能 | 新增功能、模块、API端点 |
| `core` | 核心模块变更 | track_generator, pace_fluctuator 等核心算法 |
| `fix` | 修复 | Bug 修复 |
| `web` | Web应用变更 | web/ 目录下的变更 |
| `refactor` | 重构 | 代码重构（不改变功能） |
| `docs` | 文档 | 文档更新 |
| `test` | 测试 | 测试相关 |
| `chore` | 杂项 | 配置、构建、依赖更新 |

## 关键约定
- 不可变数据模型 (`@dataclass(frozen=True)`)
- 策略模式 (planners)
- 依赖注入 (TrackGenerator)

## 坐标系说明

本项目使用**高德坐标系（GCJ-02）**。轨迹配置中的 `coordinate_correction` 定义从 `current_center`（轨迹坐标中心）到 `target_center`（实际位置中心）的偏移量。

添加新轨迹时，只需填入高德坐标的实际值，系统会自动处理偏移校正，无需手动计算。
