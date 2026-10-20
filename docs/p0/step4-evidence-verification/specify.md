# P0-4 SPEC：证据引用与工具结果交叉验证

## 现状证据

`pragent/gates.py:42-47` 的"证据"是自证的：

```python
refs = [item for item in finding.evidence_refs if isinstance(item, dict)]
valid_refs = [item for item in refs if item.get("evidence_id") and item.get("tool")]
strong_refs = [item for item in valid_refs
               if str(item.get("tool")) in self.STRONG_EVIDENCE_TOOLS]
```

只要 `evidence_id` 与 `tool` 是两个非空字符串即算"有效引用"，`tool` 落在白名单里即算
"强证据"。没有任何一处校验：

- 该 `evidence_id` 是否由本次任务的某次工具调用真正产生；
- 声明的 `tool` 与该 id 是否同源；
- 引用内容是否真的支持结论（语义层面，见非目标）。

因此模型可以用 `{"evidence_id": "anything", "tool": "semgrep"}` 通过高风险门禁，
把没有工具支撑的结论发布出去。

## 可实现性依据

工具结果本来就带可校验的标识：

- `pragent/repository_tools.py:29-37`：`_evidence` 生成 `evidence_id = "{tool}:{sha256(output)[:16]}"`
- `pragent/agentic_core.py:1346-1352`：diff AST 生成 `diff-ast:{sha256(payload)[:16]}`
- `pragent/reviewer.py:106-114`：规则扫描器生成
  `local-rule:{sha256(rule_id + path + line + content)[:16]}`，输入全部可从 diff 重算
- `pragent/telemetry.py:71-81`：每次工具调用都已记账，但只保存 1000 字符预览

## 目标（可验收）

1. 强证据引用的 `evidence_id` 必须在本次任务的账本里有对应工具调用记录。
2. `evidence_id` 的前缀工具名必须与声明的 `tool` 一致，挡住"借名字"。
3. 规则扫描器证据按确定性公式重算校验，篡改 rule_id 或行内容即失效。
4. 校验失败的引用不计入 `valid_refs` / `strong_refs`，因此无法满足高风险门禁。
5. 账本缺失时（非 agentic 路径、单元测试）退化为前缀一致性校验，不产生行为回归。
6. 被拒的未验证引用数量进入 `gate.checks`，可观测。

## 非目标

- 不做语义校验："这个工具输出是否真的支持这条结论"需要模型判断，超出确定性门禁范围。
  本步只保证"引用真实存在且同源"，不保证"引用支持结论"。

## 设计决策

**账本记 evidence_id 而不是完整输出**：`ToolCall` 现在只留 1000 字符预览，改成存完整结果会让
报告体积失控。在证据产生处登记 id 到账本集合，成本是每条一次字典写入。

**登记点放在产生处**：`repository_tools` 的工具包装器已持有 ledger；diff AST 的生成点也持有。

**前缀校验免费且必要**：`evidence_id` 自身编码了工具名，任何人可验证，不依赖账本。

**规则证据重算**：本地规则发现的 evidence_id 是 `(rule_id, path, line, content)` 的纯函数，
gate 手上有 `parsed.added_lines`，可以独立重算，无需信任调用方。

**向后兼容**：`ledger` 参数可选。缺省时行为与现在的前缀检查等价（更严一点点）。

## 约束

- `FindingGate.apply` 现有调用点只增参数，不破坏单测。
- 检查点恢复（`ledger.restore`）必须一并恢复证据集合，否则断点续跑会误杀。
