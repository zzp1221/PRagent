# P2 方向1 SPEC：步数耗尽降级为结论，而不是杀死审查

## 现状证据

**步数耗尽被当作致命错误**

- `pragent/agentic_core.py` 的 `BoundedRole.run` 在 `for step in range(1, self.max_steps + 1)`
  结束后无条件 `raise RuntimeBudgetExceeded("%s step budget exhausted" % self.name)`。
- 这个异常一路冒到 `harness._executing` 的兜底 `except Exception`，整次任务被标记 FAILED，
  `store.fail` 写入错误，报告不生成。

**A 型让这条路必然被踩到**

step2 之后 critic 可能拿到几十个文件的冻结集。step6 把它的步数从 2 提到 3，真实链路仍然
失败（任务 `aa709a00-191d-4edc-bcd1-35995f6667bc`，head `f7ece65`，29 文件）：
```
critic step budget exhausted
```
继续加大数字是治标：候选越多、文件越多，模型越想多看几处，任何固定步数都能被耗尽。
真正错的是**语义**——worker 与 critic 是可选角色，它们耗尽步数时已经有若干条观察结果，
既能给出部分结论，也不该否决其他角色的产出。

**对比：token/时间预算是真的该失败**

`run` 里 `used >= self.token_budget` 与 `elapsed >= self.time_budget` 也抛
`RuntimeBudgetExceeded`。这两条保持原样：它们代表真的在烧钱，继续跑下去没有意义。
只有「步数」是「还想多查一次」而不是「已经失控」。

## 目标（可验收）

1. worker 与 critic 步数耗尽时返回一个降级 final（带 `_degraded: True` 与已收集的
   observations），而不是抛异常；整次审查继续，其他角色的结论不受影响。
2. Lead 步数耗尽仍然抛异常。它一旦没有产出就没有任何结论可写，静默降级会产出一份
   「没发现问题」的空报告，那是比失败更糟的结果。
3. 最后一步不再向模型暴露工具清单，使「步数上限」真正起到强制收尾的作用，而不是
   等模型自愿停下。
4. 现有 234 个用例全绿（`test_review_budget` 里两处 `assertRaises` 走的是 `ReviewBudget`，
   不是步数，不受影响）。

## 非目标

- 不改 token 与时间预算的失败语义。
- 不改 `_needs_evidence_support`、`_initial_worker_steps`、critic 的三步上限（step6 保持）。
- 不做「降级后重试」，那会让预算上限失效。

## 设计决策

**降级结果带上 observations 而不是空对象**

`_collect_evidence(result.get("_observations"))` 会把观测里真实的 `evidence_id` 收进候选
发现的可引用证据。降级仍能保留「我查过什么」，报告因此可以解释结论来源。

**`_degraded` 标记而不是静默**

`_apply_critic` 对没有 decision 的候选写
`objections: ["critic returned no explicit decision"]`（这是既有逻辑），
`ledger.trace` 另记一条 `budget_exhausted` 带 `degraded=True` 与观测条数。
审计时能区分「critic 看过并同意」与「critic 没来得及说话」。

**最后一步清空工具清单**

比在 prompt 里写「这是最后一步，请收尾」更可靠：模型没有工具可请求时只能返回 final，
不依赖它遵守指令。若它仍然返回 tool，`tools.invoke` 抛出未知工具，该次观察记为失败，
循环结束走降级路径 —— 两条路都不会杀死审查。

## 约束

- 降级路径不改变候选发现的置信度（`adjustment` 保持 0），也不否决它们；最终采纳仍由
  Lead 的 finalize 决定。
- `degrade_on_exhaustion` 默认 False，只有 worker 与 critic 的两处构造打开，
  保证 Lead 与其他直接使用 `BoundedRole` 的调用点行为不变。
