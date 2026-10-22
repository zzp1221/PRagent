# P2 方向1 SPEC：文案诚实化 + 真实 PR 端到端验证

## 现状证据

**首屏承诺超出默认路径的能力**

- `README.md:3`：「安全与正确性/可靠性两个 Worker 用仓库工具取证」。默认路径（webhook
  与轮询）在 step2 之前没有任何仓库内容，这句话描述的是一条主要靠 `/v1/reviews`
  手动传本地路径才成立的能力。
- `README.md:15`：「Worker 可按需调用仓库工具取证」。原始项目（`EvoAgent(3)/README.md:15`）
  首屏只写「带 Tool Registry、参数 Schema 校验和结构化 Observation 的 Agent Loop」，
  这一句是后来加上去的能力承诺。
- 能力侧的事实：step1-step3 之后 `PinnedFiles` + contents API 已经让 webhook 路径拿到
  本次变更涉及的文件，但 README 一个字都没更新，仍然停留在「仓库工具」这种夸大表述，
  同时也没有说明「看不到调用方」这个真实边界。

**端到端从未在被审代码状态里验证过**

- `docs/p2/INDEX.md` 记的 227 个用例全部是单元或进程内集成，没有任何一条跑过
  「GitHub 送 webhook → 队列 → 拉文件 → 模型审查 → 回写评论」的真实链路。
- step1-step3 的验收依赖「报告里出现 `pinned-files`」，而这一步只有真实 PR 能提供。

## 目标（可验收）

1. README 第 3 行与第 15 行改为与实际能力一致的表述：说明默认路径能拿到本次变更涉及
   的文件全文，并明确写出「看不到改动文件之外的调用方」这条边界。
2. 容器镜像重建后，服务对真实 PR 自动完成一次审查，并在该 PR 上回写审查评论。
3. 该次审查的报告里 `execution.repository_context.source_kind == "pinned-files"`，
   `file_count` 大于 0 —— 这是 step2 在真实链路上的唯一硬证据。
4. 审查轨迹中出现真实成功的 `read_file` 或 `symbol` 工具调用（不是失败观测）。
5. 全量回归 227 用例保持 0 失败。

## 非目标

- 不为本次验证改动任何生产逻辑。若真实链路暴露缺陷，单独记录并另开一步修，
  避免把「验证」和「修 bug」混在一次提交里。
- 不调优审查质量本身（发现多少问题、准确率多少）。本步只验证 A 型的基础设施接通。
- 不改动 `gates.py` 的证据强度名单，即使 step3 给出了 `confidence`/`scope` 信息。
  那个调整需要真实数据支撑，不是本步。

## 设计决策

**PR 内容就用这次文案修正本身**

这样一次提交同时完成两件事：把夸大表述改准确，以及给 agent 一个真实的、有意义的
审查对象。改 README 还能顺带验证 `pinned-files` 能读到 Markdown 全文 —— 如果只改 `.py`，
就看不出非代码文件是否进入冻结集。

**必须重建镜像，不能只重启容器**

`pragent-pragent-1` 跑的是 step0 之前的代码。`docker compose up -d` 只会重启既有镜像，
A 型代码不会进去。必须 `--build`。这是端到端验证的前提，不是可选项。

**隧道与 webhook 必须同步**

`PRAGENT_PUBLIC_BASE_URL` 是 trycloudflare 主机名，每次起隧道都会变，而 GitHub 无法
访问 `127.0.0.1`。基线提交 `de2eef4` 加的 `-SyncWebhook` 参数正是为此：起隧道时
直接 PATCH 掉 GitHub 上的旧 hook，避免手工改。

**验证信号取自报告而不是日志**

日志只能说明「跑过了」，报告里的 `repository_context` 才能说明「拉到了几个文件」。
因此验证以 PR 评论内容或任务报告 JSON 为准。

## 约束

- 提交 PR 需要推分支到 `zzp1221/PRagent`。gh 已登录该账号并具备 `repo` scope。
- 审查消耗真实模型调用（DeepSeek）。一次审查按既有预算上限计费，不需要额外放量。
- 隧道是临时的，验证窗口以隧道存活为限；验证结束后不保留隧道进程。
- 若 GitHub 因隧道抖动漏投递，用 Webhook 的 Redeliver 或等轮询兜底，不为此改代码。
