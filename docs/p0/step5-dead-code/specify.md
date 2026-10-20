# step5 SPEC：删除不在装配路径上的 SafeFixer

## 现状证据

- `pragent/service.py:87-90`：修复器装配为
  `VerifiedPatchFixer(...) if self.chat_client else SuggestionOnlyFixer()`，两者都在
  `pragent/patching.py`。
- `pragent/service.py:11`：仍有 `from .fixer import SafeFixer`，导入后从未使用。
- `pragent/fixer.py` 整份文件只定义 `SafeFixer`，无任何生产调用点。
- `tests/test_advanced.py:32-44` 是该类唯一的消费者，同时也是当前 6 个既有失败之一
  （断言 `os.environ["PASSWORD"]` 双引号，而 Python 3.12+ 的 `ast.unparse` 产出单引号）。

## 目标

1. 删除 `pragent/fixer.py` 与 `service.py` 中的无用导入。
2. 删除仅覆盖该类的测试，避免留下无被测对象的用例。
3. 全量测试失败数由 6 降为 5。

## 非目标

- 不改动 `patching.py` 的任何行为（生产修复链路不在此步范围内）。
- 不为 `SafeFixer` 的行为寻找新归宿：它按行代换的思路已被 `VerifiedPatchFixer` 的
  unified patch 方案取代。

## 风险与判断

删除前确认三件事都成立才能删：无生产引用（已确认）、无其他测试引用（已确认）、
其能力有替代者（`VerifiedPatchFixer` 做结构校验加前后测试对比，严格强于按行代换）。

若只是修那条引号断言而不删代码，会留下"测试维护一个死组件"的长期成本，不如一次性清掉。
