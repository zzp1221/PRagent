# step7 PLAN：证据位置范围校验

## 改动面

| 文件 | 变更 |
|---|---|
| `pragent/telemetry.py` | 记录 evidence 的文件范围；summary/restore 兼容 |
| `pragent/repository_tools.py` | 登记时提取 path 参数 |
| `pragent/gates.py` | 范围工具集合与位置一致性校验 |
| `tests/test_evidence_gate.py` | 用例：跨文件证据被拒、同文件通过、无路径工具不受影响 |

## 实施顺序

1. `ExecutionLedger` 增加 `evidence_subjects` 与 `evidence_subject()`，summary/restore 支持。
2. `RepositoryToolSuite._remember_evidence` 传入 arguments 提取 path。
3. `FindingGate` 增加 `PATH_SCOPED_EVIDENCE_TOOLS` 与路径规范化比较。
4. 测试。

## 验证

- `ast_analyze` 指向 `b.py`，发现声明在 `a.py` → 不计入强证据，高风险发现被拒。
- 同一文件 → 通过。
- `search_diff`（无 path 参数）→ 不受影响。
- 全量失败数不超过 5。

## 回滚

新增校验集中在一个方法内，且账本缺位置时跳过，revert 即恢复。
