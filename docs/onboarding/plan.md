# 技术方案：一键接入（.bat 本地向导 + 轮询巡检）

## 总体结构

```
start.bat
   │  解析运行目录、选择 Python、设置绝对路径环境变量
   ▼
python -m pragent
   │
   ├── 启动时读取 runtime_settings 覆盖模型配置
   ├── 启动 WatchPoller 守护线程（间隔 180s，可配）
   └── 提供 /v1/onboarding/* 接口
          │
          ▼
   web/index.html  #onboard 视图（零构建静态页）
```

## 数据模型

### 表 runtime_settings

运行时可变配置，覆盖环境变量。键值对存法便于增量扩展。

```sql
CREATE TABLE IF NOT EXISTS runtime_settings (
    tenant_id TEXT NOT NULL,
    setting_key TEXT NOT NULL,
    setting_value TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (tenant_id, setting_key)
);
```

已定义键：

| 键 | 含义 | 敏感 |
|---|---|---|
| `llm.provider` | 提供方标识 | 否 |
| `llm.base_url` | API 基地址 | 否 |
| `llm.model` | 模型名 | 否 |
| `llm.api_key` | API 密钥 | 是 |
| `github.token` | GitHub token | 是 |
| `github.token_source` | `gh-cli` 或 `manual` | 否 |
| `github.webhook_secret` | webhook 验签密钥 | 是 |
| `watch.interval_seconds` | 轮询间隔 | 否 |

敏感值通过 `/v1/onboarding/status` 只返回"是否已设置 + 掩码"，永不回传原文。

### 表 repository_watches

```sql
CREATE TABLE IF NOT EXISTS repository_watches (
    tenant_id TEXT NOT NULL,
    repository TEXT NOT NULL,
    mode TEXT NOT NULL DEFAULT 'poll',
    enabled INTEGER NOT NULL DEFAULT 1,
    last_sha TEXT NOT NULL DEFAULT '',
    last_checked_at TEXT,
    last_task_id TEXT NOT NULL DEFAULT '',
    last_error TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    PRIMARY KEY (tenant_id, repository)
);
```

`mode` 取 `poll` | `webhook` | `both`。`last_sha` 记录最近一次已提交审查的 head commit，是轮询侧幂等键。

### 表 review_commits（跨通道去重账本）

```sql
CREATE TABLE IF NOT EXISTS review_commits (
    tenant_id TEXT NOT NULL,
    repository TEXT NOT NULL,
    head_sha TEXT NOT NULL,
    task_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (tenant_id, repository, head_sha)
);
```

独立建表而非在 `tasks.input_json` 上做 JSON 匹配，原因有三：两个后端 SQL 语义一致、主键冲突即是幂等、不依赖 JSON 序列化的空格与字段顺序。

`claim_review_commit(...)` 的语义与既有 `claim_webhook` 对齐：首次插入返回 true，已存在返回 false 并回查已有 `task_id`。

## 存储层实现

`store.py` 与 `postgres_store.py` 必须同时实现下列方法，签名一致：

- `get_runtime_setting(tenant_id, key) -> Optional[str]`
- `set_runtime_setting(tenant_id, key, value) -> None`
- `list_runtime_settings(tenant_id) -> Dict[str, str]`
- `delete_runtime_setting(tenant_id, key) -> None`
- `upsert_watch(tenant_id, repository, mode, enabled) -> None`
- `list_watches(tenant_id) -> List[dict]`
- `update_watch_check(tenant_id, repository, last_sha, last_task_id, error) -> None`
- `find_review_by_head_sha(tenant_id, repository, head_sha) -> Optional[dict]`

PostgreSQL 侧在既有 `_ensure_schema` 的语句列表中追加建表语句；SQLite 侧在 `_ensure_schema` 中追加 `conn.execute`。

## 配置热生效

现状：`Settings` 为 frozen dataclass，`ReviewService.__init__` 一次性解析 `resolved_llm()` 并构造 `JsonChatClient`、`AgenticReviewer`、`ReviewHarness`、`fixer`、`evolution`、`skill_evolution`，全部依赖同一个 client。

方案：

1. 新增 `ReviewService._load_runtime_overrides()`：启动时与每次配置变更后，从 `runtime_settings` 读出 LLM 三项，用 `dataclasses.replace()` 派生新的 `Settings` 实例，不改原对象。
2. 新增 `ReviewService.reload_llm()`：按新 Settings 重建 chat_client、registry 内的 `llm-review`、reviewer、harness、fixer、evolution 的 candidate_generator、skill_evolution 的 reviewer_factory，**整体替换引用**后返回状态摘要。
3. 替换顺序：先构建全部新对象，全部成功后再一次性赋值，避免中途失败留下半新半旧的组合。构建失败时保持旧对象不动并抛出错误。
4. 轮询线程持有一个"当前 service 快照"的读取函数，每轮开始取一次，避免读到替换中的中间态。

未配置模型时 `reload_llm()` 保留无 LLM 模式，向导据此提示"需先完成第一步"。

## 轮询线程

新增模块 `pragent/watchdog.py`：

```
class WatchPoller(threading.Thread, daemon=True):
    def __init__(self, service, interval_seconds, enabled)
    def run(self): while not stop_event: tick() then wait(interval)
    def tick(self): 遍历 watches → 逐仓库轮询 → 失败隔离 → 记录 last_error
    def stop(self)
```

单轮流程（每个仓库独立 try）：

1. 取 token：优先 `github.token` 运行时配置，回落 `settings.github_token`
2. `GET /repos/{repo}/pulls?state=open&per_page=30&sort=updated`
3. 对每个 PR 取 `head.sha`
4. 若 `head.sha` 等于该仓库 `last_sha` 则跳过
5. 若 `find_review_by_head_sha` 命中则只更新 `last_sha`，不重复提交
6. 否则取 `diff_url` 拉 diff，走 `enqueue_review` 入队（异步），记录 `last_task_id`
7. 单仓库异常：写 `last_error`，继续下一个仓库
8. 遇到 403 且带限流头：本轮回退，间隔按 2 倍放大一次，下一轮恢复

线程不持有数据库连接，每步通过 store 方法访问；`stop()` 用 `threading.Event`。

服务关闭时在 `run()` 的 `finally` 中调用 `poller.stop()`。

## 接口

全部挂在现有 `ApiHandler`，复用 `_principal` 与 `_send_json`。写操作要求 `manage` 权限。

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/v1/onboarding/status` | 汇总：模型、GitHub、webhook 可用性、已订阅仓库、轮询间隔 |
| POST | `/v1/onboarding/probe-gh` | 探测本机 gh，返回 found/account/scopes/token_masked/reason |
| POST | `/v1/onboarding/llm` | 保存模型三项并验证，成功后热生效 |
| POST | `/v1/onboarding/github` | 保存 token（来源 manual 或 gh-cli），并立即校验可读用户 |
| GET | `/v1/onboarding/repositories` | 用当前 token 列仓库 |
| POST | `/v1/onboarding/watches` | 全量替换订阅集合，同步写授权白名单 |
| POST | `/v1/onboarding/webhook-secret` | 生成并保存 webhook secret，返回明文一次 |
| GET | `/v1/onboarding/webhook/await` | 查询最近一次投递，用于验证 webhook 连通性 |

全部写操作用 POST：项目既有的 `ApiHandler` 只实现了 `do_GET` 与 `do_POST`，新增 `do_PUT` 会扩大请求面而没有收益。

敏感字段一律不出现在响应里。`POST /v1/onboarding/llm` 的验证方式是构造临时 `JsonChatClient` 调一次 `complete_json`，用极小 prompt 要求返回固定 JSON。

## 公网判定

新增 `pragent/network.py`：

```
def is_public_https(url) -> tuple[bool, str]  # 返回 (是否可用, 原因)
```

判定顺序：协议必须 https；主机不得为 localhost/回环/私有网段/链路本地/未指定地址；不得为 IP 直连的私有段。返回原因字符串供前端直接展示。

## 前端

在 `web/index.html` 增加 `#view-onboard` 与导航项；`web/app.js` 增加向导状态机：

1. 进入视图时拉 `status`，据结果渲染三步进度
2. 第一步表单提交 `PUT llm`，失败展示错误原文
3. 第二步进入时自动 `POST probe-gh`；成功展示账号并允许一键采用；失败展示 token 输入框
4. 第三步拉仓库列表，checkbox 勾选，保存调 `PUT watches`
5. 若 `webhook.available` 为真，展示可选加速区；否则灰显并展示原因

沿用现有零构建方式，不引入打包工具。样式追加到 `app.css`，复用既有 CSS 变量。

## 启动器

`start.bat` 职责严格限定为三件事，不含业务探测逻辑：

1. 以 `%~dp0` 为根，依次探测 `runtime\\python\\python.exe`、`python`、`py -3.11`
2. 设置 `PRAGENT_DB_PATH`、`PRAGENT_SKILLS_DIR`、`PRAGENT_PUBLIC_BASE_URL`（若未设）为绝对路径
3. 探测端口占用：占用则打印提示并直接打开浏览器；否则启动服务后打开浏览器

失败分支全部输出中文可读提示。单实例保护通过启动前探测端口实现，不引入 PID 文件。

## 测试策略

- `tests/test_onboarding.py`：接口契约、状态汇总、公网判定、中英敏感值掩码
- `tests/test_watch_poller.py`：注入假 GitHub 客户端，验证新 PR 发现、同 sha 跳过、跨通道去重、单仓库异常隔离、限流回退
- `tests/test_runtime_settings.py`：双存储层的键值读写与覆盖语义
- 端到端：本地起服务，用 fake LLM 与 fake GitHub，跑通"配置模型 → 保存 token → 订阅 → 轮询 → 生成任务"

## 交付顺序

存储层 → 配置热生效 → 手册接口 → 轮询线程 → 前端向导 → 启动器 → 测试 → 文档 → PR。
