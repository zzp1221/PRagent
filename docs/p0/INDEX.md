# P0 落地索引

每个步骤执行前先写 `specify.md`（问题证据、目标、设计决策、边界）、`plan.md`（改动面、
实施顺序、验证方法）、`task.md`（可勾选清单），完成后再回填结果。

## P0 四项

| 步骤 | 主题 | 提交 |
|---|---|---|
| step1 | PR 级评论合并，消除同一 PR 的评论堆叠 | `45890f3` |
| step2 | 队列租约、跨进程执行锁、Webhook 原子派发与补偿 | `f767e89` |
| step3 | 自动修复绑定被审查的提交 | `7cebabb` |
| step4 | 证据引用与工具结果交叉验证 | `221f6cf` |

## P0 残留收尾

| 步骤 | 主题 | 提交 |
|---|---|---|
| step5 | 删除不在装配路径上的 `SafeFixer` | `35ccae6` |
| step6 | 结果写入的租约 fencing | `6b350f4` |
| step7 | 证据位置范围校验，并划清语义校验边界 | `aa96e23` |
| step8 | 恢复缺失的离线评测 corpus | `9888fbd` |

## 解决了什么

**step1**：评论 marker 由 task_id 改为 `repository#number`，同一 PR 的后续审查更新原评论
而不是新增；`upsert_comment` 支持翻页与 PATCH 容错，他人伪造 marker 不会中断发布。
附带修复 SQLite 连接泄漏（每次 store 调用泄漏一个文件描述符）。

**step2**：长任务执行期间持续重置 Redis PEL 空闲时间并续租数据库租约，消除"审查超过 60 秒
就被第二个 consumer 抢走并重复执行"；Webhook 的任务创建与交付记录同事务提交，中间失败不再
静默丢单，进程重启会补派未投递任务。附带修复 PostgreSQL 连接泄漏。

**step3**：审查时记录被审提交的 SHA，修复请求携带该 SHA；PR head 已变化时返回 `stale`。
读文件与测试归档统一使用不可变 SHA。此前这条能写入远端分支的路径没有任何测试。

**step4**：证据门禁不再接受"任意非空 evidence_id + 白名单工具名"，改为校验该 id 确实由本次
审查的某次工具调用产生；规则扫描器证据按 `(rule_id, path, line, content)` 重算且规则必须
真的命中该行。

**step5**：`SafeFixer` 从未被构造，删除该模块与其测试；`VerifiedPatchFixer` 与
`SuggestionOnlyFixer` 是实际装配的修复器。

**step6**：状态、报告、trace 与取消写入携带 `(owner, token)` fence，租约易主后被拒绝；
被拒写入抛 `LeaseLost`，由队列层当作"任务已归属他人"处理，而不是当作失败重试。

**step7**：账本额外记录证据涉及的文件，`ast_analyze` 针对 `b.py` 的结果不能再挂在
`a.py` 的发现上当强证据。

**step8**：`evaluation_data/` 下两份被代码引用却从未提交的离线 corpus 由确定性脚本重建。

## 回归基线

```
python -c "import sys,pathlib,unittest; sys.path.insert(0,'.'); sys.path.insert(0,'tests'); \
  names=sorted(p.stem for p in pathlib.Path('tests').glob('test_*.py')); \
  unittest.TextTestRunner(verbosity=1).run(unittest.TestLoader().loadTestsFromNames(names))"
```

会话开始时：70 用例，45 失败（39 个 Windows 文件锁、5 个缺数据集、1 个 `ast.unparse` 引号断言）。
现在：**110 用例，0 失败**。新增 40 个用例，全部通过。

验证方法：全量运行 4 次、`test_queue_reliability` 单独运行 5 次。其中一次全量出现过 1 个
无法复现的错误（其余 8 次全绿），已在新增测试的临时库清理里加入针对 Windows 瞬时句柄
占用的重试。既有测试文件未改动，它们的失败此前已由连接修复解决。

注意：项目没有 `tests/__init__.py`，`python -m unittest discover -s tests` 在 Python 3.14 下
会报 `Start directory is not importable`，请用上面的按模块名加载方式（或 `pytest`）。

## 仍然存在的边界（都是明确的设计取舍，不是待办）

- **fencing 只保护数据库写入**：执行者失去租约后仍可能已产生外部副作用（模型调用、
  GitHub 评论）。彻底消除需要把 token 校验推进到每一步外部调用之前。
- **证据门禁不做语义判断**："该工具输出是否支持这条结论"需要模型参与，那就不是确定性门禁。
  报告保留完整证据明细供人审阅。
- **离线 corpus 不是真实 PR 数据**：`validate_real_dataset` 要求 300 例真实来源，相关生产
  声明门禁保持关闭；合成数据在这里是设计要求。
- **Webhook 链路仍未准备仓库快照**：`repository_root` 只能由 API 调用方提供本地绝对路径，
  跨文件分析能力受限（对应上一轮评审的方向 1）。
- **没有 PR 级共享硬预算**：`_token_budget` 按角色独立计算，缺少整次审查的总量闸门
  （对应方向 3）。
