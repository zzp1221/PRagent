# 任务清单：一键接入（.bat 本地向导 + 轮询巡检）

状态标记：`[ ]` 未开始，`[~]` 进行中，`[x]` 完成

## 阶段 0：准备

- [x] 创建分支 `feat/bat-onboarding-poll`
- [x] 记录基线：`python -m unittest discover -s tests` 通过（125 项）
- [x] 编写 `docs/onboarding/specify.md`
- [x] 编写 `docs/onboarding/plan.md`
- [x] 编写 `docs/onboarding/task.md`

## 阶段 1：存储层

- [x] `store.py` 建 `runtime_settings`、`repository_watches`、`review_commits` 三表
- [x] `store.py` 实现键值、订阅、去重账本、最近投递共 12 个方法
- [x] `postgres_store.py` 同步追加建表语句与方法实现
- [x] 单元测试覆盖双存储层的键值覆盖语义与订阅读写（`tests/test_runtime_settings.py`）

## 阶段 2：配置热生效

- [x] `pragent/network.py`：`inspect_public_base_url` 与私有网段判定
- [x] `ReviewService` 增加 `_effective_settings`，用 `dataclasses.replace` 派生配置
- [x] `ReviewService._install_llm_runtime`：整体重建后原子替换 LLM 相关对象
- [x] `ReviewService.reload_llm`：运行时重载模型配置
- [x] `runtime_github_client`：队列取 diff 时使用向导保存的令牌
- [x] 验证：改配置后 `/health` 反映新模型且进程未重启

## 阶段 3：接入接口

- [x] `GET /v1/onboarding/status`
- [x] `POST /v1/onboarding/probe-gh`
- [x] `POST /v1/onboarding/llm`（含真实调用验证）
- [x] `POST /v1/onboarding/github`
- [x] `GET /v1/onboarding/repositories`
- [x] `POST /v1/onboarding/watches`
- [x] `POST /v1/onboarding/webhook-secret`
- [x] `GET /v1/onboarding/webhook/await`
- [x] 敏感值掩码与权限校验
- [x] 修正：`/webhooks/github` 前移到会话鉴权之前，改用运行时 secret（原本会被 401 拦截）

## 阶段 4：轮询线程

- [x] `pragent/watchdog.py`：`WatchPoller` 守护线程
- [x] 单仓库异常隔离、限流回退
- [x] `(tenant, repository, head_sha)` 跨通道去重接入两条路径
- [x] `release_review_commit` 补偿：任务创建失败时释放声明
- [x] 服务关闭时优雅停止线程

## 阶段 5：前端向导

- [x] `index.html` 增加导航项与 `#view-onboard`
- [x] `app.js` 三步状态机与接口调用
- [x] `app.css` 向导样式
- [x] webhook 不可用时灰显并展示原因

## 阶段 6：启动器

- [x] `start.bat`：Python 探测、pushd 规范化目录、端口占用处理
- [x] 四种失败场景的中文提示（实测无 Python 与端口占用两条分支）
- [x] 确认 `start-linux.sh` 属于非目标：`specify.md` 的"不包含"已列出，README 只承诺 Windows 一键入口

## 阶段 7：验证

- [x] `tests/test_runtime_settings.py`（9 项）
- [x] `tests/test_onboarding.py`（24 项，含 HTTP 端到端）
- [x] `tests/test_watch_poller.py`（12 项）
- [x] `tests/test_polled_review.py`（7 项）
- [x] 全量 `python -m unittest discover -s tests`：176 项通过
- [x] 端到端冒烟：起真服务验证 `/health`、`/v1/onboarding/status`、`/api/dashboard`

## 阶段 8：文档与交付

- [x] 更新 `README.md` 增加一键接入章节
- [x] 更新 `.env.example` 增加轮询配置项
- [x] 确认未改动 `tunnel.ps1`、`tunnel-quick.ps1`
- [ ] 提交并推送分支
- [ ] 在 `zzp1221/PRagent` 提真实 PR，附验证证据

## 验收对照

| 验收项 | 对应阶段 | 证据 |
|---|---|---|
| AC-1 模型配置热生效 | 2、3 | `test_save_llm_applies_immediately_and_masks_the_key` + 冒烟 `/health` |
| AC-2 GitHub 探测与兜底 | 3 | `test_probe_endpoint_never_returns_the_token`、`test_logged_out_cli_explains_how_to_fix` |
| AC-3 轮询自动审查 | 4 | `test_new_pull_request_is_submitted_and_recorded` |
| AC-4 跨通道去重 | 4 | `test_webhook_task_is_skipped_when_the_poller_already_claimed_it` |
| AC-5 公网判定 | 2 | `test_loopback_https_url_is_rejected_for_a_different_reason` |
| AC-6 启动器 | 6 | 实测：无 Python 分支退出码 1、端口占用检测命中 |
| AC-7 无残留 | 全部 | 176 项测试 + 双存储签名一致性测试 |

## 已知边界

- `/v1/onboarding/*` 的写操作要求 `manage` 权限。`PRAGENT_AUTH_REQUIRED=false` 时本机默认管理身份可直接调用，这与项目既有权限模型一致。
- 模型密钥与 GitHub 令牌以明文存于数据库中，与 `.env` 同级风险；向导与状态接口一律掩码返回，审计日志只记录账号与来源。
- 取消订阅不撤销仓库授权，手动审查该仓库仍然可用。
