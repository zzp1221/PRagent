# step6 TASK：租约 fencing（已完成）

- [x] T1 `TaskLease.fence` 与 `LeaseLost`
- [x] T2 `store.succeed/fail/transition/cancel` 支持 fence，返回 bool
- [x] T3 `postgres_store` 同步支持
- [x] T4 `harness.run` 接受 fence 并透传，失去所有权时抛 `LeaseLost`
- [x] T5 `service` 接线并捕获 `LeaseLost`
- [x] T6 测试：过期执行者写入被拒、接管者写入成功、无 fence 行为不变、审查中途失去锁即中止
- [x] T7 全量回归：106 用例，失败 5，与上一步一致
- [x] T8 git 提交

## 实现细节

写入统一走 `_write_state`：先执行带 fence 条件的单条 UPDATE，`rowcount != 1` 即视为失去
所有权，不写状态也不写 trace，直接返回 False。fence 为 None 时不附加条件，同步路径与既有
测试零改动。

`fail` 与 `cancel` 的失败分支不会因 fencing 再抛异常，避免掩盖原始错误；只有 `succeed`
和 `transition` 被拒时抛 `LeaseLost`，由 `service` 捕获后只记指标，任务交给当前持锁者。

## 残留边界（记录在 SPEC，本步不解决）

fencing 只保护数据库写入。执行者失去锁后仍可能已产生外部副作用（模型调用、GitHub 评论）。
