# P0-3 PLAN：自动修复绑定被审查的提交

## 改动面

| 文件 | 变更 |
|---|---|
| `pragent/service.py` | webhook 记录 head/base SHA；`create_fix` 读取并传递 |
| `pragent/patching.py` | `create_fix_commits(..., expected_sha="")`；stale 拒绝；读文件改用 SHA |
| `tests/test_fix_binding.py` | 新建：修复路径的完整测试 |

## 实施顺序

1. `handle_github_pull_request` 从 payload 取 `pull.head.sha` / `pull.base.sha` 写入 task input。
2. `patching.VerifiedPatchFixer.create_fix_commits` 增加 `expected_sha`：
   - 非空且与当前 head 不同 → 返回 `status="stale"`
   - `get_file` 改用 `source_sha`
3. `SuggestionOnlyFixer` 同步签名。
4. `service.create_fix` 从 task input 取 `head_sha` 传入。
5. 建立 fake GitHub 客户端与 fake 模型，覆盖真实修复链路。
6. 全量回归。

## 验证方法

- 新建 `tests/test_fix_binding.py`：
  - stale：记录 SHA 与当前 head 不同 → `status="stale"`，无 commit、无 Draft PR
  - 绑定：`get_file` 收到的 ref 等于 SHA
  - 无记录：expected 为空时仍可产出 draft（用最小可验证 patch）
  - 完整链路：patch → 结构校验 → baseline/patched 测试 → atomic commit → draft PR
- 全量：失败数不超过 6。

## 回滚

单文件逻辑改动加新测试，revert 即恢复。
