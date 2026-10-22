# P2 方向1 SPEC：仓库源抽象（RepositorySource）

## 现状证据

**工具套件只认一个本地目录，主路径没有目录**

- `pragent/repository_tools.py:41-51`：`RepositoryToolSuite.__init__` 只接受 `root: str`，
  内部 `os.path.abspath(root)` + `os.path.isdir` 校验，非目录即视为空。
- `pragent/repository_tools.py:73-80`：`_safe_path` 在 `self.root` 为空时直接
  `raise ValueError("repository checkout is unavailable for this review")`。
- `pragent/repository_tools.py:82-97`：`_files()` 在 `self.root` 为空时返回 `[]`。
- 后果：`read_file`、`ast_analyze`、`git_context` 抛异常；`list_repository`、
  `search_repository`、`symbol`、`locate_tests`、`read_project_controls` 静默返回空；
  `run_scanners`、`run_repository_checks` 显式 `available: False`。
  12 个工具里只有 `search_diff`、`changed_line` 真正可用。

**主路径不传该目录，且没有任何通道能传**

- `pragent/service.py:363-395`：`submit_polled_review` 的 `store.create` input 无
  `repository_root` 键；调用点 `pragent/watchdog.py:113`。
- `pragent/service.py:331-361`：`_create_webhook_task` 的 input 仅含 `diff_url`、
  `github_issue_url`、`head_sha` 等；调用点 `pragent/service.py:646`。
- `pragent/config.py` 无任何 `repository_root` 或仓库路径配置项。
- 唯一入口是 `pragent/api.py:502` 的 `/v1/reviews` 请求体字段。

**这是原始项目继承的设计边界，已在 P0 索引登记**

`docs/p0/INDEX.md:78-79`：「Webhook 链路仍未准备仓库快照：`repository_root` 只能由 API
调用方提供本地绝对路径，跨文件分析能力受限（对应上一轮评审的方向 1）。」

**抽象错位的根因**

`_files()` 用 `os.walk` 全库枚举、上限 20000 文件；`search_repository` 逐行全扫。这是
「审查者手里有工作树」的本地静态分析器形状，而产品主路径是服务端接 GitHub webhook，
物理上没有工作树。补 `repository_root` 参数解决不了问题，必须换掉这个抽象。

## 目标（可验收）

1. `RepositoryToolSuite` 接受三种输入：`RepositorySource` 实例、目录字符串、空值。
   空值以外两种都让 `repository_available` 为真，且工具行为与今天传入同等目录时一致。
2. 新增 `RepositorySource` 抽象与两个实现：`LocalTree`（包装现有 `os.walk` 行为）、
   `PinnedFiles`（内存中的冻结文件集，可懒物化为临时目录供 subprocess 类工具使用）。
3. 源为空时 `registry()` 只注册 `search_diff` 与 `changed_line`，模型不再看到必然失败的
   schema，账本不再产生 `repository checkout is unavailable` 的失败观测。
4. `repository_context` 报告字段在现有 `available`/`root_supplied` 之外增加
   `source_kind`（`local-tree`/`pinned-files`/空）与 `file_count`，能力状态对用户可见。
5. 现有 110 个用例全绿；`RepositoryToolSuite("", DIFF, parsed)` 的旧调用形态继续工作。

## 非目标

- 不实现远程取文件（`PinnedFiles` 的数据来源）——那是 step2，本步只把管道换成可插拔的。
- 不改变任何工具的参数 schema 与返回字段结构。
- 不改动 `run_scanners`/`run_repository_checks` 的固定命令与隔离语义。
- 不引入 tree-sitter 或其他解析依赖。

## 设计决策

**保留位置参数兼容，而不是全面改写调用点**：`__init__` 的形参名由 `root` 改为 `source`，
但传入字符串时自动包装成 `LocalTree`，传入 `None`/`""` 时视为无源。这样
`tests/test_evidence_gate.py:56,166` 的 `RepositoryToolSuite("", DIFF, self.parsed, ledger)`
无需改动，装配层的改动面收敛到一处。

**路径安全校验下沉到 source**：越界校验从 `_safe_path` 迁移到 `LocalTree` 内部
（`PinnedFiles` 天然只能取到冻结集合内的键，不需要路径拼接）。`_safe_path` 保留为
「取物化后的绝对路径」语义，仅服务 `git_context`、`run_scanners`、
`run_repository_checks` 这类需要真实文件系统的工具；对 `PinnedFiles` 触发的是一次懒物化。

**subprocess 类工具走物化而不是禁用**：`run_scanners` 与 `run_repository_checks` 需要
真实 cwd。`PinnedFiles.local_path()` 在首次调用时把冻结集合写入
`tempfile.TemporaryDirectory`，之后两者行为不变。`git_context` 额外要求 `.git` 存在，
冻结集不含 `.git`，因此它在远程形态下自然返回 `available: False` —— 这是正确的语义，
不是缺陷。

**条件注册而不是让工具内部报错**：模型看到 schema 就会尝试调用。源为空时把 10 个工具
从 registry 里摘掉，比保留它们并在调用时抛异常更省预算，也让失败率指标恢复可信。

## 约束

- `PinnedFiles` 的物化目录必须在 `RepositoryToolSuite` 生命周期内有效，析构时清理；
  实施上用 `TemporaryDirectory` 对象持有引用，避免过早回收。
- 单文件内容上限沿用现有 `read_file` 的 40_000 字符截断语义，不在 source 层截断。
- 源对象可能被多个 Worker 线程并发读取（`agentic_core.py:1083` 起用 ThreadPoolExecutor），
  实现必须是只读且线程安全的：不加锁、只读不可变字典。
- `LocalTree` 必须保留 `SKIP_DIRS` 跳过规则与 2_000_000 字节单文件上限，否则工具行为会漂移。
