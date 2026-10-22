# P2 方向1 任务清单：仓库源抽象

## 实现

- [x] 新增 `pragent/repository_source.py`
  - [x] `RepositorySource` 基类：`kind`、`list_files`、`read_text`、`resolve`、`local_path`、`describe`
  - [x] `LocalTree`：搬运现有 `_files`/`_safe_path` 逻辑，保留 `SKIP_DIRS`、2MB 单文件上限、20000 文件上限、越界校验
  - [x] `PinnedFiles`：不可变文件字典、`resolve` 只允许冻结集合内的键、`local_path` 惰性物化到 `TemporaryDirectory`、物化过程加锁
- [x] 改造 `pragent/repository_tools.py`
  - [x] `__init__` 形参 `root` → `source`，字符串自动包 `LocalTree`，空值视为无源
  - [x] `repository_available` 改为 `self.source is not None`
  - [x] `_files()` 走 `source.list_files()`
  - [x] `_safe_path` → `source.resolve()`
  - [x] `search_repository`/`read_file`/`symbol`/`read_project_controls`/`ast_analyze` 走 `source.read_text()`
  - [x] `git_context`/`run_scanners`/`run_repository_checks` 走 `source.local_path()` 与 `source.resolve()`
  - [x] `registry()` 无源时只保留 `search_diff`、`changed_line`
  - [x] 修正 `selected = allowed or set(specs)` 在 `allowed` 为空集时误判全量的逻辑
- [x] `pragent/agentic_core.py`：`repository_context` 增加 `source_kind`、`file_count`

## 测试

- [x] 新增 `tests/test_repository_source.py`（23 用例）
  - [x] `LocalTree` 列文件跳过 `SKIP_DIRS`、越界 `resolve` 报错
  - [x] `PinnedFiles` 读命中、读集合外键报错、`resolve` 不越界、物化后文件真实存在
  - [x] 8 线程并发读同一 `PinnedFiles` 无异常
  - [x] `RepositoryToolSuite("")` 的 `registry()` 只含 `search_diff`、`changed_line`
  - [x] `RepositoryToolSuite(目录)` 与旧行为一致：`list_repository`/`read_file`/`search_repository` 可用
  - [x] `RepositoryToolSuite(PinnedFiles)` 下 10 个工具不再抛「checkout is unavailable」
  - [x] `git_context` 在 `PinnedFiles` 下返回 `available: False` 而不是抛异常

## 验证

- [x] 全量回归：**199 用例，0 失败 0 错误**（真实基线 176，本步新增 23）
- [x] `test_evidence_gate.py` 中 `RepositoryToolSuite("", DIFF, parsed, ledger)` 的旧调用形态未改动且通过
- [x] 人工核对报告 `repository_context.source_kind`

## 实施中的两处偏离（记录，不改变验收结论）

1. **`LocalTree.describe()` 的 `file_count` 返回 `None`**。枚举文件树是 `os.walk` 全遍历，而工具调用本来每次都在走；
   再为报告多走一遍是纯浪费。`PinnedFiles` 是 `len(dict)`，返回真实数量。报告里 `None` 的含义是「未枚举」。
2. **`git_context` 在 `PinnedFiles` 下直接返回 `available: False`**，不尝试物化。物化出的临时树没有 `.git`，
   查了也只会得到空历史，反而多写一次盘。这个判断通过 `source.kind` 短路，避免触发物化。

## 收尾

- [x] 回填 `docs/p2/INDEX.md`
- [x] 提交
