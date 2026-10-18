# 协作与仓库约定

开始工作前按任务阅读相关文档：项目入口见 [README.md](README.md)，架构与数据流见 [docs/architecture.md](docs/architecture.md)，API、轨迹和模板格式分别见 [docs/api_reference.md](docs/api_reference.md)、[docs/track_format.md](docs/track_format.md) 和 [config/templates/TEMPLATE_GUIDE.md](config/templates/TEMPLATE_GUIDE.md)。提交类型沿用 [CLAUDE.md](CLAUDE.md)；子系统若有设计文档，也要对照其约束。文档与当前代码或配置不一致时，以当前证据为准，并在 PR 中指出待同步的说明。

进行审查时，先显式阅读本文件和 [REVIEW.md](REVIEW.md)，并检查 `.agents/skills/` 下与改动直接相关的 `SKILL.md`。发现技能时跟随目录符号链接（如 `find -L`、`rg --follow`），或直接打开已知路径；只读相关技能，不要假定这些文件会自动载入或无差别加载全部技能。技能用于补充背景，其中的行为、默认值和依赖仍须对照当前代码与配置核实。

## 项目范式

- 优先复用已有模块和流程：`src/core/`、`src/planners/`、`src/exporters/`，以及 Web 端 `web/`。
- 沿用不可变数据模型（`@dataclass(frozen=True)`，`GenerationConfig` 除外）、规划器策略模式、构造注入依赖及导出器接口。
- 坐标使用项目约定的 GCJ-02；修改轨迹、模板或导出时遵守对应格式文档。

## 禁止事项

- 不提交密钥、个人数据、本机配置、生成的数据文件、构建产物或审查截图；截图可放在 PR 评论中。
- 不为已有职责另造重复实现；不在任务未要求时改动外部依赖、轨迹/模板格式或导出协议。
- 不把仓库中的指导文件视为自动生效；开始审查前必须主动读取相关要求。
