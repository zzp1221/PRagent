# P2 方向1 任务清单：暴露降级角色

## 实现

- [x] `ExecutionLedger.summary()` 增加 `degraded_roles`
  - [x] 从 `agent_traces` 里 `event == "budget_exhausted"` 且 `degraded` 为真的记录推导
  - [x] 排序去重；无降级时为 `[]`
  - [x] 在锁外计算（traces 已复制）
- [x] `report.to_markdown()` 在 `degraded_roles` 非空时增加一行警告

## 测试

- [x] `tests/test_degraded_reporting.py`
  - [x] 空账本 → `[]`
  - [x] `degraded=True` 的 `budget_exhausted` → 该角色
  - [x] 不带 `degraded` 的 `budget_exhausted` → 仍为 `[]`
  - [x] 两个角色 → 按字母序
  - [x] 报告 markdown：无降级不出现该行，有降级出现且列出角色

## 验证

- [x] 全量回归 235 + 新增，0 失败
- [x] 推一个新提交到 PR #3，确认审查成功且 `degraded_roles` 为 `[]`

## 收尾

- [x] 回填 `docs/p2/INDEX.md`（把遗留边界从「未标注」改为「已标注」）
- [x] 提交
