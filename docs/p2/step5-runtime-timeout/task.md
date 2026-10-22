# P2 方向1 任务清单：对齐框架超时与审查预算

## 实现

- [x] `Settings.resolved_runtime_timeout()`
  - [x] 读 `resolved_review_budget()["review_time_budget_seconds"]`
  - [x] 返回 `max(timeout_seconds, budget + 60)`
- [x] `service.py` 的 `ReviewHarness(...)` 用该值

## 测试

- [x] `tests/test_runtime_timeout.py`（6 用例）
  - [x] 默认配置推导为 540
  - [x] 显式更小的 `timeout_seconds` 被推导值覆盖
  - [x] 显式更大的 `timeout_seconds` 保留
  - [x] 显式审查预算小于框架值时，把超时压到预算加余量
  - [x] 框架值大于小预算时仍然保留框架值
  - [x] service 构造的 harness 与 runtime 都使用推导值

## 验证

- [x] 全量回归：**233 用例，0 失败 0 错误**（本步新增 6）
- [ ] 推一个新提交到 PR #3，确认新一轮审查不再报无原因的预算错误

## 实施记录

实现与计划一致。测试里修正过一次断言：最初期望
`agent_review_time_budget_seconds=30` 单独就能把超时压到 90，但 `max()` 的语义是
「显式框架值更大时保留框架值」（120 > 90），这是正确行为，因此拆成两个用例分别覆盖
两种相对大小。

另：本文件在上一轮写入时被中断截断（多字节字符被切断），已重建。

## 收尾

- [x] 回填 `docs/p2/INDEX.md`
- [x] 提交
