# P0-3 SPEC：自动修复绑定被审查的提交

## 前置纠正（推翻上一轮结论）

上一轮评审称"修复流程会读取最新分支内容，而报告可能来自更早的版本"并据此指出
`pragent/fixer.py:126`。核对生产装配后发现该结论只对**未被使用的旧实现**成立：

- `pragent/service.py:87-90`：真正装配的是
  `patching.VerifiedPatchFixer`（有模型时）或 `patching.SuggestionOnlyFixer`（无模型时）。
- `pragent/fixer.py` 的 `SafeFixer` 不在任何构造路径上，是死代码。
- `pragent/patching.py:186-189` **已经实现**了修复前后对比
  （`baseline = verify_archive(archive, {})`、`patched = verify_archive(archive, changed)`、
  `compare(baseline, patched)`）。
- `pragent/patching.py:179-185` 在未配置测试命令时**已经**拒绝创建 Draft PR，降级为
  suggestion-only。

因此"接上 compare()"和"无测试命令不得发 PR"这两项**已经存在**，本步不做。

## 仍然成立的缺陷

**缺陷一：修复不绑定被审查的提交**

- `pragent/patching.py:132-134`：直接取 `pull["head"]["sha"]`，即**调用时刻**的最新提交。
- 报告的 findings 行号与证据来自更早的审查（webhook 只在 `synchronize` 时触发）。
- 两者之间若有推送，`apply_file_patch` 会拿旧行号去套新内容：上下文不匹配时抛异常（可接受），
  但若恰好匹配就会静默改错位置。

**缺陷二：同一份基线取了两份不同时点的内容**

- `pragent/patching.py:145-147`：用 `source_ref`（分支名，可变）读文件内容。
- `pragent/patching.py:186`：用 `source_sha`（不可变）下载归档做测试基线。
- 即使无人推送，这也是逻辑不一致；有人推送时，patch 基于 ref 时点、测试基于 sha 时点。

**缺陷三：这条路径没有任何测试覆盖**

- 全仓测试中不存在 `create_fix` 或 GitHub 修复 API 的用例。
- `VerifiedPatchFixer` 是唯一能写入远端分支的组件，零覆盖是不可接受的风险敞口。

## 目标（可验收）

1. 审查任务记录被审查的 `head_sha` 与 `base_sha`（webhook 路径）。
2. 修复请求携带该 SHA；当 PR 的最新 head 与记录不一致时，拒绝生成修复并返回明确状态，
   要求重新审查。
3. 读文件与下载归档使用同一个不可变 SHA。
4. 补齐该路径的测试：SHA 绑定、stale 拒绝、无记录时的降级、patch 与验证流程。

## 非目标

- 不改 `fixer.py` 的 `SafeFixer`（死代码，单独清理）。
- 不新增行内评论或 check run。

## 设计决策

- `head_sha` 落在 task input（与 `diff_url` 同处），不塞进 report 结构，避免改动报告契约。
- SHA 校验放在 fixer 内部而不是 service：任何调用方都受保护。
- 校验失败返回 `status: "stale"` 而不抛异常：这是可预期的业务结果，不是故障。
- 无记录 SHA（手动 API 任务）时保持原有行为，但仍改用 `pull["head"]["sha"]` 读文件，
  保证读文件与归档同源。

## 约束

- `SuggestionOnlyFixer.create_fix_commits` 签名同步扩展，接受可选 `expected_sha`。
- `service.create_fix` 的对外返回结构不变，只在内部多传一个参数。
