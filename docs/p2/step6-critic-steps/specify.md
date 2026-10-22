# P2 方向1 SPEC：给 Critic 足够的验证步数

## 现状证据

**A 型把 `critic_tools` 从恒假变成可能为真，但步数没跟着变**

- `pragent/agentic_core.py:759-767`：
  ```python
  critic_tools = suite.repository_available and (
      high_risk or self._needs_evidence_support(candidates)
  )
  critic_result = self._run_critic(
      ..., max_steps=2 if critic_tools else 1, allow_tools=critic_tools,
  )
  ```
- `BoundedRole` 的一步要么发起工具调用，要么给出最终答案
  （`agentic_core.py:274` 的 `step budget exhausted` 在循环末尾抛出）。
  因此 `max_steps=2` 的真实含义是「最多一次工具调用 + 一次回答」。

**A 型之前这条路走不到**

`repository_available` 在 webhook 与轮询路径上恒为假，`critic_tools` 恒为假，critic 永远
`max_steps=1` 单步盲审。step2 之后它可能拿到 29 个文件的冻结集与一次查询机会。

**真实链路已经因此失败**

任务 `0b8ea657-3d18-4828-8637-99211c6a98c6`（PR #3，29 文件）：
```
2 [EXECUTING] Reviewing 29 changed files
3 [FAILED] Review failed: critic step budget exhausted
```
同一 PR 的上一轮（任务 `545fc4f1`，25 文件）成功，是因为那次 critic 只读了一个文件就
给出了决定。加两个文件后它想再查一次，就撞上了 2 步上限。

## 目标（可验收）

1. critic 拿到工具时至少有 3 步：两次验证查询 + 一次最终决定。
2. critic 没有工具时仍是 1 步，行为不变。
3. 现有 233 个用例全绿，`test_review_budget` 里依赖 `critic_tools` 的断言不受影响。

## 非目标

- 不放宽 worker 的步数策略（`_initial_worker_steps` 不变）。
- 不改 `_needs_evidence_support` 的判定条件。critic 该不该拿工具是另一个问题，
  本步只修「拿到工具却不够用」。
- 不提高 `review_token_budget`。一次 critic 查询约 1.5 万 token，第三次仍在 288000 之内。

## 设计决策

**3 步而不是按候选数量动态计算**

critic 的职责是「挑战结论」，不是「穷举验证」。两个查询足以覆盖最常见的两种反例
（读实现、查调用点）。按候选数量放大步数会让一个 14 候选的 PR 把预算烧在盲审阶段，
而这恰恰是最不该花钱的地方。

**与 high-risk worker 对齐**

`_initial_worker_steps(high_risk=True)` 给 worker 3 步。critic 的验证深度不应低于
worker 的取证深度，否则「盲审挑战」会退化成「看一眼就点头」。

## 约束

- `BoundedRole` 的每步都会 `budget.check`，所以多一步同时受整次审查预算约束；
  step5 已经把框架超时抬到审查预算之上，这里不会引入新的互相矛盾。
- 失败时的错误信息保持不变（`critic step budget exhausted`），只是更难触发。
