# P1 方向3 TASK：调查深度与共享预算（已完成）

- [x] T1 新建 `pragent/budget.py` 的 `ReviewBudget`（读账本，不重复记账）
- [x] T2 `BoundedRole` 接受 budget，步骤循环顶部与格式重试循环内检查
- [x] T3 `AgenticReviewer` 三项预算参数，按 task_id 注册并在 `review_with_context` 结束时清理
- [x] T4 深度策略：`_initial_worker_steps` 与 `_needs_evidence_support`
- [x] T5 Worker 的 instruction 说明"最多一次检索"；Critic 沿用既有工具提示
- [x] T6 `execution.review_budget` 快照；耗尽时 `review_budget_exhausted` 写入 trace 与任务错误
- [x] T7 `config` 三项配置 + `resolved_review_budget()`，service 接线，`.env.example` 与 README 同步
- [x] T8 新建 `tests/test_review_budget.py`（11 个用例）
- [x] T9 全量回归：121 用例全绿
- [x] T10 git 提交

## 落地后的行为

**调查深度不再由单一风险标签决定**

- Worker：高风险 3 步；普通风险且有仓库上下文 2 步（1 次检索 + 1 次总结）；
  无仓库上下文维持 1 步无工具。后者是刻意的：没有仓库时给工具只会产生一串
  `repository checkout is unavailable` 的失败观测，纯烧预算。
- Critic：仓库可用且（高风险 或 存在"高风险但没有任何可验证证据"的候选）时给 2 步与工具，
  否则维持 1 步盲审。

**预算覆盖整次审查**

`ReviewBudget` 读 `ExecutionLedger.model_calls`，因此天然包含所有角色、格式重试与返工轮次。
检查点在每个角色循环的步骤顶部与格式重试循环内，耗尽即抛 `RuntimeBudgetExceeded`：
Worker 线程内会被记为该 worker 失败，Lead/Critic 阶段会中止整次审查。

## 验证

- 预算单元：token 上限、调用次数上限、全 0 不耗尽、快照字段。
- 深度：有仓库时普通任务 worker 可走两步（先 `search_diff` 再给结论，观测数 0→1）；
  无仓库时工具目录为空且 instruction 为 one-shot。
- Critic：无证据的高风险候选在有仓库时获得工具，无仓库时不获得。
- 端到端：`agent_review_token_budget=1` 时任务 FAILED 且错误含 `review budget exhausted`；
  正常预算下报告含 `execution.review_budget`（48000 / 240 / 未耗尽）。
- 全量 121 用例 0 失败。
