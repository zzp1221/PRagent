# P0-4 PLAN：证据引用与工具结果交叉验证

## 改动面

| 文件 | 变更 |
|---|---|
| `pragent/telemetry.py` | 证据集合、`record_evidence`、`has_evidence`、summary/restore 支持 |
| `pragent/repository_tools.py` | 工具结果含 `evidence_id` 时登记 |
| `pragent/agentic_core.py` | diff AST 证据登记；`gate.apply` 传 ledger |
| `pragent/gates.py` | 前缀校验、账本校验、规则证据重算、计数入 checks |
| `tests/test_evidence_gate.py` | 新建：伪造、同源、前缀、重算、兼容性 |

## 实施顺序

1. `ExecutionLedger` 加 `evidence` 字典与两个方法；summary 输出 `evidence_ids`；restore 读回。
2. `repository_tools` 包装器登记证据 id。
3. `agentic_core` 的 diff AST 分支登记。
4. `gates.FindingGate.apply(findings, parsed, ledger=None)` 实现三级校验。
5. `agentic_core` 调用点传 `ledger`。
6. 测试覆盖六种情形。
7. 全量回归。

## 验证方法

- 伪造：`{"evidence_id": "semgrep:deadbeef", "tool": "semgrep"}` 且账本为空 → 高风险 finding 被拒，
  `checks["evidence"]["unverified"]` 计数增加。
- 同源：真实调用 `search_repository` 拿到 evidence_id 后引用 → 通过。
- 前缀：`evidence_id="local-rule:x"`、`tool="semgrep"` → 拒绝。
- 重算：构造 rule_id/path/line/content 一致 → 通过；改 rule_id → 拒绝。
- 兼容：`ledger=None` 时前缀一致即可通过。
- 回归：全量失败数不超过 6。

## 回滚

门禁校验逻辑集中在一个方法内，revert 即恢复旧行为。
