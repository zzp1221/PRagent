# P0-1 SPEC：PR 级评论合并（消除同一 PR 的评论堆叠）

## 现状证据

- `pragent/service.py:377-380`：`client.upsert_comment(issue_url, markdown, "<!-- pragent-review:%s -->" % task_id)`
- `pragent/service.py:249`：每个任务生成新的 `uuid4()` task_id
- `pragent/github.py:51-60`：`upsert_comment` 以 marker 子串匹配已有评论，命中则 PATCH，未命中则 POST

后果：同一 PR 每收到一次 `synchronize` 事件就生成新 task_id，marker 随之变化，`upsert_comment` 找不到旧评论，于是新增一条。PR 迭代 5 次即堆积 5 条评论。

## 目标（可验收）

1. 同一 `repository + pull_request` 的任意次审查结果，最终在 GitHub 上只保留 **1 条** 本服务产生的评论。
2. 无 PR 号的手动任务保持现有行为（task 级 marker），不引入回归。
3. 匹配到非本服务所有的评论（他人伪造 marker）时不得中断发布流程，应继续查找或最终新建。
4. 评论正文保留可追溯的 task_id。
5. 评论列表超过单页时仍能命中已有评论。

## 非目标

- 不做行内评论（inline review comment）、不做 check run 状态。
- 不做"问题已修复/仍存在"跟踪。
- 并发双任务同时 upsert 的互斥由 P0-2 的执行锁兜底，本步不处理。

## 设计决策

- marker 匹配键改为 `<!-- pragent-review:{repository}#{number} -->`，稳定且与任务无关。
- 另起一行 `<!-- pragent-review-task:{task_id} -->` 承载溯源信息，不参与匹配。
- `upsert_comment` 返回 `"created"` 或 `"updated"`，便于测试与后续指标统计。
- 匹配时对每页评论做容错 PATCH：失败（403/他人评论）继续下一条，全部失败才新建。
- 翻页上限 5 页（500 条），避免无界请求。

## 约束

- 不改变 `handle_github_pull_request` 的对外返回结构。
- 不改变 webhook 去重语义（P0-2 才动）。
- 新增测试必须能在无网络条件下运行（fake client）。
