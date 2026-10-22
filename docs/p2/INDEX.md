# P2 落地索引

每个步骤执行前先写 `specify.md`（问题证据、目标、设计决策、边界）、`plan.md`（改动面、
实施顺序、验证方法）、`task.md`（可勾选清单），完成后再回填结果。

## 方向1：仓库源接入（A 型改造）

对应 `docs/p0/INDEX.md:78-79` 登记的遗留边界「Webhook 链路仍未准备仓库快照」。

拆成四步，因为「把抽象换成可插拔」和「真的去拉文件」是两种风险：前者是纯重构，
后者要引入网络、缓存、限额和失败降级。混在一起出问题时无法判断是哪一层坏的。

| 步骤 | 主题 | 提交 |
|---|---|---|
| step1 | 仓库源抽象：`RepositorySource` / `LocalTree` / `PinnedFiles`，无源时收起 10 个工具 | `dc7c068` |
| step2 | 远程取文件：GitHub contents API + service 层 provider，webhook 路径首次获得文件内容 | 见下 |
| step3 | `symbol` 在冻结集上做对：import 关系过滤，消除同名碰撞 | |
| step4 | 文案诚实化 + 全量回归 + 真实 PR 端到端验证 | |

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
构造函数级 `PinnedFiles` 交给工具套件。webhook 与轮询路径第一次真正拿到了文件内容，
`repository_context.source_kind` 变为 `pinned-files`。三重上限（40 个文件 / 300KB 单文件 /
2MB 总量）与二进制跳过保证取文件的边界可控；单文件失败跳过，全失败退回 step1 行为。
两道前置检查是实施中补的：没有 `head_sha` 就拒绝取（避免 diff 与文件版本不一致），
没有凭据就不发请求（避免每次审查付一次必然 401 的往返）。

## 回归基线

```
python -c "import sys,pathlib,unittest; sys.path.insert(0,'.'); sys.path.insert(0,'tests'); \
  names=sorted(p.stem for p in pathlib.Path('tests').glob('test_*.py')); \
  unittest.TextTestRunner(verbosity=1).run(unittest.TestLoader().loadTestsFromNames(names))"
```

step1 完成时：**199 用例，0 失败 0 错误**。
step2 完成时：**215 用例，0 失败 0 错误**。

## 仍然存在的边界

- **`file_count` 对 `LocalTree` 为 `None`**：枚举目录是 `os.walk` 全遍历，不在报告里重复付费。
- **`symbol` 仍然只对 `.py` 生效**：这是 step3 的范围。
- **冻结集只含被改文件，不含其调用方**：跨文件因果推理需要「谁调用了这个函数」，
  那属于第二圈扩张，不在本方向。step2 解决的是「被改的这几个文件看不全」。
- **`git_context` 在远程形态下永远不可用**：contents API 不提供 blame 与提交历史。

