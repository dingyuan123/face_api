# 见面聊后端

见面聊后端是基于 Python 3.12、Django、Django REST Framework、PostgreSQL、Redis 和 Celery 的模块化单体服务。当前仓库已建立工程基础，包括统一 API 响应、请求追踪、日志脱敏、健康检查、OpenAPI、pytest、Ruff、迁移流程和 Docker Compose 开发编排。

当前仓库包含手机号、Apple、微信登录，以及服务者、排期、订单、支付、退款、评价、资讯、地址搜索和订单实时聊天等业务能力。各模块的完成范围和待接入事项以 `docs/development-roadmap.md`、`docs/open-questions.md` 为准。

## 技术环境

- Python 3.12
- Django 5.x + Django REST Framework
- PostgreSQL 16
- Redis 7.x（本地也可以使用兼容版本，但需要实际验证）
- Celery 5.x
- pytest、Ruff

本地没有 Docker 时，使用已安装的 PostgreSQL 和 Redis 即可。MySQL 不参与当前项目配置。

## Windows 本地启动

以下命令默认使用 PowerShell，并且假设工作目录是 `D:\即享\face_api`。

### 1. 启动 PostgreSQL 和 Redis

确认 PostgreSQL 服务和 Redis 服务已经启动。

Redis 可以先验证：

```powershell
redis-cli ping
```

正常返回：

```text
PONG
```

Windows 上如果使用 Memurai 或 WSL2 中的 Redis，只要地址和端口与 `.env` 配置一致即可。

### 2. 创建开发数据库

使用 `psql` 或 PostgreSQL 管理工具执行：

```sql
CREATE ROLE jianmianliao LOGIN PASSWORD 'development-password';
CREATE DATABASE jianmianliao OWNER jianmianliao;
```

请将密码替换为自己的本地开发密码。不要使用生产密码，不要把真实密码提交到 Git。

### 3. 创建环境配置

```powershell
Copy-Item .env.example .env
notepad .env
```

至少检查或修改以下变量：

```text
DJANGO_ENV=development
DJANGO_SECRET_KEY=替换成一个较长的本地随机值
DJANGO_DEBUG=true
DJANGO_ALLOWED_HOSTS=localhost,127.0.0.1

POSTGRES_DB=jianmianliao
POSTGRES_USER=jianmianliao
POSTGRES_PASSWORD=development-password
POSTGRES_HOST=localhost
POSTGRES_PORT=5432

REDIS_URL=redis://localhost:6379/0
CELERY_BROKER_URL=redis://localhost:6379/1
CELERY_RESULT_BACKEND=redis://localhost:6379/2
```

如果 PostgreSQL 或 Redis 使用了其他端口，请同步修改 `.env`。

如果需要从同一局域网的其他电脑访问开发服务，请把开发电脑的局域网 IP 加入
`DJANGO_ALLOWED_HOSTS`，例如：`DJANGO_ALLOWED_HOSTS=localhost,127.0.0.1,192.168.10.9`。
然后重启 API 服务。Django 校验的是主机名/IP，不包含端口。

开发环境默认允许跨域访问，以便局域网内的前端项目直接请求 API。若要限制来源，请在
`.env` 设置 `CORS_ALLOW_ALL_ORIGINS=false`，并配置：
`CORS_ALLOWED_ORIGINS=http://192.168.10.3:5173`（改成前端实际地址）。生产环境必须
使用明确来源，不能开启 `CORS_ALLOW_ALL_ORIGINS`。

使用 Cloudflare Tunnel 临时地址时，开发环境可将 `.trycloudflare.com` 加入
`DJANGO_ALLOWED_HOSTS`；如果 Tunnel 重启后地址变化，临时通配符可以免去再次修改，
生产环境必须改为明确域名，不能使用通配符。

### 4. 创建虚拟环境并安装依赖

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
```

已经创建过 `.venv` 时，可以跳过第一句，只执行依赖安装。

### 5. 初始化数据库

```powershell
.\.venv\Scripts\python.exe manage.py migrate --noinput
```

每次拉取、同步或更新后端代码后，都要重新执行数据库迁移。代码中的模型已经更新，但数据库不会自动应用新的迁移文件。

### 6. 启动 HTTP + WebSocket API

```powershell
.\.venv\Scripts\python.exe -m daphne -b 0.0.0.0 -p 8000 backend.config.asgi:application
```

以后本地开发和联调统一使用上面的 Daphne 命令启动 API，它同时处理 HTTP 和 WebSocket。
`manage.py runserver` 只适合临时调试纯 HTTP 接口；如果使用它，订单聊天 WebSocket 无法正常联调。
使用 Docker Compose 启动时不需要手动执行 Daphne，Compose 已配置自动使用 ASGI 启动。

服务启动后访问：

- 健康检查：<http://localhost:8000/api/v1/health/live/>
- 就绪检查：<http://localhost:8000/api/v1/health/ready/>
- Swagger 文档：<http://localhost:8000/api/v1/docs/>
- ReDoc 文档：<http://localhost:8000/api/v1/redoc/>
- OpenAPI Schema：<http://localhost:8000/api/v1/schema/>

`health/ready/` 返回 `200` 时，说明 PostgreSQL 和 Redis 都可以正常访问；如果返回 `503`，先检查数据库和 Redis 服务及 `.env` 配置。

### 7. 启动 Celery Worker

再打开一个新的 PowerShell 窗口：

```powershell
cd D:\即享\face_api
.\.venv\Scripts\python.exe -m celery -A backend.config worker --pool=solo --loglevel=INFO
```

如果直接执行 `celery.exe` 时出现“应用程序控制策略已阻止此文件”，请使用上面的 Python 模块方式启动，不要关闭或绕过系统安全策略。

Windows 开发环境建议使用 `--pool=solo`。Worker 启动后会保持运行，不能关闭该终端。

### 8. 订单实时聊天联调

1. 先调用 `POST /api/v1/messaging/ws-ticket/` 获取一次性票据。
2. WebSocket 连接地址为 `ws://localhost:8000/ws/messages/?ticket=<ticket>`；Cloudflare Tunnel 使用 `wss://`。
3. 连接后发送 `{"action":"subscribe","conversation_id":"<会话 UUID>"}` 订阅订单会话。
4. 发送文本消息使用 `{"action":"message.send","conversation_id":"...","message_type":"TEXT","content":"你好","client_message_id":"..."}`。
5. 断线后用 `GET /api/v1/conversations/<会话 UUID>/messages/?after_sequence=<上次序号>` 补偿消息。

票据只能使用一次且默认 60 秒过期；不能把长期 Access Token 放在 WebSocket URL 中。

## Docker Compose 启动

如果本机安装了 Docker Desktop，也可以使用 Compose：

```powershell
Copy-Item .env.example .env
docker compose up --build
```

Compose 会启动 PostgreSQL、Redis、API 和 Celery Worker，并自动执行数据库迁移。查看服务状态：

```powershell
docker compose ps
```

停止服务：

```powershell
docker compose down
```

`docker compose down -v` 会删除本地开发数据，只在明确需要清理数据时执行。

## 测试和质量检查

```powershell
.\.venv\Scripts\python.exe manage.py check
.\.venv\Scripts\python.exe manage.py makemigrations --check --dry-run
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m ruff format --check .
.\.venv\Scripts\python.exe manage.py spectacular --file openapi.yaml
```

自动化测试使用 SQLite 内存数据库和内存缓存，因此只运行测试时不需要 PostgreSQL 或 Redis。涉及真实数据库事务、约束和并发行为时，仍需在 PostgreSQL 环境中运行集成测试。

## 手机号登录接口

当前开发/测试环境未接入阿里云或其他短信服务，发送验证码接口会返回仅供联调的 `debug_code`。生产配置禁止返回该字段。

```powershell
# 发送验证码
$sms = Invoke-RestMethod -Method Post -Uri http://localhost:8000/api/v1/auth/sms-code/ `
  -ContentType 'application/json' -Body '{"phone":"13800138000"}'
$sms.data.debug_code

# 登录/自动注册
$login = Invoke-RestMethod -Method Post -Uri http://localhost:8000/api/v1/auth/login/ `
  -ContentType 'application/json' `
  -Body ('{"phone":"13800138000","code":"' + $sms.data.debug_code + '"}')

# 访问当前会话
Invoke-RestMethod -Uri http://localhost:8000/api/v1/users/me/ `
  -Headers @{Authorization = "Bearer $($login.data.access_token)"}
```

接口约定：

- `POST /api/v1/auth/sms-code/`：发送 6 位验证码；支持 `Idempotency-Key`。
- `POST /api/v1/auth/login/`：验证码登录并自动注册；支持 `Idempotency-Key`。
- `POST /api/v1/auth/refresh/`：轮换访问令牌和刷新令牌。
- `GET /api/v1/users/me/`：使用 `Authorization: Bearer <access_token>` 查询当前会话。

## 数据库迁移

修改模型后：

```powershell
.\.venv\Scripts\python.exe manage.py makemigrations <app>
.\.venv\Scripts\python.exe manage.py migrate --noinput
```

所有数据库结构修改都必须经过迁移文件。不要手工改表，不要删除已经发布的迁移。

启动服务前可以检查是否存在未应用迁移：

```powershell
.\.venv\Scripts\python.exe manage.py showmigrations
```

如果计划任务或启动日志提示 `You have unapplied migration(s)`，执行：

```powershell
.\.venv\Scripts\python.exe manage.py migrate --noinput
```

## 用户协议和隐私政策

用户服务协议和隐私政策已作为无需登录的公开页面托管：

- 用户服务协议：<http://localhost:8000/terms/>
- 隐私政策：<http://localhost:8000/privacy/>
- 规范地址：<http://localhost:8000/legal/terms/>
- 规范地址：<http://localhost:8000/legal/privacy/>

部署到 Cloudflare Tunnel 或正式域名后，将 `localhost:8000` 替换为实际域名即可，例如：

```text
https://你的域名/terms/
https://你的域名/privacy/
```

这些地址不需要登录，允许浏览器和 App WebView 直接访问。当前文档中的正式发布日期、生效日期、公司联系方式仍包含待填写内容，对外发布前需要由业务或法务负责人确认。

## 常见问题

### `redis-cli ping` 没有返回 `PONG`

先启动 Redis 服务，或确认 Memurai/WSL2 Redis 的地址和端口与 `REDIS_URL` 一致。

### `manage.py migrate` 无法连接数据库

检查 PostgreSQL 服务是否启动、`POSTGRES_HOST`、`POSTGRES_PORT`、数据库名、用户名和密码是否正确。当前项目不使用 MySQL。

### 微信或 Apple 登录返回 `500`，提示 `phone_hash` 不能为空

这通常不是第三方登录失败，而是后端代码已经允许第三方账号暂时没有手机号，但数据库还没有应用对应迁移。日志可能包含：

```text
IntegrityError: null value in column "phone_hash" of relation "auth_login_requests" violates not-null constraint
```

解决方法：

```powershell
.\.venv\Scripts\python.exe manage.py migrate --noinput
.\.venv\Scripts\python.exe manage.py showmigrations accounts
```

确认 `accounts` 下没有未应用迁移后，重新发起登录。同一个微信授权 `code` 只能使用一次，重试时必须使用微信 SDK 返回的新 `code`。

### `celery.exe` 被应用程序控制策略阻止

使用 Python 模块方式：

```powershell
.\.venv\Scripts\python.exe -m celery -A backend.config worker --pool=solo --loglevel=INFO
```

如果 `python -m celery` 也被阻止，需要由电脑管理员允许该开发目录或 Python 环境。

### `/api/v1/health/ready/` 返回 `503`

分别检查 PostgreSQL 和 Redis。`/api/v1/health/live/` 只检查进程存活，不代表数据库和 Redis 已连接。

### 宝塔 Nginx 反向代理后 `/ws/messages/` 返回 `404`

这是 WebSocket 反向代理常见的坑：票据接口可以正常返回，但 WebSocket 握手请求到 Django 后变成普通
`GET` 请求，最终被 WebSocket 路由拒绝，日志可能显示：

```text
GET /ws/messages/?ticket=...
status_code: 404
```

这通常不是聊天接口路径写错，也不是票据本身的问题，而是 Nginx 没有把 WebSocket 的
`Upgrade` / `Connection` 请求头转发给 Daphne。浏览器和 App 发起 WebSocket 连接时必须完成
HTTP 协议升级，否则后端收到的只是普通 HTTP 请求。

在 `/www/server/nginx/conf/nginx.conf` 的 `http {}` 块中添加连接升级映射：

```nginx
map $http_upgrade $connection_upgrade {
    default upgrade;
    ''      close;
}
```

然后在宝塔网站的反向代理配置中，给 `location /` 增加 WebSocket 转发配置；原有的
`Host`、`X-Real-IP` 和 `X-Forwarded-*` 配置保留：

```nginx
location / {
    proxy_pass http://127.0.0.1:8000;
    proxy_http_version 1.1;

    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection $connection_upgrade;
    proxy_read_timeout 300s;
    proxy_send_timeout 300s;

    proxy_set_header Host $http_host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
}
```

修改后检查并重载 Nginx：

```bash
nginx -t
nginx -s reload
```

验证时必须使用新获取的一次性票据，并带上 WebSocket 握手请求头：

```bash
curl -i -N \
  -H "Connection: Upgrade" \
  -H "Upgrade: websocket" \
  -H "Sec-WebSocket-Version: 13" \
  -H "Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==" \
  "https://你的域名/ws/messages/?ticket=<新票据>"
```

目标响应是 `101 Switching Protocols`。票据默认 60 秒过期且只能使用一次，重复使用旧票据
不能用来判断代理配置是否正确。没有带 `Upgrade: websocket` 请求头时返回 `404` 是正常现象，
因为该地址只接受 WebSocket 握手。若直接访问 `http://127.0.0.1:8000/ws/messages/` 能握手成功，
而通过域名仍返回 `404`，问题就在 Nginx、Cloudflare Tunnel 或其他中间代理的 WebSocket 转发。

## 项目文档

- 架构说明：`docs/architecture.md`
- API 规范：`docs/api-conventions.md`
- 数据库设计：`docs/database-design.md`
- 安全规范：`docs/security.md`
- 测试规范：`docs/testing.md`
- 开发路线图：`docs/development-roadmap.md`
- 目录结构：`docs/codebase-structure.md`
- 开发环境详细说明：`docs/development-setup.md`

## 安全提示

- `.env`、真实密钥、生产数据库地址和真实用户/支付数据不得提交到 Git。
- 不要使用生产数据库进行开发、测试或迁移验证。
- 生产配置缺少必要环境变量时会拒绝启动，这是预期行为。
