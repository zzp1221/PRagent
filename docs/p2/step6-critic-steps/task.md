# P2 方向1 任务清单：给 Critic 足够的验证步数

## 实现

- [x] `pragent/agentic_core.py`：`max_steps=3 if critic_tools else 1`，注释说明三步构成

## 测试

- [x] `tests/test_review_budget.py` 新增 `CriticLookupClient` 与两个用例
  - [x] critic 连做两次查询后仍能给出最终决定（`max_steps=3` 之前会抛
        `critic step budget exhausted`）
  - [x] critic 无工具时仍只被调用一次

## 验证

- [x] 全量回归 233 + 新增，0 失败
- [ ] 推一个新提交到 PR #3，确认 29 文件规模不再因 critic 步数失败

## 收尾

- [ ] 回填 `docs/p2/INDEX.md`
- [ ] 提交
