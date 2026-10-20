# P0-2 SPEC：队列租约、跨进程执行锁与 Webhook 原子派发

## 现状证据

**长任务被并行重复执行**

- `pragent/task_queue.py:122-135`：`_reclaim_stale` 在每个 worker 的空闲循环里用
  `xautoclaim(min_idle_time=lease_seconds*1000)` 回收超租约消息，默认 60 秒。
- `pragent/task_queue.py:50-51`：`async_workers` 默认为 2，构造函数起 2 个 consumer。
- 一次多 Agent 审查包含 lead 4 次调用加 worker、critic，真实网络下常态超过 60 秒。
- 结论：consumer A 仍在执行时，consumer B 把消息 claim 走并再跑一遍，造成重复评论、
  重复计费、并发写同一 task_id。

**Webhook 静默丢单**

- `pragent/service.py:419-426`：`claim_webhook` 先落库，命中重复则直接返回
  `task_id=existing.get("task_id")`（此时可能为 None）并返回 HTTP 200。
- `pragent/service.py:439-451`：`_create_deferred_task`、`queue.submit`、
  `complete_webhook` 是三个独立步骤。
- 若 `queue.submit` 抛异常，webhook 记录已存在且 task_id 为空；GitHub 重投同一
  delivery_id 时走 duplicate 分支返回 200，GitHub 不再重试，任务永久丢失。
- 全仓无 outbox 或补偿扫描。

**跨进程无互斥**

- `pragent/store.py` 只有进程内 `threading.Lock`，跨进程零互斥。

## 目标（可验收）

1. 同一 task_id 在同一时刻只有一个执行者；重复投递的第二个消费者直接跳过。
2. 执行期超过租约的任务不被回收：执行期间持续续租，进程崩溃后租约自然过期可被接手。
3. Webhook 的任务记录与"已派发"标记在同一次数据库写入中完成，中间不存在可丢失窗口。
4. 已经完成派发的重复投递返回原 task_id；未完成派发的重复投递重新走一次派发。
5. 进程重启时补派"已创建但从未投递"的待执行任务。

## 非目标

- 不做 fencing 校验所有结果写入（见"残留风险"）。
- 不改队列后端（仍为 Redis Streams 或内存）。

## 设计决策

**租约落在 tasks 表**，不新建表：任务状态与租约同库同事务，崩溃恢复时一处可见。

新增列：`lease_owner`、`lease_token`、`lease_expires_at`。沿用既有 `_ensure_column` 迁移。

**获取租约用单条条件 UPDATE**（CAS 风格）而不是先 SELECT 再 UPDATE：
SQLite 的写操作串行化保证原子性，避免读写之间的竞态；PG 依赖行锁。

条件是"任务非终态 且 (无人持有 或 持有者是自己 或 租约已过期)"。成功则 `lease_token+1`，
返回新 token 作为本次执行的标识。

**续租用后台心跳线程**，间隔为租约的三分之一，覆盖整个 handler 执行期。
心跳停止（进程死亡）即释放，不需要显式清理。

**Redis PEL 侧同样心跳**：执行期间按 `XCLAIM ... IDLE 0` 重置消息空闲时间，
让 `xautoclaim` 不会把活跃消息抢走。

**Webhook 原子派发**：新增 store 方法，在一个事务里 INSERT tasks 并 UPDATE
webhook_deliveries.task_id。事务提交即代表"任务已存在且可被补偿扫描发现"。

**重复投递分支**：只有 webhook 记录里已有 task_id 时才短路返回；
task_id 为空说明上次断了，继续本次派发。

**补偿扫描**：`dispatched_at` 写入 tasks.input_json，submit 成功后标记。
启动时扫描 `state=PENDING` 且无 `dispatched_at` 且创建超过阈值（默认 60 秒）的任务重新提交。

## 残留风险（如实记录）

- 租约到期后原进程若从长时间停顿中恢复，仍可能写入结果。彻底防护需要把 lease_token
  作为条件写进每一次结果写入，改动面覆盖 harness 与 store 的全部写路径，本步不做。
- 重复投递依赖执行锁与终态判断兜底，不是严格的一次性语义。

## 约束

- 内存队列后端必须继续工作（测试默认用它）。
- 现有 `submit/close/dead_letters` 对外签名不变。
