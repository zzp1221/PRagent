# P1 方向3 PLAN：调查深度与共享预算

## 改动面

| 文件 | 变更 |
|---|---|
| `pragent/budget.py` | 新建 `ReviewBudget`：读账本、判断耗尽、快照 |
| `pragent/agentic_core.py` | `BoundedRole` 接受 budget；深度策略改为能力+缺口；execution 输出预算快照 |
| `pragent/config.py` | 新增三项预算配置与推导方法 |
| `pragent/service.py` | 构造 `AgenticReviewer` 时传入预算参数 |
| `tests/test_review_budget.py` | 新建：预算闸门、快照、深度策略 |

## 实施顺序

1. 写 `ReviewBudget`：`used_tokens / model_calls / elapsed / exhausted / check / snapshot`。
2. `BoundedRole` 加 `budget=None`；步骤循环顶部与格式重试循环内调用 `check`。
3. `AgenticReviewer.__init__` 加三个预算参数并在 `_review_with_context` 创建实例，
   沿 `_run_lead` / `_run_critic` / `_run_pending_assignments` 传递。
4. 深度策略：新增 `_initial_worker_steps` 与 `_needs_evidence_support`，替换写死的三元表达式。
5. Worker/Critic 的 instruction 文本补上"最多一次检索"的说明。
6. `execution["review_budget"]` 写入 summary；耗尽时 trace 记录原因。
7. `config.Settings` 三项配置与 `resolved_review_budget()`；service 接线。
8. 测试：预算耗尽（token / 调用次数）、快照入报告、有/无仓库下的深度差异、Critic 补证条件。
9. 全量回归，保持 110 用例全绿。

## 验证方法

- `tests/test_review_budget.py` 用 fake 客户端记录每次调用的角色、工具目录大小与 instruction。
- 预算：把 token 上限设成极小值 → 审查抛 `RuntimeBudgetExceeded`，错误信息含
  `review budget exhausted`；正常预算下报告含 `execution.review_budget` 且 `exhausted` 为空。
- 深度：同一份 diff，有 `repository_root` 时普通任务的 worker 调用数大于 1 且工具目录非空；
  无仓库时恰好 1 次且工具目录为空。
- Critic：构造一个高风险且无 evidence_refs/call_chain 的候选 → critic 调用带工具；
  同一场景去掉仓库 → critic 无工具。
- 回归：`python -c ...` 全量，失败数为 0。

## 回滚

预算是独立新模块，深度策略集中在两个方法内，revert 提交即恢复原行为。
