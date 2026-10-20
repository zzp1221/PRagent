# P0 落地索引

每个步骤执行前先写 `specify.md`（问题证据、目标、设计决策、边界）、`plan.md`（改动面、
实施顺序、验证方法）、`task.md`（可勾选清单），完成后再回填结果。四步均已落地并通过回归。

| 步骤 | 主题 | 提交 |
|---|---|---|
| step1 | PR 级评论合并，消除同一 PR 的评论堆叠 | `45890f3` |
| step2 | 队列租约、跨进程执行锁、Webhook 原子派发与补偿 | `f767e89` |
| step3 | 自动修复绑定被审查的提交 | `7cebabb` |
| step4 | 证据引用与工具结果交叉验证 | `221f6cf` |

## 每一步解决了什么

**step1**：评论 marker 由 task_id 改为 `repository#number`，同一 PR 的后续审查更新原评论
而不是新增；`upsert_comment` 支持翻页与 PATCH 容错，他人伪造 marker 不会中断发布。
附带修复 SQLite 连接泄漏（每次 store 调用泄漏一个文件描述符，Windows 上导致库文件无法释放）。

**step2**：长任务执行期间持续重置 Redis PEL 空闲时间并续租数据库租约，消除"审查超过 60 秒
就被第二个 consumer 抢走并重复执行"；Webhook 的任务创建与交付记录同事务提交，中间失败不再
静默丢单，进程重启会补派未投递任务。附带修复 PostgreSQL 连接泄漏。

**step3**：审查时记录被审提交的 SHA，修复请求携带该 SHA；PR head 已变化时返回 `stale` 并
要求重新审查，读文件与测试归档统一使用不可变 SHA。此前这条能写入远端分支的路径没有任何测试。

**step4**：证据门禁不再接受"任意非空 evidence_id + 白名单工具名"，改为校验该 id 确实由本次
审查的某次工具调用产生；规则扫描器证据按 `(rule_id, path, line, content)` 重算且规则必须
真的命中该行。未通过的引用不计入有效/强证据，无法满足高风险门禁。

## 回归基线

```
python -c "import sys,pathlib,unittest; sys.path.insert(0,'.'); sys.path.insert(0,'tests'); \
  names=sorted(p.stem for p in pathlib.Path('tests').glob('test_*.py')); \
  unittest.TextTestRunner(verbosity=1).run(unittest.TestLoader().loadTestsFromNames(names))"
```

- 起点：70 用例，45 失败（39 个 Windows 文件锁、5 个缺 `evaluation_data/` 数据集、
  1 个 Python 3.14 `ast.unparse` 引号断言）。
- 现在：103 用例，6 失败，剩余失败与起点同源，均为环境/数据缺失，未被本次改动触及。
- 新增 33 个用例，全部通过。

## 已知残留（未在本批处理，按 SPEC 记录）

- 租约过期后原进程若从长时间停顿中恢复，仍可能写入结果。彻底防护需要把 lease_token 带入
  每一次结果写入（覆盖 harness 与 store 全部写路径）。
- 证据门禁只保证"引用真实存在且同源"，不判断"该工具输出是否支持这条结论"，后者需要模型判断。
- `pragent/fixer.py` 的 `SafeFixer` 不在任何装配路径上，是死代码，可单独清理。
- `evaluation_data/` 数据集缺失导致 5 个评测用例无法运行，属资源投入问题。
