# step6 PLAN：租约 fencing

## 改动面

| 文件 | 变更 |
|---|---|
| `pragent/task_lease.py` | `LeaseLost` 异常、`fence` 属性 |
| `pragent/store.py` | 四个写入点接受 `fence`，返回 bool |
| `pragent/postgres_store.py` | 同上 |
| `pragent/harness.py` | `run(..., fence=None)`，写入透传，成功写入被拒则抛 `LeaseLost` |
| `pragent/service.py` | `_run_review` 透传 fence；`_process_leased` 传 `lease.fence` 并捕获 `LeaseLost` |
| `tests/test_queue_reliability.py` | 用例：过期执行者的写入被拒 |

## 实施顺序

1. `TaskLease` 增加 `fence` 与 `LeaseLost`。
2. `store` 四个方法加 fence 参数与条件 UPDATE，返回 bool。
3. `postgres_store` 同步实现。
4. `harness` 透传；`_transition` 从线程本地上下文取 fence。
5. `service` 接线并处理 `LeaseLost`。
6. 测试与回归。

## 验证方法

- 用两个 `TaskLease` 模拟：A 持有 → 租约过期 → B 接管 → A 用旧 token 写 succeed 被拒，
  B 用新 token 写 succeed 成功，最终报告属于 B。
- 同步路径（fence=None）写入不受影响：既有 `test_service` / `test_harness` 全绿。
- 全量失败数不超过 5。

## 回滚

fence 默认 None，删除参数即恢复原行为。
