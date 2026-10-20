# P0-2 PLAN：队列租约、执行锁与 Webhook 原子派发

## 改动面

| 文件 | 变更 |
|---|---|
| `pragent/store.py` | tasks 表加 lease 列；acquire/renew/release；`create_dispatched_webhook_task`；`list_undispatched_tasks` |
| `pragent/postgres_store.py` | 同上；并修复 `_connect` 未关闭连接 |
| `pragent/task_queue.py` | PEL 续租心跳；`_deliver` 接收 redis_id；回收时跳过活跃消息 |
| `pragent/service.py` | `_process_queued` 加租约与终态幂等；webhook 原子派发；`redispatch_pending` |
| `pragent/api.py` | 启动时调用 `redispatch_pending` |
| `tests/test_production_features.py` | 租约语义、重复投递、原子派发、补偿扫描 |

## 子块顺序

**2A 数据库租约**

1. `_init` 里加三列迁移。
2. 实现 `acquire_task_lease` / `renew_task_lease` / `release_task_lease`。
3. 心跳线程类 `TaskLease`：acquire 成功后在独立线程每 interval 续租，stop 时释放。
4. `_process_queued` 接入：拿不到租约就返回；终态任务直接返回。

**2B Redis PEL 续租**

1. `_deliver(envelope, redis_id="")`。
2. 执行期起心跳线程调用 `xclaim(..., min_idle_time=0, idle=0)`。
3. `_reclaim_stale` 保留，但只要心跳有效就不会命中活跃消息。

**2C Webhook 原子派发与补偿**

1. store 加 `create_dispatched_webhook_task`（单事务 INSERT + UPDATE）。
2. `handle_github_pull_request` 改用它，然后 submit，再标 `dispatched_at`。
3. duplicate 分支：有 task_id 才短路。
4. store 加 `list_undispatched_tasks`；service 加 `redispatch_pending`；api.run 启动时调用。

## 验证方法

- 租约：两个"进程"（两个 store 实例）并发 acquire 同一 task，只有一个成功。
- 过期：租约过期后另一个实例可以接管，token 递增。
- 心跳：持有期间推进时间，租约不过期（用短租约 + 真实等待）。
- 重复投递：`_process_queued` 连续调两次，第二次不产生第二份 report。
- 原子派发：模拟 submit 失败，webhook 记录的 task_id 非空且任务可被补偿扫描发现。
- 补偿：`redispatch_pending` 只提交无 dispatched_at 的 PENDING 任务。
- 全量回归：失败数不超过 6（已知既有环境失败）。

## 回滚

按子块分三次提交，可分别 revert。列迁移是 ADD COLUMN，向后兼容旧代码。
