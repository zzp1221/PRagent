# P0-1 TASK：PR 级评论合并（已完成）

- [x] T1 新增 `ReviewService._review_comment_marker` 并保证无 PR 号时回退 task 级 marker
- [x] T2 `GitHubClient.upsert_comment` 支持分页、PATCH 容错、返回 created/updated
- [x] T3 `_process_queued` 接入稳定 marker + task 溯源注释 + `github_comments_*` 指标
- [x] T4 新增 `tests/test_github.py` 用例：翻页命中已有评论
- [x] T5 新增 `tests/test_github.py` 用例：他人 marker 不可 PATCH 时继续并新建
- [x] T6 新增 `tests/test_service.py` 用例：同 PR 两个任务只保留一条评论
- [x] T7 跑 test_github / test_service：8/8 通过
- [x] T8 全量：74 用例，失败 6，无新增（基线 45 → 6，见下）
- [x] T9 git 提交

## 附带修复（阻塞验证的根因）

`pragent/store.py` 的 `TaskStore._connect` 每次返回新连接，而 `with conn:` 只提交或回滚、
不关闭句柄。长时间运行会持续泄漏文件描述符；在 Windows 上导致临时库文件无法删除，
压掉了 39 个测试的 tearDown。改为 contextmanager 并显式 `close()`。

## 结果

- 全量测试失败数：45 → 6（39 个 Windows 文件锁消失）。
- 剩余 6 个均为既有环境问题，与本步无关：5 个缺 `evaluation_data/` 数据集，1 个
  Python 3.14 `ast.unparse` 单引号风格断言。
