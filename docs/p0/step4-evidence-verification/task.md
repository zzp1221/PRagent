# P0-4 TASK：证据引用与工具结果交叉验证（已完成）

- [x] T1 `ExecutionLedger` 增加证据集合与 `record_evidence` / `has_evidence`，summary 与 restore 一并支持
- [x] T2 `RepositoryToolSuite` 包装器登记工具证据 id
- [x] T3 `agentic_core` 的 diff AST 证据登记
- [x] T4 `FindingGate.apply` 支持 ledger，实现前缀 / 账本 / 规则重算三级校验
- [x] T5 `agentic_core` 门禁调用点传入 ledger
- [x] T6 新建 `tests/test_evidence_gate.py`
- [x] T7 用例：伪造强证据被拒、真实工具证据通过校验、借名被拒、规则重算通过、
      篡改 rule_id 被拒、diff 外行号被拒、无账本兼容、检查点恢复保留证据
- [x] T8 全量回归：103 用例，失败 6，与基线一致
- [x] T9 git 提交

## 实现中的一处设计修正

最初的规则证据重算用引用自带的 `rule_id` 作为输入，等于让被校验方同时提供论据和结论，
篡改用例因此通过。改为：

- `rule_id` / `path` / `line` 取自 finding，行内容取自 diff 中真实存在的 added line；
- 再用 `LocalRuleReviewer.RULES` 验证该规则的正则**确实命中**该行。

这样即使伪造 `rule_id`，也必须该规则真的触发，否则证据无效。
