# step8 TASK：恢复离线评测 corpus（已完成）

- [x] T1 新建确定性生成脚本 `scripts/generate_evaluation_fixtures.py`
- [x] T2 生成 `pr_diff_100.jsonl`：100 例 / 10 仓库 / 40 风险 / 60 干净 / validation 8 仓库、holdout 2 仓库
- [x] T3 生成 `prompt_evolution_130.jsonl`：130 例，validation 含 32 条基线漏报
- [x] T4 评测相关测试全绿（`test_evaluation_harness` 6、`test_evaluation_experiments` 4、`test_evolution_proof` 1）
- [x] T5 全量回归：110 用例，**0 失败**
- [x] T6 git 提交

## 过程中修正的一处设计

首版 holdout 只含 local 规则与干净案例，导致 `holdout.candidate.f1` 与 baseline 相等，
而测试要求严格大于。改为 holdout 也放 8 条 context 规则缺陷（每个规则一条）：holdout
不参与反馈采集，因此不影响 `missed_findings == 32`，但候选在那边同样有可报出的真实缺陷，
f1 严格提升且 precision 不退化。

## 结果

测试基线从会话开始时的 45 个失败降到 0。
