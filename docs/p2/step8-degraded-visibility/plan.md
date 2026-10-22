# P2 方向1 计划：暴露降级角色

## 改动面

| 文件 | 改动 |
|---|---|
| `pragent/telemetry.py` | `summary()` 增加 `degraded_roles` |
| `pragent/report.py` | 非空时在 Execution facts 增加一行 |
| `tests/test_degraded_reporting.py` | 新增。账本汇总、报告渲染、无降级时不改输出 |

不改动：`agentic_core.py`、`budget.py`、`gates.py`、任何 schema。

## 实施顺序

1. `telemetry.summary()`：在锁外从已复制的 `traces` 推导排序后的角色名列表。
2. `report.to_markdown()`：读 `execution["degraded_roles"]`，非空时插入一行。
3. 测试。

## 验证方法

**单元**

- 空账本：`degraded_roles == []`。
- 写一条 `trace("critic", "budget_exhausted", degraded=True)`：`["critic"]`。
- 写一条不带 `degraded` 的 `budget_exhausted`：仍是 `[]`（token/时间耗尽不算降级）。
- 两个角色降级：按字母序返回。
- 报告：`degraded_roles` 为空时 markdown 不含 `Degraded roles`；非空时含该行且列出角色。

**回归**

```
python -c "import sys,pathlib,unittest; sys.path.insert(0,'.'); sys.path.insert(0,'tests'); \
  names=sorted(p.stem for p in pathlib.Path('tests').glob('test_*.py')); \
  unittest.TextTestRunner(verbosity=1).run(unittest.TestLoader().loadTestsFromNames(names))"
```

235 + 新增，0 失败。

**端到端**

推一个新提交到 PR #3，确认新一轮审查成功且报告里 `degraded_roles` 为 `[]`
（本轮没有角色降级，说明这条通道只在真正降级时才出现）。

## 回滚

两处小改动，`git revert` 回到 step7。
