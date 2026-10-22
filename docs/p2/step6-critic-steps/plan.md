# P2 方向1 计划：给 Critic 足够的验证步数

## 改动面

| 文件 | 改动 |
|---|---|
| `pragent/agentic_core.py` | `max_steps=2 if critic_tools else 1` → `3` |
| `tests/test_review_budget.py` | 新增两个用例：critic 能连做两次查询后回答；无工具时仍单步 |

不改动：worker 步数、预算、门禁、任何 schema。

## 实施顺序

1. 改 `agentic_core.py` 的一处常量，并在注释里说明三步的构成。
2. 加测试：一个「critic 连续两次工具调用再 final」的 fake client，
   断言审查成功且 critic 收到 3 次调用机会。
3. 反向用例：critic 无工具时只有 1 次调用。

## 验证方法

**单元**

- `CriticLookupClient`：critic 第一次返回 tool、第二次返回 tool、第三次返回 final。
  在 `max_steps=3` 下审查应成功；若仍是 2，会抛 `critic step budget exhausted`。
- 无工具路径：`repository_available` 为假时 critic 单次调用，与既有断言一致。

**回归**

```
python -c "import sys,pathlib,unittest; sys.path.insert(0,'.'); sys.path.insert(0,'tests'); \
  names=sorted(p.stem for p in pathlib.Path('tests').glob('test_*.py')); \
  unittest.TextTestRunner(verbosity=1).run(unittest.TestLoader().loadTestsFromNames(names))"
```

233 + 新增，0 失败。

**端到端**

推一个新提交到 PR #3，确认 29 文件规模的审查不再因 critic 步数失败。

## 回滚

一处常量。`git revert` 即回到 step5 行为。
