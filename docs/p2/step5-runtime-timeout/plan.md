# P2 方向1 计划：对齐框架超时与审查预算

## 改动面

| 文件 | 改动 |
|---|---|
| `pragent/config.py` | 新增 `Settings.resolved_runtime_timeout()` |
| `pragent/service.py` | `ReviewHarness` 构造改用 `resolved_runtime_timeout()` |
| `tests/test_runtime_timeout.py` | 新增。覆盖推导规则与显式配置优先 |

不改动：`runtime.py`、`harness.py`、`budget.py`、任何测试既有断言。

## 实施顺序

1. `config.py` 加方法，读 `resolved_review_budget()["review_time_budget_seconds"]`。
2. `service.py:160` 换参数。
3. 测试。

## 验证方法

**单元**（`tests/test_runtime_timeout.py`）

- 默认：`timeout_seconds=120`、`agent_time_budget_seconds=60` → 480 + 60 = 540。
- 显式更小：`timeout_seconds=10` → 仍为 540（推导值更大）。
- 显式更大：`timeout_seconds=900` → 900（不被压低）。
- 显式审查预算：`agent_review_time_budget_seconds=30` → 30 + 60 = 90 与 timeout 取大。
- service 构造出的 `harness.timeout_seconds` 等于推导值。

**回归**

```
python -c "import sys,pathlib,unittest; sys.path.insert(0,'.'); sys.path.insert(0,'tests'); \
  names=sorted(p.stem for p in pathlib.Path('tests').glob('test_*.py')); \
  unittest.TextTestRunner(verbosity=1).run(unittest.TestLoader().loadTestsFromNames(names))"
```

227 + 新增，0 失败。

**端到端**

把 step5 的提交推到 PR #3 分支，触发一次新的轮询审查。预期：
- 该次审查不再出现无原因的 `task execution budget exceeded`
- 报告里 `review_budget.time_budget_seconds` 仍然是 480，且 `exhausted` 为空

## 回滚

两处小改动，`git revert` 即回到 step4 行为。没有配置格式变更。
