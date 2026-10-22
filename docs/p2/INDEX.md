# P2 落地索引

每个步骤执行前先写 `specify.md`（问题证据、目标、设计决策、边界）、`plan.md`（改动面、
实施顺序、验证方法）、`task.md`（可勾选清单），完成后再回填结果。

## 方向1：仓库源接入（A 型改造）

对应 `docs/p0/INDEX.md:78-79` 登记的遗留边界「Webhook 链路仍未准备仓库快照」。

拆成多步，因为「把抽象换成可插拔」「真的去拉文件」「提高符号精度」「改文案」
「修超时分层」「修盲审深度」是六种不同性质的风险。混在一次提交里出问题时无法判断是
哪一层坏的。

| 步骤 | 主题 | 提交 |
|---|---|---|
| step1 | 仓库源抽象：`RepositorySource` / `LocalTree` / `PinnedFiles`，无源时收起 10 个工具 | `dc7c068` |
| step2 | 远程取文件：GitHub contents API + service 层 provider | `5246505` |
| step3 | `symbol` 多语言定义查找 + `confidence`/`scope` 标注 | `029748e` |
| step4 | 文案诚实化 + 真实 PR 端到端验证 | `0167c2e` |
| step5 | 框架超时不再先于审查预算触发 | `09b5324` |
| step6 | Critic 拿到工具后退化为「看一眼就点头」 | `f7ece65` `2924aa0` |

## 解决了什么

**step1**：`RepositoryToolSuite` 不再要求一个本地工作树，改为接受 `RepositorySource`。
目录字符串仍然可用，所以 API 路径与既有测试零改动。`PinnedFiles` 提供「冻结文件集」
这一新形态：读走内存，需要真实目录的工具（scanner、compile/test）首次调用时惰性物化。
`git_context` 在冻结集下明确返回 `available: False`，因为它需要 `.git`。
无源时 `registry()` 只注册 `search_diff` 与 `changed_line`：模型不再看到必然失败的 schema，
账本也不再堆积 `repository checkout is unavailable` 的失败观测。
附带修正 `selected = allowed or set(specs)` 在 `allowed` 为空集时被当作「未传」的缺陷。

**step2**：`GitHubClient.fetch_file` 用 contents API 的 raw 形态读单文件；
`service._repository_source_provider` 按 `parsed.files` 取本次 diff 涉及的文件，
构造函数级 `PinnedFiles` 交给工具套件。webhook 与轮询路径第一次真正拿到了文件内容。
三重上限（40 文件 / 300KB 单文件 / 2MB 总量）与二进制跳过保证边界可控；单文件失败跳过，
全失败退回 step1 行为。两道前置检查是实施中补的：没有 `head_sha` 就拒绝取（避免 diff
与文件版本不一致），没有凭据就不发请求（避免每次审查付一次必然 401 的往返）。

**step3**：`symbol` 从「只认 `.py` 的裸名匹配」变成双通道。Python 走 AST 并标
`confidence: "exact"`；JS/TS/Go/Java/Ruby/Rust/PHP 按语言族锚定正则标 `"heuristic"`。
每个 caller 获得 `scope`：`local`（本文件定义）、`imported`（本文件 import 了该名字）、
`unresolved`（无来处，可能是同名不同物）。这不能消除同名碰撞 —— 那需要完整类型系统 ——
但它把不确定性显式交给模型，而不是伪装成确定命中。

**step4**：README 不再承诺「Worker 用仓库工具取证」。现在写的是默认路径按被审提交的 SHA
读取本次变更涉及的文件全文，并明确「改动文件之外的调用方不在这个范围内」。

**step5**：`Settings.resolved_runtime_timeout()` 让框架硬杀不小于审查自身的软上限
加一分钟收尾余量。此前 `runtime.py:164` 的 120 秒硬杀永远先于 480 秒的
`review_time_budget_seconds` 触发，用户只会看到无原因的
`task execution budget exceeded`。

**step6**：critic 拿到仓库源时从 2 步提到 3 步（两次验证查询 + 一次决定）。
A 型之前 `critic_tools` 恒为假、critic 永远单步盲审；A 型之后它可能拿到 29 个文件的
冻结集，却只有「一次查询 + 一次回答」的空间，真实链路因此以
`critic step budget exhausted` 失败过。

只抬步数不够：一个坚持要工具的 critic 仍能在下一步撞死整次审查。所以加了两层结构保证。
第一层是**最后一步不再暴露工具**（`visible_tools = [] if step >= max_steps`）——
「最后一步必须出结论」从此是确定的，不再取决于模型是否听话。
第二层是 `degrade_on_exhaustion`：worker 与 critic 万一仍然耗尽，就带着已有观测返回
`_degraded` 结果，而不是抛 `RuntimeBudgetExceeded` 把一份已经有其他角色结果的审查打掉。
Lead 保持致命语义，因为没有 Lead 的合成就没有报告。

这两层分开记录：步数从 2 抬到 3 在 `docs/p2/step6-critic-steps/`，
最后一步清空工具清单与 `degrade_on_exhaustion` 在 `docs/p2/step7-degrade-on-exhaustion/`。
分两次提交是因为第二层不是「再多给一步」的延伸，而是把「耗尽」从致命错误改成降级语义 ——
它同时改变 worker 的行为，值得单独可回滚。

## 回归基线

```
python -c "import sys,pathlib,unittest; sys.path.insert(0,'.'); sys.path.insert(0,'tests'); \
  names=sorted(p.stem for p in pathlib.Path('tests').glob('test_*.py')); \
  unittest.TextTestRunner(verbosity=1).run(unittest.TestLoader().loadTestsFromNames(names))"
```

进入 P2 前：176。step1 后 199。step2 后 215。step3 后 227。step4 后 227。
step5 后 233。step6 后 **235，0 失败 0 错误**。

## 端到端验证（PR #3）

https://github.com/zzp1221/PRagent/pull/3

用轮询路径触发（本机没有 `cloudflared`，公网隧道不可用；轮询不需要公网入口，而且它正是
本方向要修的「另一条主路径」）。

### 第一轮：25 文件，成功

任务 `545fc4f1-a020-4990-a25b-9ecda95e9373`，SUCCESS，head `0167c2e`。

报告：`{"available": true, "file_count": 25, "source_kind": "pinned-files", "root_supplied": false}`

Worker 与 Critic 的真实工具调用（全部 `ok: true`；step1 之前这些调用会抛
`repository checkout is unavailable` 或返回空）：

| 角色 | 工具 | 参数 |
|---|---|---|
| security | `read_file` | `pragent/github.py` 1-200 |
| security | `read_file` | `pragent/repository_source.py` 1-260 |
| security | `read_file` | `pragent/repository_source.py` 1-157 |
| security | `search_repository` | `query="eval("` |
| security | `search_diff` | `query="token"` |
| critic | `read_file` | `pragent/service.py` 270-320 |

产出 2 条 medium finding，都指向本轮新写的 provider 代码的宽泛 `except Exception`；
证据引用 `read_file:548bf61cd2e049bd` 通过了门禁的 ledger 与路径归属校验。
PR 评论已按 marker `<!-- pragent-review:zzp1221/PRagent#3 -->` 回写。
成本：16 次模型调用、21 次工具调用、183465 tokens、95.2 秒。

### 第二轮：29 文件，暴露两个真实缺陷

任务 `0b8ea657-3d18-4828-8637-99211c6a98c6`，head `b82579c`，FAILED。

| 现象 | 根因 | 修复 |
|---|---|---|
| 同一轮轮询的 PR #1 任务 139 秒后失败，错误无原因 | 框架硬杀 120 秒先于审查软上限 480 秒触发 | step5 |
| 29 文件审查在 `critic step budget exhausted` 失败 | critic 有工具但只有 2 步 | step6 |

两次失败都不是 A 型的逻辑错误，而是 **A 型把审查从「读 diff」变成「读几十个文件 + 二十余次
工具调用」之后，原来够用的两个上限（超时、盲审步数）不再够用**。这正是端到端验证的价值：
单测覆盖不到这类「预算与深度不匹配」的问题。

### 第三轮：36 文件，两个修复都生效

任务 `2af51484-5f44-45b7-8368-fee529536abb`，head `bc98647`，**SUCCESS**，126 秒。

```json
{"available": true, "file_count": 36, "source_kind": "pinned-files", "root_supplied": false}
```

`review_budget` 全项未耗尽：`model_calls=18`、`tokens_used=207021 / 288000`、
`elapsed=126.2s / 480s`、`exhausted: ""`。

关键差异在 Critic —— 它这次真的做了两次独立查证：

| 角色 | 工具 | 参数 |
|---|---|---|
| security | `read_file` | `pragent/repository_source.py` 1-200 |
| security | `read_file` | `pragent/repository_tools.py` 1-200 |
| security | `read_file` | `pragent/github.py` 1-120 |
| security | `search_repository` | `query="eval("` |
| critic | `read_file` | `pragent/service.py` 280-320 |
| critic | `read_file` | `pragent/service.py` 260-312 |

第二轮里 Critic 只有一次 `read_file`（`service.py` 270-320）就被步数掐死；
这次它能用两步分别读 280-320 与 260-312，第三步在无工具的约束下出结论。
产出仍是 2 条 medium finding，指向 provider 的宽泛 `except Exception`。
PR 评论按同一 marker `<!-- pragent-review:zzp1221/PRagent#3 -->` upsert 更新，
没有堆叠新评论。

## 仍然存在的边界

- **冻结集只含被改文件，不含其调用方**：跨文件因果推理需要「谁调用了这个函数」，
  属于第二圈扩张。本方向解决的是「被改的这几个文件看不全」。
- **`symbol` 的跨文件精度只到 `scope` 标注**：能指出「这个调用点没有可解释的来处」，
  但不能确定它指向哪个同名符号。非 Python 是正则级，不是 AST 级。
- **`git_context` 在远程形态下不可用**：contents API 不提供 blame 与提交历史。
- **`file_count` 对 `LocalTree` 为 `None`**：枚举目录是 `os.walk` 全遍历，不在报告里重复付费。
- **并发审查会互相拖慢**：同一轮轮询提交多个 PR 时它们争抢模型配额。step5 让这种情况
  表现为「软上限带原因地触发」，step6 让单角色步数耗尽降级而不是打掉整次审查，
  但没有做并发限流。
- **A 型让审查变慢**：真实 PR 从「读 diff」变成「读 25-36 个文件、20+ 次工具调用」，
  耗时 95-126 秒。这是用时间换上下文的取舍，不是待修的缺陷。
- **`degrade_on_exhaustion` 产出的结果没有经过 Critic 裁决**：critic 万一耗尽，报告里的
  finding 就是未经挑战的候选。降级比整次失败好，但结论强度确实弱一档。step8 已让这一点
  可见：`execution.degraded_roles` 非空时，PR 评论的 Execution facts 会多出一行
  `Degraded roles: ... (ran out of steps; their results are partial)`。
  **仍未做的是**：把「有角色降级」升级成门禁条件或降低整体置信度，那需要真实数据支撑。
