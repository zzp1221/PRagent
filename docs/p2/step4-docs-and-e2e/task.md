# P2 方向1 任务清单：文案诚实化 + 真实 PR 端到端验证

## 文案

- [ ] `README.md:3` 改为「用本次变更涉及的文件与 diff 取证」
- [ ] `README.md:15` 改为「读文件全文、查符号定义与调用点、定位相关测试」
- [ ] 新增一条文件上下文说明，写明来源（按被审提交 SHA 读取）与边界（不含改动文件之外的调用方）
- [ ] `README.md` 架构图里的「Worker 使用仓库工具取证」改为「文件内容与 diff」
- [ ] 全仓检查无残留的「仓库工具取证 / 仓库级」表述

## 端到端验证

- [ ] `docker compose up -d --build pragent` 重建镜像（让 step1-step3 生效）
- [ ] 容器 healthy
- [ ] 起 quick tunnel，`-SyncWebhook zzp1221/PRagent` 同步 GitHub hook
- [ ] 从 `main` 开分支，提交本次改动，push
- [ ] 开 PR
- [ ] 服务自动收到 webhook 并完成审查
- [ ] PR 上出现审查评论（marker `<!-- pragent-review:zzp1221/PRagent#<n> -->`）
- [ ] 报告 `execution.repository_context.source_kind == "pinned-files"`
- [ ] 报告 `file_count > 0` 且 `root_supplied == false`
- [ ] 轨迹里至少一次 `ok: true` 的 `read_file` 或 `symbol`

## 回归

- [ ] 227 用例 0 失败

## 收尾

- [ ] 回填 `docs/p2/INDEX.md` 的端到端结果
- [ ] 提交

## 结果记录

（执行后回填）
