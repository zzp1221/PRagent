# P2 方向1 任务清单：文案诚实化 + 真实 PR 端到端验证

## 文案

- [x] `README.md:3` 改为「用本次变更涉及的文件与 diff 取证」
- [x] `README.md:15` 改为「读文件全文、查符号定义与调用点、定位相关测试」
- [x] 新增一条文件上下文说明，写明来源（按被审提交 SHA 读取）与边界（不含改动文件之外的调用方）
- [x] `README.md` 架构图里的「Worker 使用仓库工具取证」改为「文件内容与 diff」
- [x] 全仓检查无残留的「仓库工具取证 / 仓库级」表述

## 端到端验证

- [x] `docker compose up -d --build pragent` 重建镜像（让 step1-step3 生效）
- [x] 容器 healthy，且容器内 `GitHubClient.fetch_file` 与
      `ReviewService._repository_source_provider` 均存在
- [ ] ~~起 quick tunnel，`-SyncWebhook zzp1221/PRagent` 同步 GitHub hook~~
      **改为轮询路径**：本机没有安装 `cloudflared`，公网隧道不可用。轮询不需要公网入口，
      而且它正是本方向最初要修的「另一条主路径」，验证价值不低于 webhook。
- [x] 通过 `/v1/onboarding/watches` 注册 `zzp1221/PRagent` 的 poll 订阅
- [x] 从 `main` 开 `feature/repository-source`，提交 5 个 commit，push
- [x] 开 PR：https://github.com/zzp1221/PRagent/pull/3 （25 文件 / 1976 增行 / 95KB diff）
- [x] 服务自动收到轮询并完成审查（任务 `545fc4f1-a020-4990-a25b-9ecda95e9373`，SUCCESS）
- [x] PR 上出现审查评论（marker `<!-- pragent-review:zzp1221/PRagent#3 -->`）
- [x] 报告 `execution.repository_context.source_kind == "pinned-files"`
- [x] 报告 `file_count == 25` 且 `root_supplied == false`
- [x] 轨迹里出现多次 `ok: true` 的 `read_file` / `search_repository` / `search_diff`

## 回归

- [x] 227 用例 0 失败

## 端到端结果（硬证据）

**报告**

```json
{"available": true, "file_count": 25, "source_kind": "pinned-files", "root_supplied": false}
```

**Worker 与 Critic 的真实工具调用**（全部 `ok: true`，A 型之前这些调用会抛
`repository checkout is unavailable` 或返回空）

| 角色 | 工具 | 参数 |
|---|---|---|
| security | `read_file` | `pragent/github.py` 1-200 |
| security | `read_file` | `pragent/repository_source.py` 1-260 |
| security | `read_file` | `pragent/repository_source.py` 1-157 |
| security | `search_repository` | `query="eval("` |
| security | `search_diff` | `query="token"` |
| critic | `read_file` | `pragent/service.py` 270-320 |

`search_repository` 在冻结集上真的搜到了东西 —— 这是「仓库级工具在无 checkout 环境里工作」
最直接的证据。Critic 读 `service.py:270-320` 正是 `_repository_source_provider` 所在区间，
它用这段内容验证了两条发现。

**审查产出**：2 条 medium finding，都指向 `pragent/service.py`（本轮新写的 provider 代码）的
宽泛 `except Exception`。证据引用 `read_file:548bf61cd2e049bd` 通过了门禁的 ledger 校验与
路径归属校验 —— 说明这条证据确实来自冻结集，而不是伪造 id。

**执行成本**：16 次模型调用、21 次工具调用、183465 tokens、95.2 秒。

## 端到端暴露的缺陷（转 step5）

同一轮轮询同时提交了两个任务（PR #1 与 PR #3），并发争抢模型配额：

| 任务 | 文件数 | diff | 耗时 | 结果 |
|---|---|---|---|---|
| PR #3 | 25 | 97529 字符 | 97.9 秒 | SUCCESS |
| PR #1 | 1 | 1562 字符 | 139.0 秒 | FAILED `task execution budget exceeded` |

失败原因不是 A 型的逻辑问题，而是 **两个时间预算互相矛盾**：
`pragent/runtime.py:164` 的硬杀取 `Settings.timeout_seconds`（默认 120 秒），
而审查自己的软上限 `review_time_budget_seconds` 是 `agent_time_budget_seconds × 8`（480 秒）。
更紧的那个先触发，而且它的错误信息不带任何原因。A 型让一次真实审查从「读 diff」变成
「读 25 个文件 + 21 次工具调用」，耗时升到 98 秒，120 秒的余量只剩 23%。

## 收尾

- [x] 回填 `docs/p2/INDEX.md`
- [x] 提交
