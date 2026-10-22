# P2 方向1 任务清单：远程取被改文件

## 实现

- [x] `GitHubClient.fetch_file(repository, path, ref="")`
  - [x] `GET /repos/{repo}/contents/{path}`，`ref` 非空时拼 `?ref=`
  - [x] `accept="application/vnd.github.raw"`、`raw=True`
  - [x] 路径分段转义（`safe="/"`），`#`/空格/中文可安全传递
- [x] `config.py` 新增
  - [x] `repository_source_enabled: bool = True`
  - [x] `repository_source_max_files: int = 40`
  - [x] `repository_source_max_file_bytes: int = 300_000`
  - [x] `repository_source_max_total_bytes: int = 2_000_000`
  - [x] `PRAGENT_REPOSITORY_SOURCE_*` 环境变量解析
- [x] `service._repository_source_provider(tenant_id, repository, task_input, parsed)`
  - [x] 关闭开关时直接返回 `None`
  - [x] 按 `parsed.files` 顺序取，跳过空路径与重复路径
  - [x] 单文件超 `max_file_bytes` 跳过（不截断）
  - [x] 累计超 `max_total_bytes` 立即停止
  - [x] 含 NUL 的内容跳过
  - [x] 单文件异常跳过，全部失败返回 `None`
  - [x] 用 `head_sha` 作 `ref`
  - [x] 无 `head_sha` 时拒绝取文件
  - [x] 无凭据时不发起请求
- [x] `agentic_core`
  - [x] `AgenticReviewer.__init__` 末尾加 `repository_source_provider=None`
  - [x] `_review_with_context`：本地源为空且 provider 存在时才调用
  - [x] provider 抛异常时记 trace `repository-source/fetch_failed` 并降级
  - [x] provider 成功时记 trace `repository-source/fetched`，带文件数

## 测试

- [x] `tests/test_remote_file_fetch.py`（16 用例）
  - [x] `fetch_file` URL/accept/ref 转义
  - [x] provider 正常取回多个文件
  - [x] provider 单文件超字节上限被跳过
  - [x] provider 总字节超限即停止
  - [x] provider 单文件抛错不影响其余
  - [x] provider 全失败返回 `None`
  - [x] provider 跳过含 NUL 的二进制内容
  - [x] `repository_source_enabled=False` 时不调用 GitHub
  - [x] 无 `head_sha` 时不调用 GitHub
  - [x] 无凭据时不调用 GitHub
  - [x] `max_files` 上限生效
  - [x] 有本地 `repository_root` 时 provider 不被调用
  - [x] 无本地源时 `repository_context.source_kind == "pinned-files"`
  - [x] provider 抛异常时报告 `available: false` 且不失败整次审查

## 验证

- [x] 全量回归：**215 用例，0 失败 0 错误**（本步新增 16）
- [x] `PRAGENT_REPOSITORY_SOURCE_ENABLED=false` 时行为回到 step1

## 实施中的两处设计修正（已回写 specify.md）

1. **无 `head_sha` 时不取文件**。原计划退化为默认分支，会产出「diff 与文件不对应」的
   混合审查，比不取更危险。改为直接跳过。
2. **无凭据时不发请求**。最初没有这道检查，结果是未配置 PAT 的部署每次审查都要付一次
   必然 401 的网络往返；在本机测试套件里表现为 `test_advanced.test_async_multi_agent_review`
   从 `SUCCESS` 退化成 `EXECUTING`（请求把队列跑挂住了）。加上凭据与 `head_sha` 双前置
   检查后恢复全绿。

## 收尾

- [x] 回填 `docs/p2/INDEX.md`
- [x] 提交
