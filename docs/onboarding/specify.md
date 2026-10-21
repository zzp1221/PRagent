# 规格说明：一键接入（.bat 本地向导 + 轮询巡检）

## 背景

当前 PRAgent 的接入方式全部面向技术人员：模型配置只能写环境变量、审 PR 需要手工粘贴 diff 或自行配置 GitHub webhook、启动需要手敲 `python -m pragent`。这导致非技术用户在"下载之后"到"第一次看到审查结果"之间存在大量断点。

本规格定义一个面向普通用户的一键接入路径：双击 `start.bat`，浏览器自动打开向导，用户填模型三项、确认 GitHub 身份、勾选要自动审查的仓库，此后新开的 PR 会被自动审查并把结论回写到 PR 评论。

## 用户故事

### US-1 模型配置（非技术用户）

用户双击 `start.bat` 后，浏览器打开接入向导第一步。用户填写 model、base url、api key 三项，点击"测试连接"。系统发起一次真实的 JSON 约束调用验证凭据可用，成功则保存并在本次进程内立即生效，无需重启、无需编辑 `.env`。

失败时展示服务端返回的具体错误（HTTP 状态码与响应摘要），不清空用户已填内容。

### US-2 GitHub 身份（自动探测优先）

向导第二步自动探测本机 GitHub CLI 登录状态。探测成功则显示登录账号、token 前缀掩码与 scope 列表，并提供"使用此身份"按钮。

探测失败（未安装、未登录、scope 不足、PATH 中找不到、调用超时）**不是失败状态**，而是显示 token 输入框，提示用户去 GitHub 生成具备 `repo` scope 的 token 并粘贴。两条路径汇流到同一套 token 使用逻辑。

若探测到已登录但缺少 `repo` scope，额外提示补权限命令 `gh auth refresh -s repo`。

### US-3 仓库选择（轮询接入）

向导第三步列出该 token 可访问的仓库，用户勾选需要自动审查的仓库，每个仓库提供一个"自动审查 PR"开关。保存后系统把仓库写入授权白名单与订阅表，后台轮询线程开始工作。

轮询线程按固定间隔（默认 180 秒）扫描已订阅仓库的 open PR，发现新的 head commit 则拉取 diff 提交审查任务，审查完成后把结论回写到该 PR 评论。

### US-4 秒级加速（可选，条件可用）

当 `public_base_url` 为公网 HTTPS 地址时，向导额外展示 webhook 接入区：显示目标 webhook URL、生成并展示 secret、给出在 GitHub 仓库设置页填写所需的四项信息，并提供"等待首个事件"的连通性验证。

当 `public_base_url` 为回环或私有地址时，该区域显示为不可用并说明原因，不允许用户选择。轮询保持开启。

webhook 与轮询同时开启时，同一 `(repository, head_sha)` 只审查一次。

### US-5 零残留启动

双击 `start.bat` 时：
- 优先使用随包便携 Python，其次回落系统 Python（需 3.11 及以上），都没有则给出可操作提示
- 数据库、技能目录、配置文件落在脚本所在目录或 `%LOCALAPPDATA%\\PRAgent`，不依赖当前工作目录
- 端口被占用时提示"已在运行，是否直接打开控制台"，不抛 traceback
- 已有实例运行时不再启动第二个实例，避免重复审查

## 范围

### 包含

- Windows 启动脚本与运行目录约定
- 运行时配置持久化（模型三项、GitHub token、webhook secret、轮询参数）
- 配置热生效（无需重启进程）
- GitHub CLI 探测与 token 输入兜底
- 仓库订阅表与轮询线程
- 基于 `(repository, head_sha)` 的跨通道去重
- 接入向导前端视图与后端接口
- SQLite 与 PostgreSQL 双存储实现
- 单元测试与端到端验证

### 不包含

- 便携 Python 运行时的实际打包产物（只定义探测契约与目录约定）
- macOS / Linux 启动脚本
- GitHub App 注册自动化（manifest flow）
- 邮件或 IM 通知
- 多用户计费与配额

## 验收标准

### AC-1 模型配置

`PUT /v1/onboarding/llm` 提交有效配置后，`GET /v1/onboarding/status` 的 `llm.configured` 为 true；紧接着通过 `POST /v1/reviews` 提交的审查任务使用新配置的模型，`/health` 的 `llm_model` 反映新值，且进程未重启。

提交无效 api key 时返回 4xx 与可读错误信息，`llm.configured` 保持原值不变。

### AC-2 GitHub 探测与兜底

`POST /v1/onboarding/probe-gh` 在 gh 已登录环境返回 `found=true`、账号与 scope，**响应体中不出现完整 token**，`token_masked` 只含前缀。

gh 不可用时返回 `found=false` 与失败原因分类，HTTP 状态码仍为 200（探测失败不是接口错误）。

通过 `PUT /v1/onboarding/github` 粘贴 token 后，`GET /v1/onboarding/repositories` 返回该 token 可见的仓库列表。

### AC-3 轮询自动审查

订阅某仓库并开启自动审查后，轮询线程在下一个周期内发现新的 open PR，创建审查任务；任务完成后该 PR 出现评论，且评论带固定 marker 便于后续更新。

同一 head_sha 在后续周期中不再重复创建任务。轮询线程异常不导致主服务退出。

### AC-4 跨通道去重

对同一 `(repository, head_sha)` 先经轮询、再经 webhook 触发时，只产生一个审查任务。

### AC-5 公网判定

`public_base_url` 为 `http://127.0.0.1:8080`、`localhost`、`::1`、`10.x`、`172.16-31.x`、`192.168.x` 时，`GET /v1/onboarding/status` 的 `webhook.available` 为 false 并附带原因；为公网 HTTPS 地址时为 true。

### AC-6 启动器

`start.bat` 在"无 Python""端口占用""已有实例""正常启动"四种场景下均给出可读提示，且不出现 Python traceback。

### AC-7 无残留

- `python -m unittest discover -s tests` 全部通过
- 新增代码在 SQLite 与 PostgreSQL 两个存储实现中方法签名一致
- 未修改用户已有的 `tunnel.ps1`、`tunnel-quick.ps1`
- README 与 `.env.example` 反映新增配置项

## 风险与对策

**风险 1：配置落库后 api key 明文存储。**
对策：配置文件置于运行目录并对文件权限收紧；接口响应一律掩码；不写入审计日志。文档明确说明该文件等同凭据。

**风险 2：轮询线程与 webhook 产生重复审查。**
对策：以 `(tenant, repository, head_sha)` 为幂等键，两条通道提交前统一查询。

**风险 3：轮询频率过高触发 GitHub 限流。**
对策：默认 180 秒；只对已订阅仓库请求；单个仓库失败不阻断其他仓库；遇到 403 限流自动放大间隔。

**风险 4：热替换 LLM 客户端时并发任务读到半新半旧状态。**
对策：整体重建 client 与 reviewer 后原子替换引用，不就地修改字段。

**风险 5：探测 gh 阻塞主线程。**
对策：子进程调用设置超时，失败即降级到 token 输入。
