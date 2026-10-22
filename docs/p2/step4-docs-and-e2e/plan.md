# P2 方向1 计划：文案诚实化 + 真实 PR 端到端验证

## 改动面

| 文件 | 改动 |
|---|---|
| `README.md` | 第 3 行、第 15 行改为与实际能力一致；新增一条说明默认路径的文件上下文来源与边界 |
| `docs/p2/step4-docs-and-e2e/task.md` | 验证结果回填 |
| 容器镜像 | `docker compose up -d --build pragent` 重建，让 step1-step3 生效 |

不改动：任何 `.py` 生产逻辑。

## 实施顺序

1. 改 README 三处表述。
2. `docker compose up -d --build pragent`，等 healthy。
3. 起 quick tunnel，用 `-SyncWebhook zzp1221/PRagent` 同步 GitHub 上的 hook URL。
4. 从 `main` 开分支，提交 README 改动，push，开 PR。
5. 等审查跑完，读 PR 评论与任务报告，核对 `repository_context` 与工具轨迹。
6. 如果链路有问题：记录现象，判断是环境问题还是代码问题；代码问题另开一步修。

## 验证方法

**文案**

- 逐句对照 `README.md:3`、`:15` 与 `pragent/service.py:_repository_source_provider`、
  `pragent/agentic_core.py` 的实际行为，确认没有夸大，也没有漏掉「看不到调用方」这条边界。

**端到端硬信号**

- PR 上出现本服务的审查评论（marker `<!-- pragent-review:zzp1221/PRagent#<n> -->`）。
- 该任务的报告里：
  - `execution.repository_context.source_kind == "pinned-files"`
  - `execution.repository_context.file_count > 0`
  - `execution.repository_context.root_supplied == false`
- 执行轨迹里至少有一次 `ok: true` 的 `read_file` 或 `symbol`。

**回归**

```
python -c "import sys,pathlib,unittest; sys.path.insert(0,'.'); sys.path.insert(0,'tests'); \
  names=sorted(p.stem for p in pathlib.Path('tests').glob('test_*.py')); \
  unittest.TextTestRunner(verbosity=1).run(unittest.TestLoader().loadTestsFromNames(names))"
```

必须保持 227 用例 0 失败。

## 回滚

README 改动可单独 revert。镜像回到上一版只需 `docker compose up -d` 而不带 `--build`
（若旧镜像仍在本机）。隧道是临时进程，结束时停掉即可。
