# P0-1 PLAN：PR 级评论合并

## 改动面

| 文件 | 变更 |
|---|---|
| `pragent/github.py` | `upsert_comment` 增加翻页、PATCH 容错、返回 created/updated |
| `pragent/service.py` | 新增 `_review_comment_marker`；`_process_queued` 改用稳定 marker 并拼接 task 溯源行 |
| `tests/test_github.py` | 覆盖翻页命中、伪造 marker 容错、返回值 |
| `tests/test_service.py` | 覆盖同 PR 两次任务只产生一条评论的端到端行为 |

## 实施顺序

1. 写 `_review_comment_marker(repository, pull_request, task_id)` 纯函数，先让它可被单测直接验证。
2. 改造 `upsert_comment`：分页遍历、容错 PATCH、返回动作名。
3. 接入 `_process_queued`：marker 换成 PR 级，正文前置 task 溯源注释。
4. 补测试：github 层（fake 分页/profile）、service 层（两次 webhook 同 PR）。
5. 跑目标测试 + 全量基线回归，确认无新增失败。
6. git 提交。

## 验证方法

- `python -m unittest test_github test_service -v`（cwd=tests，PYTHONPATH 含项目根）
- 全量：`python -m unittest` 自定义加载器，对比基线 45 个既有失败不增加。
- 断言要点：同 PR 第二次审查 `created` 计数仍为 1，`updated` 计数为 1。

## 回滚

单点改动，`git revert` 该提交即恢复 task 级 marker。
