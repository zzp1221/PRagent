# 项目架构与 Agent 执行流程

依据当前源码 `b4082fe` 绘制，日期：2026-10-20。

| 图 | draw.io 可编辑源文件 | PNG 预览 | SVG 矢量图 |
|---|---|---|---|
| 项目架构 | [architecture.drawio](architecture.drawio) | [architecture.png](architecture.png) | [architecture.svg](architecture.svg) |
| Agent 执行流程 | [agent-execution.drawio](agent-execution.drawio) | [agent-execution.png](agent-execution.png) | [agent-execution.svg](agent-execution.svg) |

用 draw.io / diagrams.net 打开 `.drawio` 文件即可编辑节点、文字和连线。SVG 也包含 draw.io 图数据；PNG 用于直接预览。实线表示主要调用或执行流，虚线表示支撑依赖、子流程引用或可选操作。

## 图中范围

- 架构图包含 HTTP/API 与鉴权、ReviewService、队列、Runtime、多 Agent 协作、工具、上下文、Skill、记忆、存储、反馈演进、独立修复和可观测性。
- 执行流程图包含同步/异步入口、checkpoint 恢复、规则扫描、Lead 委派、普通/高风险 Worker、一次返工、Critic、Lead 综合、发现门禁、报告，以及工具循环和修复支线。
- 正式审查入口只有 `agentic` 模式，要求配置模型。规则扫描作为多 Agent 审查的辅助信号。
- 普通路径每个委派任务执行一轮。默认启用 Critic 且双 Worker 各接到一个任务时，共 5 次模型调用；实际调用次数随委派任务数、重试和高风险步骤变化。
- 高风险 Worker 初次任务最多 3 步，返工任务最多 2 步，最多返工一轮。Lead 和 Critic 在当前主流程中均不调用工具。
- 完整仓库工具依赖可选的本地 `repository_root`；Webhook 获取 Diff，不自动克隆仓库。修复是单独请求，验证通过后创建 Draft PR。
- 本地默认 SQLite 和进程内队列；Compose 配置 PostgreSQL 与 Redis，队列消费者在 PRAgent 服务进程的线程池内运行。

## 源码依据

- 接入与编排：[api.py](../pragent/api.py)、[service.py](../pragent/service.py)、[task_queue.py](../pragent/task_queue.py)
- Runtime 与协作：[harness.py](../pragent/harness.py)、[runtime.py](../pragent/runtime.py)、[agentic_core.py](../pragent/agentic_core.py)
- 上下文与能力：[context_manager.py](../pragent/context_manager.py)、[memory.py](../pragent/memory.py)、[skills.py](../pragent/skills.py)、[repository_tools.py](../pragent/repository_tools.py)
- 门禁与修复：[gates.py](../pragent/gates.py)、[patching.py](../pragent/patching.py)、[verifier.py](../pragent/verifier.py)
- 演进与部署：[evolution.py](../pragent/evolution.py)、[skill_evolution.py](../pragent/skill_evolution.py)、[docker-compose.yml](../docker-compose.yml)
