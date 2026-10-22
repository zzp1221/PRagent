# P2 落地索引

每个步骤执行前先写 `specify.md`（问题证据、目标、设计决策、边界）、`plan.md`（改动面、
实施顺序、验证方法）、`task.md`（可勾选清单），完成后再回填结果。

## 方向1：仓库源接入（A 型改造）

对应 `docs/p0/INDEX.md:78-79` 登记的遗留边界「Webhook 链路仍未准备仓库快照」。

拆成四步，因为「把抽象换成可插拔」和「真的去拉文件」是两种风险：前者是纯重构，
后者要引入网络、缓存、限额和失败降级。混在一起出问题时无法判断是哪一层坏的。

| 步骤 | 主题 | 提交 |
|---|---|---|
| step1 | 仓库源抽象：`RepositorySource` / `LocalTree` / `PinnedFiles`，无源时收起 10 个工具 | 见下 |
| step2 | 远程取文件：GitHub contents API + service 层 provider，webhook 路径首次获得文件内容 | |
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

## 回归基线

```
python -c "import sys,pathlib,unittest; sys.path.insert(0,'.'); sys.path.insert(0,'tests'); \
  names=sorted(p.stem for p in pathlib.Path('tests').glob('test_*.py')); \
  unittest.TextTestRunner(verbosity=1).run(unittest.TestLoader().loadTestsFromNames(names))"
```

step1 完成时：**199 用例，0 失败 0 错误**（进入 P2 前的真实基线 176，step1 新增 23）。

## 仍然存在的边界

- **step1 之后主路径仍然没有内容**：`PinnedFiles` 已经能用，但还没有任何代码去填充它。
  Webhook 与轮询路径的 `repository_context.available` 依旧是 `false`，只是现在失败会以
  「工具根本不出现在 schema 里」的形式呈现，而不是十二个调用里十个报错。
- **`file_count` 对 `LocalTree` 为 `None`**：枚举目录是 `os.walk` 全遍历，不在报告里重复付费。
- **`symbol` 仍然只对 `.py` 生效**：这是 step3 的范围。
