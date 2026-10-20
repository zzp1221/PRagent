# step8 SPEC：恢复缺失的离线评测 corpus

## 现状证据

`docs/p0/INDEX.md` 记录 5 个测试因缺 `evaluation_data/` 而无法运行。核对后实际是**两份**
文件缺失，而且它们不是"真实 PR 数据集"，是代码明确要求 checked-in 的离线 fixture：

- `pragent/evaluation_experiments.py:28-30`：`load_controlled_pr_cases()` 读取
  `evaluation_data/pr_diff_100.jsonl`，注释写明 *"Load the checked-in 100-case corpus;
  no cases are generated at runtime"*。
- `pragent/evolution_proof.py:34-41`：`generate_prompt_evolution_cases()` 的名字有误导性，
  实现是 `load_prompt_evolution_cases()`，读取 `evaluation_data/prompt_evolution_130.jsonl`。
- `git log --all -- evaluation_data` 为空：这两个文件从未被提交过，因此在任何环境都不可能通过。
- `.gitignore` 未排除该目录，说明它们本该入库。

## 契约（从测试与消费代码倒推）

**pr_diff_100.jsonl**

| 约束 | 来源 |
|---|---|
| 恰好 100 例 | `AccuracyExperimentSuite.run_controlled` 的 `exactly_100_cases` |
| 恰好 10 个仓库 | `prepare_controlled_experiment_cases` |
| 40 例有 `expected_findings`，60 例为空 | `forty_risk_cases` / `sixty_clean_cases` |
| `split` 只能取 train/validation/holdout | `validate_case` |
| validation 与 holdout 仓库不相交，且 validation 8 个仓库、holdout 2 个 | `test_generated_dataset_has_repository_level_split_and_expected_counts` |
| 全部 `source.kind == "offline-fixture"` | `offline_fixture_provenance` |
| 每条 expected 含 path/start_line/end_line/cwe/severity 且覆盖一个新增行 | `validate_case` |

适配器按仓库名字母序切 60/20/20 例，因此仓库命名必须让前 6 个恰好覆盖 60 例。

**prompt_evolution_130.jsonl**

| 约束 | 来源 |
|---|---|
| 恰好 130 例 | `test_feedback_evolution_improves_repository_disjoint_holdout` |
| validation 8 个仓库、holdout 2 个且不相交 | 同上 |
| `feedback.missed_findings == 32` | 同上 |
| validation 与 holdout 的 candidate f1 都严格大于 baseline | 同上 |
| `evolution_run.decision == "activated"`、`quantitative_passed` 为真 | 同上 |
| `production_activation_allowed` 为假 | 同上 |

## 数据形状如何满足断言

默认提示词不含任何 `[focus-rule:...]` 标记，所以 `PromptPolicyReviewer` 只报
`LocalRuleReviewer` 的 6 条规则；`ContextRuleReviewer` 的 8 条规则只有在提示词显式
focus 后才会纳入。

- validation 104 例：32 例含一条 context 规则缺陷（基线漏报 → 恰好 32 条反馈）、
  32 例含一条 local 规则缺陷、40 例干净。
  - 基线 f1 = 0.6667、score ≈ 0.783；候选把它们全部报出后 f1 = 1.0、score = 1.0，
    远高于 0.02 的提升门槛。
- holdout 26 例：8 例 context、5 例 local、13 例干净。holdout 不参与反馈采集，
  但候选在那边同样把 context 缺陷报出来，因此 f1 严格提升而 precision 不退化。
- 每类缺陷行都经过挑选，只命中一条规则、不命中其他规则，避免产生额外误报拉低 precision。

## 非目标

- 不生成"真实 GitHub PR"数据：`validate_real_dataset` 要求 300 例真实来源，
  那不是 fixture 能替代的，相关生产声明门禁保持关闭。
- 不改任何评测代码逻辑。

## 判断

这是一次**恢复资产**而不是放宽标准：数据集本身被设计为离线固定装置，报告里也明确标注
`controlled-offline` 与 `does_not_prove`。合成数据在这里是设计要求，不是取巧。
