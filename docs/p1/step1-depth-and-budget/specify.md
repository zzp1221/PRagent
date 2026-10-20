# P1 方向3 SPEC：按证据缺口调整调查深度 + 整次审查共享硬预算

## 现状证据

**深度被风险等级一次性决定，之后无法补齐**

- `pragent/agentic_core.py:606-607`：`max_steps=3 if high_risk else 1, allow_tools=high_risk`
- `pragent/agentic_core.py:684`：Critic `max_steps=1, allow_tools=False`
- Lead 委派阶段已经在 `agentic_core.py:599-600` 判定了 `risk_level`，此后不再改变。
- 后果：若 Lead 把风险判低，Worker 就是单步、无工具的盲判；即使结论缺少事实支撑，
  也没有第二次检索机会，Critic 同样只能凭 diff 文本空审。

**预算是每角色各算各的，没有整次审查的上限**

- `pragent/agentic_core.py:349-356`：`_token_budget(role)` 按角色取值，单角色可被
  `structured_config` 抬到默认的 4 倍。
- `pragent/agentic_core.py:168-174`：`BoundedRole` 只统计 `item.role == self.name` 的 tokens。
- 一次审查实际会调用 Lead 两次到四次、每个 Worker 一到两次、Critic 一次，高风险还有一轮返工，
  但没有任何一处对它们的总和设限。返工与无效重试的成本不会被任何闸门拦住。

## 目标（可验收）

1. 存在仓库上下文时，普通风险任务的 Worker 可以追加一次检索（最多两步、带工具）；
   无仓库上下文时维持单步无工具，避免把预算浪费在必然失败的调用上。
2. 候选发现里存在"高风险但没有任何可验证证据"的项时，Critic 可以调用工具补证；
   仓库不可用或不存在此类候选时，Critic 维持单步盲审。
3. 一次审查共享一个硬预算，覆盖所有角色的 token、总耗时与模型调用次数，
   含重试与返工；耗尽即中止，不再继续烧钱。
4. 预算用量与上限进入报告的 `execution.review_budget`，可观测。
5. 现有行为在默认配置下不变：110 个既有用例全绿。

## 非目标

- 不改变单角色预算的语义（仍作为角色级上限）。
- 不做"预算耗尽后仍发布部分结果"的降级路径（与现有单角色预算耗尽的失败语义保持一致）。
- 不实现仓库快照（P2 方向1）。

## 设计决策

**预算挂在账本上而不是自己记账**：`ExecutionLedger.model_calls` 已经记录每次模型调用的
tokens 与角色，是唯一真相源。`ReviewBudget` 只持上限并读账本，天然覆盖所有角色、重试与返工。

**预算检查放在每次模型调用前后**：`BoundedRole` 既在步骤循环顶部检查，也在同一步内的
格式重试循环里检查，否则一次坏的返回会烧掉三次调用而不被发现。

**深度由"能力 + 缺口"决定，不由单一风险标签决定**：
- Worker 的第二步取决于 `suite.repository_available`（能力）与 `high_risk`（风险）；
- Critic 的工具取决于候选是否真的缺证据（缺口），并同样要求仓库可用。
- 没有仓库时给工具只会产生一串 `repository checkout is unavailable` 的失败观测，纯烧预算。

**默认上限由现有配置推导**，不引入新的必填项：token 为 `agent_token_budget × 6`
（四个角色加返工余量），时间为 `agent_time_budget_seconds × 8`，调用次数默认不限
（token 已是主约束）。三项都可用环境变量显式覆盖。

时间系数取 8 而不是 4：一次审查有五到九次模型调用，每次都可能用满角色级时间预算，
系数 4 会在慢速提供方上于审查中途误杀。系数 8 仍能拦住失控的审查。

## 约束

- Worker 并发执行（`agentic_core.py:1017`），预算检查必须线程安全。
- 预算耗尽抛 `RuntimeBudgetExceeded`，Worker 线程内会被记录为该 worker 失败，
  Lead/Critic 阶段会中止整次审查；两条路径都要在 trace 里留下原因。
