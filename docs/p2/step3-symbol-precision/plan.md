# P2 方向1 计划：`symbol` 可用性

## 改动面

| 文件 | 改动 |
|---|---|
| `pragent/repository_tools.py` | `symbol` 重写为「Python AST + 多语言正则」双通道；新增模块级正则表与 `_imported_names` |
| `tests/test_symbol_lookup.py` | 新增。覆盖多语言定义、confidence、scope 三态、同名消歧 |
| `tests/test_repository_source.py` | 调整 1 处断言（definitions 现在带 `confidence`） |

不改动：`gates.py`、`agentic_core.py`、任何 schema。

## 实施顺序

1. 模块级常量 `SYMBOL_DEFINITION_PATTERNS`：扩展名 → 编译好的正则列表。
2. `_imported_names(tree) -> Set[str]`：收集 `Import`/`ImportFrom` 名字与别名。
3. `_python_symbol(...)`：现有 AST 逻辑抽出，产出 `confidence="exact"` 的定义，
   并记录本文件的定义名集合与 import 名集合。
4. `_text_symbol(...)`：正则定义查找（`confidence="heuristic"`）+ 引用查找
   （`scope="unresolved"`）。
5. `symbol()` 汇总：先跑 Python 通道，再跑文本通道，最后统一算 `scope` 与 `summary`。
6. 测试。

## 验证方法

**单元**（`tests/test_symbol_lookup.py`）

- Python 定义：`confidence == "exact"`。
- JS/TS 定义：`function helper(` 与 `const helper =` 都能被找到，`confidence == "heuristic"`。
- Go 定义：`func (s *Server) Handle(` 能被找到。
- `scope` 三态：同一冻结集里放三个文件，分别是「自己定义」「import 后调用」
  「无来处地调用」，断言三种 `scope`。
- 同名消歧：`a.py` 与 `b.py` 各定义 `helper`，`c.py` 未 import 地调用 `helper`，
  断言 `definitions` 两条且 `c.py` 的 caller 为 `unresolved`。
- `summary` 计数与实际条目一致。
- 超长单行被截断，不产生巨大输出。

**回归**

```
python -c "import sys,pathlib,unittest; sys.path.insert(0,'.'); sys.path.insert(0,'tests'); \
  names=sorted(p.stem for p in pathlib.Path('tests').glob('test_*.py')); \
  unittest.TextTestRunner(verbosity=1).run(unittest.TestLoader().loadTestsFromNames(names))"
```

进入本步基线 215 用例 0 失败。

**端到端**

在 step4 的真实 PR 上观察一次 `symbol` 调用，确认非 Python 场景下
`confidence: "heuristic"` 出现在轨迹里。

## 回滚

`symbol` 单函数重写 + 一个测试文件。`git revert` 即可回到 step2 行为，
无跨模块影响。
