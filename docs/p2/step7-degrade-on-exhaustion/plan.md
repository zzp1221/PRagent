# P2 方向1 计划：步数耗尽降级

## 改动面

| 文件 | 改动 |
|---|---|
| `pragent/agentic_core.py` | `BoundedRole` 加 `degrade_on_exhaustion`；最后一步清空工具清单；耗尽时返回降级 final |
| `tests/test_review_budget.py` | 新增「永不停止的 critic 降级而不失败」；调整一处断言（最后一步无工具） |

不改动：token/时间预算语义、Lead 的构造、任何门禁。

## 实施顺序

1. `BoundedRole.__init__` 加 `degrade_on_exhaustion: bool = False`。
2. `run` 里 `build_managed_context` 的工具清单在最后一步传 `[]`。
3. 循环结束时按标记选择降级返回或抛异常。
4. critic 与 worker 的构造点打开标记。
5. 测试。

## 验证方法

**单元**

- `CriticForeverClient` 永不返回 final：审查仍成功，critic 被调用 3 次，最后一次
  `available_tools` 为空。
- `CriticLookupClient` 两次查询后作答：前两步有工具、第三步没有。

**回归**

```
python -c "import sys,pathlib,unittest; sys.path.insert(0,'.'); sys.path.insert(0,'tests'); \
  names=sorted(p.stem for p in pathlib.Path('tests').glob('test_*.py')); \
  unittest.TextTestRunner(verbosity=1).run(unittest.TestLoader().loadTestsFromNames(names))"
```

234 + 新增，0 失败。

**端到端**

再次推送，确认 29 文件规模的审查不再因 critic 步数失败，并回写评论。

## 回滚

`agentic_core.py` 一处构造参数与两处分支。`git revert` 回到 step6。
