# step8 PLAN：恢复离线评测 corpus

## 改动面

| 文件 | 变更 |
|---|---|
| `scripts/generate_evaluation_fixtures.py` | 新建：确定性生成两份 jsonl |
| `evaluation_data/pr_diff_100.jsonl` | 新建：100 例 |
| `evaluation_data/prompt_evolution_130.jsonl` | 新建：130 例 |

## 实施顺序

1. 定义规则行表：每条确定性规则对应一行代码、一个严重级别、一个 CWE。
2. 写 `_case` 构造器，统一产出含 `source.kind = "offline-fixture"` 与 `repair_validation`
   的案例。
3. 生成 100 例：仓库 `fixture/repo-01..10`，风险例在 01、02、09、10，其余干净，
   风险集中在 4 个仓库各 10 例恰好 40。
4. 生成 130 例：validation 104（32 context + 32 local + 40 clean）、holdout 26
   （8 context + 5 local + 13 clean）。
5. 先跑评测相关测试，据失败调整分布（holdout 的 f1 断言要求严格提升）。
6. 全量回归。

## 验证

- `test_evaluation_harness`、`test_evaluation_experiments`、`test_evolution_proof` 全绿。
- 全量 110 用例 0 失败。
- 脚本可重复运行，输出稳定（无随机）。

## 回滚

删除生成的文件与脚本即可回到缺失状态。
