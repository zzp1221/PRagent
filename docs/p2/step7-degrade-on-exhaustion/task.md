# P2 方向1 任务清单：步数耗尽降级

## 实现

- [x] `BoundedRole.__init__` 加 `degrade_on_exhaustion: bool = False`
- [x] `run` 的最后一步 `build_managed_context` 传空工具清单
- [x] 循环结束：打开标记时返回降级 final（带 `_degraded`、`_observations`、`_steps`），
      否则保持抛 `RuntimeBudgetExceeded`
- [x] critic 与 worker 的构造点打开标记；Lead 保持关闭

## 测试

- [x] `CriticForeverClient`：永不返回 final，审查仍成功，3 次调用，最后一次无工具
- [x] `CriticLookupClient`：两次查询后作答，前两步有工具、第三步没有

## 验证

- [x] 全量回归：**235 用例，0 失败 0 错误**（本步新增 1）
- [ ] 推送后确认 29 文件审查不再因 critic 步数失败

## 收尾

- [ ] 回填 `docs/p2/INDEX.md`
- [ ] 提交
