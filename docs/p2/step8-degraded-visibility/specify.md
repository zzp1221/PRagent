# P2 方向1 SPEC：让被降级的角色出现在报告里

## 现状证据

**降级只存在于 trace，报告看不出来**

- `pragent/agentic_core.py` 的 `BoundedRole.run` 在 `degrade_on_exhaustion` 打开时返回
  `{"action": "final", "_degraded": True, "_steps": max_steps, "_observations": [...]}`，
  并写一条 `ledger.trace(self.name, "budget_exhausted", degraded=True, ...)`。
- `pragent/telemetry.py:145-170` 的 `summary()` 只输出 `agent_traces`，没有把降级汇总成
  一个可读字段。
- `pragent/report.py:20-38` 的 `to_markdown()` 渲染 Execution facts 时不提降级。
- 后果：critic 万一耗尽步数，报告里的 finding 就是**未经挑战的候选**，而 PR 评论与
  控制台都显示成一次正常完成。`docs/p2/INDEX.md` 末尾已把这条记为遗留边界。

**这条边界的代价**

step7 把「步数耗尽」从致命错误改成降级，选对了方向，但降级是静默的。对一个把
「所有 finding 必须通过证据与置信度门禁」写进首页的项目，静默降级比失败更容易误导：
失败至少不会发出一份看起来完整的报告。

## 目标（可验收）

1. `ExecutionLedger.summary()` 输出 `degraded_roles`：一个有序的角色名列表，
   由 `agent_traces` 里 `event == "budget_exhausted"` 且 `degraded` 为真的记录推导。
2. 该字段随 `execution` 进入报告（`harness._reviewing` 已经整体转发 `execution`）。
3. 报告 markdown 在 `degraded_roles` 非空时，于 Execution facts 中增加一行
   `Degraded roles: ... (ran out of steps; their results are partial)`。
4. 没有降级时，报告输出与今天逐字一致（不新增空行、不新增行为）。
5. 现有 235 个用例全绿。

## 非目标

- 不改降级本身的语义与触发条件（step7 保持）。
- 不为降级引入重试。
- 不把「未经 Critic 裁决」升级为门禁拒绝条件。降级结果是否可信是一个需要真实数据
  支撑的判断，本步只负责让它可见。

## 设计决策

**从账本推导，不在调用链里传递**

`agent_traces` 已经记录了每一条 `budget_exhausted`，`ExecutionLedger` 是本次审查的唯一
记账对象。在这里汇总一次，比让 `_run_pending_assignments` 与 `_run_critic` 各自把
标记往上搬要少改三处，也不会因为某条路径忘记传递而漏报。

**放在 `execution` 而不是新增顶层字段**

`harness._reviewing` 已经把 `reviewer_summary["execution"]` 整体塞进报告，新增一个
顶层的同级字段要改两处转发。放进 `execution` 零改动即达。

**警告用纯文本而非 emoji 或粗体标题**

报告已经用 `>` 引用块表达 `fallback_reason`。降级用同样的单行列表项即可，且必须能在
PR 评论里一眼看到；不需要新的视觉层级。

## 约束

- `summary()` 在锁内复制 `traces`，降级统计必须在复制之后计算，不能再次进入临界区。
- 角色名来自 `BoundedRole.name`，只会是 `lead`/`security`/`correctness-reliability`/
  `critic` 四者之一；排序后输出保证同一份 trace 得到同一份报告。
- `degraded_roles` 为空列表时，JSON 里仍是 `[]` 而不是缺失键，
  这样消费方不必区分「没有这个字段」与「没有降级」。
