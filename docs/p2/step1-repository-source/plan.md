# P2 方向1 计划：仓库源抽象

## 改动面

| 文件 | 改动 |
|---|---|
| `pragent/repository_source.py` | 新增。`RepositorySource` 抽象、`LocalTree`、`PinnedFiles` |
| `pragent/repository_tools.py` | `__init__` 改收 `source`；`_files`/`_safe_path`/`repository_available` 改为走 source；`registry()` 空源时收起 10 个工具 |
| `pragent/agentic_core.py` | `repository_context` 增加 `source_kind`、`file_count` |
| `tests/test_repository_source.py` | 新增。覆盖三种输入形态、路径逃逸、物化、并发只读 |

不改动：`service.py`、`github.py`、`watchdog.py`、任何工具的参数 schema。

## 实施顺序

1. 写 `repository_source.py`：`LocalTree` 直接搬运 `repository_tools.py` 现有的
   `_files` 与 `_safe_path` 逻辑，行为逐字对齐（含 `SKIP_DIRS`、2MB 上限、20000 上限）。
2. 改 `RepositoryToolSuite.__init__`：字符串 → `LocalTree`，实例 → 直接用，空 → `None`；
   `self.root` 改为 `self._local_root()` 惰性取（避免构造时触发物化）。
3. 把 7 个依赖文件内容的工具改为 `self.source.read_text(...)`；
   `git_context`/`run_scanners`/`run_repository_checks` 改为 `self.source.local_path()`。
4. `registry()` 加空源裁剪。保留 `search_diff`、`changed_line`。
5. `agentic_core.py` 报告字段补 `source_kind`/`file_count`。
6. 补测试。

## 验证方法

**单元**

- `RepositoryToolSuite` 传目录字符串：`list_repository`/`read_file`/`search_repository`
  输出与改动前同目录下逐字一致（用固定 fixture 目录对照）。
- 传 `PinnedFiles`：`read_file` 命中、`read_file("../etc/passwd")` 报错、
  `symbol` 在冻结集上工作、`git_context` 返回 `available: False`。
- 传 `""`：`registry()` 只含 `search_diff`、`changed_line` 两项。
- 并发：8 线程同时读同一个 `PinnedFiles` 不报错。

**回归**

```
python -c "import sys,pathlib,unittest; sys.path.insert(0,'.'); sys.path.insert(0,'tests'); \
  names=sorted(p.stem for p in pathlib.Path('tests').glob('test_*.py')); \
  unittest.TextTestRunner(verbosity=1).run(unittest.TestLoader().loadTestsFromNames(names))"
```

基线 110 用例 0 失败（`docs/p0/INDEX.md:61`）。本步结束后应为 110 + 新增，0 失败。

**人工核对**

跑一次 `/v1/reviews` 带本地 `repository_root` 的真实审查，确认报告
`repository_context.source_kind == "local-tree"` 且工具轨迹里有真实 `read_file` 成功记录。

## 回滚

单文件新增 + 两处改造，`git revert` 该提交即可回到 `de2eef4` 的行为。无数据迁移，
无配置格式变更。
