# P0-3 TASK：自动修复绑定被审查的提交（已完成）

- [x] T1 webhook 路径记录 `head_sha` / `base_sha` 到 task input
- [x] T2 `VerifiedPatchFixer.create_fix_commits` 接受 `expected_sha`，不匹配返回 `status="stale"`
- [x] T3 `get_file` 改用 `source_sha`，与 `download_archive` 同源
- [x] T4 `SuggestionOnlyFixer` 签名同步
- [x] T5 `service.create_fix` 读取 task 的 `head_sha` 并传递
- [x] T6 新建 `tests/test_fix_binding.py`：fake GitHub 客户端 + fake 模型
- [x] T7 用例：stale 拒绝（不读文件、不建 commit）、SHA 同源、完整链路只发 Draft、
      无测试命令不建 Draft、门禁未通过的 finding 不参与打补丁
- [x] T8 全量回归：94 用例，失败 6，与基线一致
- [x] T9 git 提交

## 范围修正

上一轮把 `fixer.py` 当作生产修复链路是错的。实际装配是
`patching.VerifiedPatchFixer`（`service.py:87-90`），它已经具备：
修复前后测试对比（`patching.py:186-189`）与"无测试命令则拒绝 Draft PR"
（`patching.py:179-185`）。因此本步只处理真实存在的两个缺陷（不绑定被审提交、
读文件用可变 ref）以及该路径零测试覆盖的问题。

新增测试同时为这条此前完全无覆盖的远端写入路径提供回归保护。
