# 见面聊后端

见面聊后端是基于 Python 3.12、Django、Django REST Framework、PostgreSQL、Redis 和 Celery 的模块化单体服务。当前仓库已建立工程基础，包括统一 API 响应、请求追踪、日志脱敏、健康检查、OpenAPI、pytest、Ruff、迁移流程和 Docker Compose 开发编排。

当前阶段包含手机号验证码登录/自动注册和令牌会话基础能力，不包含密码、微信/Apple 登录、订单、支付、退款、结算、推广奖励等完整业务模块。

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

### 6. 启动 API

```powershell
.\.venv\Scripts\python.exe manage.py runserver 0.0.0.0:8000
```

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

## 常见问题

### `redis-cli ping` 没有返回 `PONG`

先启动 Redis 服务，或确认 Memurai/WSL2 Redis 的地址和端口与 `REDIS_URL` 一致。

### `manage.py migrate` 无法连接数据库

检查 PostgreSQL 服务是否启动、`POSTGRES_HOST`、`POSTGRES_PORT`、数据库名、用户名和密码是否正确。当前项目不使用 MySQL。

### `celery.exe` 被应用程序控制策略阻止

使用 Python 模块方式：

```powershell
.\.venv\Scripts\python.exe -m celery -A backend.config worker --pool=solo --loglevel=INFO
```

如果 `python -m celery` 也被阻止，需要由电脑管理员允许该开发目录或 Python 环境。

### `/api/v1/health/ready/` 返回 `503`

分别检查 PostgreSQL 和 Redis。`/api/v1/health/live/` 只检查进程存活，不代表数据库和 Redis 已连接。

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
