# P0-2 TASK：队列租约、执行锁与 Webhook 原子派发（已完成）

## 2A 数据库租约与执行锁

- [x] T1 `TaskStore._init` 迁移三个 lease 列（lease_owner / lease_token / lease_expires_at）
- [x] T2 `acquire_task_lease` / `renew_task_lease` / `release_task_lease`（SQLite，单条条件 UPDATE）
- [x] T3 同样的方法在 `PostgresTaskStore`
- [x] T4 `pragent/task_lease.py` 新增 `TaskLease` 心跳上下文
- [x] T5 `_process_queued` 接入租约，终态任务幂等返回
- [x] T6 测试：并发 acquire 只有一个成功、过期可接管、token 递增、心跳跨越长任务

## 2B Redis PEL 续租

- [x] T7 `_deliver` 接收 redis_id，执行期起 `xclaim(idle=0)` 心跳
- [x] T8 `_reclaim_stale` 加固：无法解析的消息进 DLQ 并 ACK，不再永久卡在 PEL
- [x] T8b 测试：心跳期间持续重置 idle、无 redis_id 不 claim、坏消息被停放

## 2C Webhook 原子派发与补偿

- [x] T9 store 加 `create_webhook_task`（tasks 插入与 delivery 更新同一事务）
- [x] T10 `handle_github_pull_request` 改原子派发 + duplicate 短路修正
- [x] T11 store 加 `list_undispatched_tasks`，service 加 `redispatch_pending`
- [x] T12 `api.run` 启动时补偿
- [x] T13 测试：submit 失败不丢单、重复投递返回原 task_id、断在派发中途的重投、补偿只派发未标记任务
- [x] T14 全量回归：88 用例，失败 6，与基线一致
- [x] T15 git 提交（三块改动交织在 service.py，合并为一次提交）

## 结果

- 新增 `tests/test_queue_reliability.py`：14 个用例全绿。
- `enqueue_review` / `resume_task` 一并写入 `dispatched_at`，补偿器语义对所有投递路径一致。
- 顺带修复 `PostgresTaskStore._connect` 未关闭连接（生产上每次 DB 操作泄漏一个连接槽）。

## 已知残留（按 SPEC 记录）

- 租约过期后原进程恢复仍可能写结果，彻底防护需要把 lease_token 带入每一次结果写入。
