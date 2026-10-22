# P2 方向1 任务清单：暴露降级角色

## 实现

- [x] `ExecutionLedger.summary()` 增加 `degraded_roles`
  - [x] 从 `agent_traces` 里 `event == "budget_exhausted"` 且 `degraded` 为真的记录推导
  - [x] 排序去重；无降级时为 `[]`
  - [x] 在锁外计算（traces 已复制）
- [x] `report.to_markdown()` 在 `degraded_roles` 非空时增加一行警告

## 测试

- [x] `tests/test_degraded_reporting.py`（8 用例）
  - [x] 空账本 → `[]`
  - [x] `degraded=True` 的 `budget_exhausted` → 该角色
  - [x] 不带 `degraded` 的 `budget_exhausted` → 仍为 `[]`（token/时间耗尽不算降级）
  - [x] 两个角色 → 按字母序
  - [x] checkpoint 往返后仍能推导（`restore` 恢复 `agent_traces`）
  - [x] 报告 markdown：无降级不出现该行，有降级出现且列出角色
  - [x] 警告位于 Execution facts 块内

## 验证

- [x] 全量回归：**243 用例，0 失败 0 错误**（本步新增 8）
- [x] 推一个新提交到 PR #3，审查成功

## 端到端：这次降级是真实发生的

任务 `2d2d4c49-4a38-414b-9956-13385c0ea9e1`，head `d23ba71`，**SUCCESS**，141 秒。

PR 这次有 **42 个文件变更**，超出 `repository_source_max_files = 40` 的上限：
`repository_context.file_count` 停在 40，而 diff 报了 42。

```
2 [EXECUTING] Reviewing 42 changed files
3 [REVIEWING] Validating and ranking 2 findings
4 [SUCCESS] Review completed
```

security worker 想读的东西超过三步能给的空间，**真的耗尽了步数并降级**：

```json
{"available": true, "file_count": 40, "source_kind": "pinned-files", "root_supplied": false}
"degraded_roles": "security"
```

PR 评论本体因此多出一行（已确认渲染在 Execution facts 块内）：

```
- Degraded roles: `security` (ran out of steps; their results are partial)
```

这次不需要构造场景：A 型把冻结集撑到 40 个文件之后，Worker 的步数上限自然会成为约束。
改之前这条信息只存在于 `agent_traces` 里，审查看起来和正常完成没有区别。

## 收尾

- [x] 回填 `docs/p2/INDEX.md`（把遗留边界从「未标注」改为「已标注」）
- [x] 提交
