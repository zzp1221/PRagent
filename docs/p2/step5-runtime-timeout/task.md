# P2 方向1 任务清单：对齐框架超时与审查预算

## 实现

- [x] `Settings.resolved_runtime_timeout()`
  - [x] �?`resolved_review_budget()["review_time_budget_seconds"]`
  - [x] 返回 `max(timeout_seconds, budget + 60)`
- [x] `service.py` �?`ReviewHarness(...)` 用该�?
## 测试

- [x] `tests/test_runtime_timeout.py`
  - [x] 默认配置推导�?540
  - [x] 显式更小�?`timeout_seconds` 被推导值覆�?  - [x] 显式更大�?`timeout_seconds` 保留
  - [x] 显式 `agent_review_time_budget_seconds` 参与推导
  - [x] service 构造的 harness 使用推导�?
## 验证

- [x] 全量回归 227 + 新增�? 失败
- [x] 推一个新提交�?PR #3，确认新一轮审查不再报无原因的预算错误

## 收尾

- [x] 回填 `docs/p2/INDEX.md`
- [x] 提交
