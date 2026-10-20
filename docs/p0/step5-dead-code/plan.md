# step5 PLAN：删除 SafeFixer

1. `git rm pragent/fixer.py`。
2. `service.py` 删除 `from .fixer import SafeFixer`。
3. `tests/test_advanced.py` 删除 `test_safe_fixer_changes_only_supported_rules` 与对应导入。
4. 确认 `pragent` 与 `tests` 中不再有 `fixer` 模块引用。
5. 全量回归，期望 5 个失败（缺两个数据集共 4 个用例 + 无引号用例已删除）。

## 验证

- `grep fixer` 只应剩 `git` 历史与文档。
- 全量测试的失败清单里不再出现 `test_advanced`。
