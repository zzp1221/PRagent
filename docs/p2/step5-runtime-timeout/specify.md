# P2 方向1 SPEC：让框架超时不再先于审查预算触发

## 现状证据

**两个时间预算互相矛盾，更紧的那个还没有原因**

- `pragent/runtime.py:164-166`：
  ```python
  if steps >= self.max_steps or time.monotonic() - started > self.timeout_seconds:
      emit("budget_exhausted", node)
      raise RuntimeBudgetExceeded("task execution budget exceeded")
  ```
  `timeout_seconds` 取 `Settings.timeout_seconds`，默认 120（`pragent/config.py`）。
- `pragent/config.py:155-157`：`review_time_budget_seconds` 默认
  `agent_time_budget_seconds × 8 = 480`。
- `pragent/service.py:159-162` 构造 `ReviewHarness` 时直接用 `effective.timeout_seconds`，
  两者没有任何关联。

后果：框架硬杀永远先于审查软上限触发，`ReviewBudget` 里那句能说清
「seconds 312/480」的错误信息永远没机会出现；用户只看到无原因的
`task execution budget exceeded`。

**A 型把这个问题从理论变成常态**

step4 的真实 PR（25 文件）审查耗时 97.9 秒，而默认上限是 120 秒，余量 23%。
同一轮轮询并发提交的另一个任务（PR #1，仅 1 文件 1562 字符）因为争抢模型配额跑到
139 秒，直接失败。A 型之前审查只读 diff，同样的 PR 通常几十秒内结束，这个矛盾没有暴露。

## 目标（可验收）

1. 框架级 `timeout_seconds` 不小于审查自身的 `review_time_budget_seconds` 加一档余量，
   使得「审查预算先触发、框架硬杀只做兜底」这一分层成立。
2. 超时时优先出现 `review budget exhausted: seconds X/Y`，而不是无原因的
   `task execution budget exceeded`。
3. 显式配置 `PRAGENT_TIMEOUT_SECONDS` 且大于推导值时，仍然尊重显式值。
4. 现有 227 个用例全绿（尤其 `test_review_budget` 的两处 `assertRaises` 不受影响）。

## 非目标

- 不改 `max_steps`。它是节点步数上限，默认 8 对三个节点加两轮重试已经够用。
- 不引入并发限流。轮询同时提交多个 PR 是正常行为，问题在超时分层而不是并发本身。
- 不缩短审查耗时。A 型用 98 秒换来 21 次真实工具调用与 25 个文件的完整上下文，
  这是要保留的取舍，不是要压回的成本。
- 不改 `ReviewBudget` 的语义。

## 设计决策

**推导放在 `Settings`，不放 service**

`resolved_review_budget()` 已经是「未显式配置时推导天花板」的既有位置。新增
`resolved_runtime_timeout()` 与它并列，读同一份推导结果，避免两处各算一次而漂移。
service 只需要把 `effective.timeout_seconds` 换成 `effective.resolved_runtime_timeout()`。

**余量取 60 秒而不是系数**

软上限触发后，`RuntimeBudgetExceeded` 需要向上穿过 worker 线程、写 trace、写任务状态。
这段收尾是秒级的，但给多少取决于模型提供方的尾延迟。60 秒足够覆盖收尾，又不会让
「框架兜底」形同虚设。

**显式配置优先**

`max(self.timeout_seconds, budget + 60)` 只在推导值更大时生效。运维显式写
`PRAGENT_TIMEOUT_SECONDS=900` 时结果就是 900，不会被推导值压低。

## 约束

- 测试环境大量使用 `timeout_seconds=10`，推导后变 540。这不影响任何用例：没有用例
  依赖 runtime 超时触发（`test_review_budget` 的两处 `assertRaises` 走的是
  `ReviewBudget.check`，`test_runtime_memory_context` 直接构造 `AgentRuntime` 不经过 service）。
- 该值只影响框架硬杀，不增加任何实际等待时间。
