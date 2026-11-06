# 开发环境启动

## 1. 技术前提

- Python 3.12。
- PostgreSQL 16 和 Redis 7；推荐使用 Docker Compose 启动。
- Git、PowerShell 或兼容 Shell。
- 不得使用生产数据库、生产密钥或真实个人/支付数据。

## 2. 本地启动

1. 复制 `.env.example` 为 `.env`，至少修改 `DJANGO_SECRET_KEY` 和 `POSTGRES_PASSWORD`。
2. 启动依赖服务：`docker compose up -d postgres redis`。
3. 创建虚拟环境：`python -m venv .venv`。
4. 安装依赖：`.venv\Scripts\python -m pip install -r requirements-dev.txt`。
5. 检查配置：`.venv\Scripts\python manage.py check`。
6. 应用迁移：`.venv\Scripts\python manage.py migrate --noinput`。
7. 启动 API：`.venv\Scripts\python manage.py runserver 0.0.0.0:8000`。
8. 启动异步 Worker：`.venv\Scripts\celery -A backend.config worker --loglevel=INFO`。

开发阶段上传图片默认保存到 `var/media/`，可通过 `MEDIA_ROOT` 修改；该目录只保存开发文件，不提交 Git。Docker Compose 使用 `media_data` 卷持久化 `/app/var/media`。生产接入 OSS/COS 前，必须为生产配置持久化目录或切换存储适配器。

PowerShell 下激活虚拟环境后，可以直接使用 `python manage.py`。

## 3. Docker Compose 启动

1. 复制 `.env.example` 为 `.env` 并填写开发变量。
2. 执行 `docker compose up --build`。
3. 打开 `http://localhost:8000/api/v1/health/live/` 验证 API。
4. 打开 `http://localhost:8000/api/v1/docs/` 查看 OpenAPI UI。
5. 执行 `docker compose ps` 检查 PostgreSQL、Redis、API 和 Worker 状态。
6. 停止服务：`docker compose down`；需要删除本地开发数据时才执行 `docker compose down -v`。

Compose 仅用于开发。它的默认密码和密钥不是生产凭据，禁止直接用于生产部署。

## 4. 配置策略

- 开发/测试配置在缺失非敏感变量时使用安全的本地默认值。
- 测试使用内存 SQLite 和内存缓存，避免单元/基础测试依赖外部服务。
- PostgreSQL、Redis、Celery 的开发连接地址可由环境变量覆盖。
- `MEDIA_ROOT` 控制本地媒体目录，`MEDIA_MAX_UPLOAD_BYTES`、图片尺寸和像素限制均通过环境变量配置。
- `MEDIA_URL_SIGNING_KEY` 控制 `display_url` 签名，开发环境使用本地值；生产必须使用独立密钥并支持 `MEDIA_URL_SIGNING_KEY_VERSION` 轮换。
- `PROFILE_DEFAULT_CITY_CODE`、昵称长度、签名长度和兴趣标签数量控制个人资料规则；首批兴趣标签和城市选项由数据库配置表维护。
- `backend.config.settings.prod` 在缺少生产必需变量或使用开发默认密钥时启动失败。
- 任何真实密钥只从环境变量或密钥服务注入，禁止写入 Git、镜像或日志。

## 5. 数据库迁移

- 修改模型后执行 `python manage.py makemigrations <app>` 生成迁移。
- 提交前执行 `python manage.py makemigrations --check --dry-run` 确认无遗漏。
- 执行 `python manage.py migrate --noinput` 应用迁移。
- 不手工修改数据库结构，不删除已发布迁移；破坏性变更必须有迁移窗口和回滚方案。

## 6. 质量检查

依次执行：

```text
python manage.py check
python manage.py makemigrations --check --dry-run
pytest
ruff check .
ruff format --check .
python manage.py spectacular --file openapi.yaml
```

涉及外部服务时，再运行带 `integration` 标记的测试。每个开发任务必须报告实际命令、结果和未验证项。

## 7. 基础接口

- `GET /api/v1/health/live/`：进程存活，不访问数据库。
- `GET /api/v1/health/ready/`：检查 PostgreSQL 和 Redis；依赖异常返回 `503`。
- `GET /api/v1/schema/`：OpenAPI 文档。
- `GET /api/v1/docs/`：Swagger UI。
- `GET /api/v1/redoc/`：ReDoc。
- `POST /api/v1/media/uploads/`：登录后上传服务者申请图片。
- `GET /api/v1/media/{media_id}/content/`：上传者或管理员读取私有媒体。
- `GET /api/v1/media/display/{media_id}/`：加载带签名的临时图片地址。
- `GET /api/v1/users/me/profile/`：查询当前用户个人资料。
- `PATCH /api/v1/users/me/profile/`：修改当前用户个人资料。
- `GET /api/v1/profile-options/interest-tags/`：获取兴趣标签配置。
- `GET /api/v1/profile-options/cities/`：获取城市代码配置。

## 8. Django Admin（开发查看）

- 访问地址：`/admin/`。
- 登录用户名使用完整手机号，不是 `phone_hash`。
- 创建或提升管理员账号：
  ```powershell
  .\.venv\Scripts\python.exe manage.py create_admin_user --phone 13800000000 --password '替换为至少12位密码'
  ```
- 当前后台模型默认只读，服务状态、价格、动态状态等修改继续通过 API 业务服务执行。
- 该后台适合本地开发和早期运营查看，不是生产管理员安全方案。
