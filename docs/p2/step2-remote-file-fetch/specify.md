# P2 方向1 SPEC：远程取被改文件（webhook 路径首次获得文件内容）

## 现状证据

**冻结集已经能工作，但没有任何代码去填充它**

- `pragent/repository_source.py:104` 起的 `PinnedFiles` 在 step1 就绪，
  `tests/test_repository_source.py` 证明它能驱动 `read_file`/`symbol`/`ast_analyze`。
- `pragent/agentic_core.py:442-445` 仍然只从 `task_input["repository_root"]` 或
  `os.path.isdir(repository)` 取源；两者在 webhook 路径下恒为空。
- `pragent/service.py:331-361` 与 `:363-395` 创建的 task input 里没有该键，
  `pragent/config.py` 也没有任何可配置的仓库路径来源。
- 结果：`repository_context.available` 在真实 PR 上恒为 `false`，step1 只是把
  「十个工具报错」变成「十个工具不出现」，能力本身没有增加。

**取文件的能力已经在客户端里**

- `pragent/github.py:34-38`：`fetch_diff` 用 `accept="application/vnd.github.raw"` 取原文，
  同一套 `_request` 重试与限流处理可直接复用于单文件读取。
- 凭据方面无需新增权限：README 已要求 `Contents: Read`，contents API 用的就是这一项。

**版本必须锁定在被审提交**

- `pragent/service.py:340` 的 webhook 路径与 `:382` 的轮询路径都会把 `head_sha` 写进
  task input。按分支名取文件会在 PR 有新推送时让内容与 diff 漂移。

## 目标（可验收）

1. webhook 与轮询创建的审查，在 `repository_root` 为空时自动拉取本次 diff 涉及的
   文件内容，构造 `PinnedFiles` 交给工具套件；报告 `repository_context.source_kind`
   为 `pinned-files`，`file_count` 等于实际取到的文件数。
2. 取文件失败不失败整次审查：单文件失败跳过，全部失败退回 step1 行为
   （`available: false`），并在 trace 记一条 `repository-source` 事件。
3. 有硬上限：文件数、单文件字节、总字节三重限制，默认分别 40 / 300000 / 2000000，
   可用环境变量覆盖；超限的文件跳过而不是截断。
4. 二进制文件（内容含 NUL 字节）跳过，不进入冻结集。
5. 显式提供 `repository_root` 的 API 调用行为不变：本地目录优先，不产生任何网络请求。
6. 现有 199 个用例全绿。

## 非目标

- 不索引全库、不拉 tarball/zipball、不做 `download_archive` 接线。PR 审查需要的是
  被改文件与其邻近上下文，不是仓库镜像。
- 不实现跨文件调用方发现（第二圈扩张）。本步只解决「改动的这几个文件看不全」。
- 不改 `symbol` 的语言支持范围（step3）。
- 不引入缓存层。一次审查取一次，task 结束即释放。

## 设计决策

**取文件放在 service 层，用现有 provider 模式注入**

`AgenticReviewer` 已经有 `scanner_provider` 与 `skill_provider` 两个回调
（`agentic_core.py:323,329`）。新增第三个 `repository_source_provider`，签名
`(tenant_id, repository, task_input, parsed) -> RepositorySource | None`。
这样 `agentic_core` 不依赖 `GitHubClient`，`service` 不依赖工具套件，分层不变。

**provider 只在本地源缺失时被调用**

`_review_with_context` 先按现有逻辑解析 `repository_root`；只有结果为空才调用 provider。
API 调用方传入本地路径时，一次网络请求都不会发生。这条顺序是可验收的（目标 5）。

**用 contents API 的单文件接口，不用 zipball**

`GET /repos/{repo}/contents/{path}?ref={sha}`，`Accept: application/vnd.github.raw`。
一个 PR 通常改 3-10 个文件，25 次请求远低于认证后的 5000 次/小时额度；
zipball 会让单次审查下载整个仓库，与「一次 PR 审查固定成本」的产品叙事冲突。

**只取 diff 里出现过的路径，且取一次**

路径来源是 `parsed.files`，不是 worker 的任意请求。worker 只能读冻结集里的文件
（`PinnedFiles.read_text` 对集合外的键直接报错），因此不存在「模型诱导服务端
拉任意路径」的通道 —— 路径集合在审查开始前就固定了。

**失败降级而不是重试到底**

`_request` 自带 4 次重试与限流等待，provider 层不再叠加。单文件异常直接跳过，
因为一个文件取不到不构成整次审查失败的理由；全失败才退回无源状态。

## 约束

- provider 在 worker 线程池启动**之前**调用（`agentic_core.py:445` 处构造 suite），
  因此串行取文件不会放大并发，但会拉长审查启动时间。40 个文件 × 单次往返是上界，
  因此默认文件数上限取 40 而非常见的百级。
- **没有 `head_sha` 就不取文件**。原设计打算退化为 contents API 的默认分支，实施时判定
  这是错的：默认分支的内容可能与被审 diff 不一致，审查会在「diff 说 A、文件说 B」的
  混合状态下出结论，比不取更危险。同步入口若确实需要文件内容，正确做法是调用方传
  `repository_root`（本步保证那条路径零网络请求）。
- **无凭据时直接跳过**。既不是 installation 也没有 `github_token` 的部署，每次请求都注定
  401。这条是实施中暴露出来的必要性修正：缺了它，未配置 PAT 的环境每跑一次审查都要付一次
  必然失败的网络往返，Windows 上的测试套件会因此挂住（`test_advanced` 曾因此从 SUCCESS
  退化为 EXECUTING）。
- 冻结集内容进入内存后不再校验一致性；审查期间上游推送新提交不会影响本次结果，
  这是「锁定被审提交」的期望行为。
- 单文件字节上限必须低于 GitHub contents API 的 1MB 原始返回上限，否则大于该值的
  文件会拿到一段 JSON 元数据而不是文件内容。
