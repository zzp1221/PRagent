# P2 方向1 任务清单：给 Critic 足够的验证步数，并且耗尽时降级

## 实现

- [x] `pragent/agentic_core.py`：`max_steps=3 if critic_tools else 1`
      —— 两步验证加一步结论，`f7ece65` 已提交
- [x] `BoundedRole` 增加 `degrade_on_exhaustion`
      —— 步数耗尽时返回带 `_degraded` 标记的 final，而不是抛
      `RuntimeBudgetExceeded` 把整次审查打掉
- [x] 最后一步不再向模型暴露工具（`visible_tools = [] if step >= max_steps`）
      —— 结构上保证「最后一步必须出结论」，而不是指望模型自己收手
- [x] Worker 与 Critic 都启用 `degrade_on_exhaustion`；Lead 保持致命，
      因为没有 Lead 的合成就没有报告

## 测试

- [x] `tests/test_review_budget.py` 新增 `CriticLookupClient`
  - [x] critic 连做两次查询后仍能给出最终决定（`max_steps=2` 之前会抛
        `critic step budget exhausted`）
  - [x] critic 无工具时仍只被调用一次
- [x] 新增 `CriticForeverClient`
  - [x] 一个永远要工具的 critic：前两步有工具、第三步无工具
  - [x] 该场景降级而不是让审查失败
- [x] 既有 `test_critic_gets_tools_for_an_unevidenced_high_risk_candidate`
      改为断言「前两步有工具、最后一步没有」

## 验证

- [x] 全量回归：**235 用例，0 失败 0 错误**（step6 新增 2）
- [x] 推一个新提交到 PR #3，确认 36 文件规模不再因 critic 步数失败
      （任务 `2af51484`，SUCCESS，126 秒）
- [x] 第三次审查报告 `repository_context` 仍为 `pinned-files`，`file_count=36`
- [x] Critic 真的做了两次 `read_file`（`service.py` 280-320 与 260-312），
      第三步在无工具约束下出结论

## 实施记录

第一次修复只把 `max_steps` 从 2 抬到 3（`f7ece65`），但那只把边界往后推了一步：
一个坚持要工具的 Critic 仍然能在第四步撞死整次审查。真正的修法有两层——
步数够用（3 步）+ 结构上保证最后一步只能出结论（隐藏工具）+ 万一还撞上则降级
（`degrade_on_exhaustion`）。后两层是本次未提交改动补上的。

「隐藏工具」这个选择值得记一笔：它比「在 prompt 里要求模型收手」可靠得多，
因为模型是否听话不再影响正确性，只剩「第三步一定会给答案」这一个确定性事实。

## 收尾

- [ ] 回填 `docs/p2/INDEX.md`
- [ ] 提交
