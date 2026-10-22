# P2 方向1 计划：远程取被改文件

## 改动面

| 文件 | 改动 |
|---|---|
| `pragent/github.py` | 新增 `fetch_file(repository, path, ref)`，走 `application/vnd.github.raw` |
| `pragent/config.py` | 新增 4 个配置项与对应环境变量解析 |
| `pragent/service.py` | 新增 `_repository_source_provider`，并在 `_build_agentic_reviewer` 里注入 |
| `pragent/agentic_core.py` | `__init__` 加 `repository_source_provider`；`_review_with_context` 在无本地源时调用它并记 trace |
| `tests/test_remote_file_fetch.py` | 新增。覆盖取文件、限额、二进制跳过、失败降级、本地源优先 |

不改动：`watchdog.py`、`task_queue.py`、任何工具的参数 schema、门禁逻辑。

## 实施顺序

1. `GitHubClient.fetch_file`：URL 用 `urllib.parse.quote(path, safe="/")`，`ref` 空则不加
   查询串。复用 `_request(..., accept="application/vnd.github.raw", raw=True)`。
2. `config.py` 加 `repository_source_enabled` / `repository_source_max_files` /
   `repository_source_max_file_bytes` / `repository_source_max_total_bytes` 与
   `PRAGENT_REPOSITORY_SOURCE_*` 解析。
3. `service._repository_source_provider`：按 `parsed.files` 顺序取，逐项做字节与 NUL 检查，
   累计超总上限即停止；任何异常记入返回的统计而不上抛。
4. `agentic_core.AgenticReviewer.__init__` 加参数（放最后，不破坏位置调用）；
   `_review_with_context` 分级取源并在 trace 记录结果。
5. 测试。

## 验证方法

**单元**

- `GitHubClient.fetch_file` 的 URL 与 accept 头：用子类覆盖 `_request` 捕获参数，
  断言 `ref` 拼进查询串、路径中的空格与 `#` 被转义。
- provider：给 10 个路径、单文件上限 100 字节，断言超限文件被跳过而不是截断。
- provider：某个文件抛 `RuntimeError`，其余仍被取到。
- provider：全部文件失败，返回 `None`。
- provider：内容含 `\x00` 的文件被跳过。
- `repository_source_enabled = False` 时 provider 返回 `None` 且不调用 GitHub。
- agentic：`task_input` 带 `repository_root`（真实临时目录）时 provider 不被调用。
- agentic：`task_input` 无 `repository_root` 但 provider 返回 `PinnedFiles` 时，
  `repository_context.source_kind == "pinned-files"`。

**回归**

```
python -c "import sys,pathlib,unittest; sys.path.insert(0,'.'); sys.path.insert(0,'tests'); \
  names=sorted(p.stem for p in pathlib.Path('tests').glob('test_*.py')); \
  unittest.TextTestRunner(verbosity=1).run(unittest.TestLoader().loadTestsFromNames(names))"
```

进入本步的基线是 199 用例 0 失败。

**端到端（step4 才做真实 PR）**

本步只验证到「审查报告里出现 `pinned-files` 与正确的 `file_count`」，
真实 PR 的完整链路验证留到 step4。

## 回滚

新增方法 + 一个可选注入点，默认开启但可用
`PRAGENT_REPOSITORY_SOURCE_ENABLED=false` 一键关闭并回到 step1 行为。
