# 后端目录结构规划

## 1. 目录树

```text
face_api/
├── AGENTS.md
├── README.md
├── pyproject.toml
├── ruff.toml
├── pytest.ini
├── manage.py
├── docker-compose.yml
├── .env.example
├── docs/
│   ├── architecture.md
│   ├── requirements-analysis.md
│   ├── business-rules.md
│   ├── api-conventions.md
│   ├── database-design.md
│   ├── security.md
│   ├── testing.md
│   ├── codebase-structure.md
│   ├── development-roadmap.md
│   ├── open-questions.md
│   └── decisions/
├── backend/
│   ├── config/
│   │   ├── settings/
│   │   │   ├── base.py
│   │   │   ├── dev.py
│   │   │   ├── test.py
│   │   │   └── prod.py
│   │   ├── urls.py
│   │   ├── asgi.py
│   │   ├── wsgi.py
│   │   └── celery.py
│   ├── common/
│   │   ├── context.py
│   │   ├── errors.py
│   │   ├── exceptions.py
│   │   ├── logging.py
│   │   ├── pagination.py
│   │   ├── renderers.py
│   │   ├── permissions.py
│   │   ├── authentication.py
│   │   ├── idempotency.py
│   │   ├── money.py
│   │   ├── time.py
│   │   ├── ids.py
│   │   ├── outbox.py
│   │   ├── inbox.py
│   │   ├── tasks.py
│   │   ├── audit.py
│   │   └── middleware.py
│   ├── health/
│   │   ├── views.py
│   │   └── urls.py
│   ├── api/
│   │   └── v1/urls.py
│   ├── accounts/
│   │   ├── models.py
│   │   ├── services.py
│   │   ├── selectors.py
│   │   ├── api/
│   │   ├── tasks.py
│   │   ├── events.py
│   │   └── migrations/
│   ├── identity/
│   ├── media/
│   │   ├── api/
│   │   ├── models.py
│   │   ├── services.py
│   │   ├── storage.py
│   │   └── migrations/
│   ├── catalog/
│   │   ├── api/
│   │   ├── models.py
│   │   ├── services.py
│   │   └── migrations/
│   ├── discovery/
│   │   ├── api/
│   │   ├── services.py
│   │   └── apps.py
│   ├── providers/
│   │   ├── api/
│   │   ├── models.py
│   │   ├── services.py
│   │   └── migrations/
│   ├── catalog/
│   ├── scheduling/
│   ├── content/
│   │   ├── api/
│   │   ├── models.py
│   │   ├── services.py
│   │   └── migrations/
│   ├── discovery/
│   ├── orders/
│   ├── payments/
│   ├── wallets/
│   ├── referrals/
│   ├── messaging/
│   ├── social/
│   ├── safety/
│   ├── notifications/
│   ├── moderation/
│   ├── adminops/
│   └── integrations/
│       ├── contracts.py
│       ├── payment/
│       ├── identity/
│       ├── messaging/
│       ├── moderation/
│       ├── geo/
│       ├── storage/
│       └── push/
└── tests/
    ├── unit/
    ├── services/
    ├── api/
    ├── integration/
    ├── migrations/
    ├── concurrency/
    └── factories/
```

## 2. 模块内文件规则

- `[DESIGN]` `models.py` 只定义持久化结构、约束和必要查询；`services.py` 放事务和业务命令；`selectors.py/queries.py` 放读模型；`api/` 放 DRF serializer/view/router。
- `[DESIGN]` 复杂模块可以拆 `domain/`、`application/`、`infrastructure/`；简单模块不强制拆空层。
- `[DESIGN]` `events.py` 只定义公开事件和订阅入口；`tasks.py` 只做异步编排，不隐藏业务规则。
- `[DESIGN]` `integrations/contracts.py` 定义稳定 Protocol/ABC，业务模块不导入厂商 SDK。
- `[DESIGN]` `providers` 只通过 `identity.services` 执行认证，不读取第三方认证凭证；`accounts` 管理首次身份和工作区，`providers` 只更新公开的服务者状态字段。
- `[DESIGN]` `providers` 通过 `media.services` 校验和引用媒体，不直接读写 `media_assets` 或文件存储；`media.storage` 是后续 OSS/COS 适配的替换边界。
- `[DESIGN]` `catalog` 管理服务配置和可售服务，依赖 `providers` 的公开资料权限和 `media` 的公开媒体服务；订单模块后续只消费服务价格快照。
- `[DESIGN]` `content` 管理动态、动态媒体、动态标签和动态状态事件；依赖 `providers`、`catalog` 和 `media` 公开服务。

## 3. 依赖规则

- `[DESIGN]` `common` 不得导入任何业务模块；`integrations` 不得导入业务模块。
- `[DESIGN]` 上层业务依赖下层公开服务/事件，禁止跨模块直接写对方表。
- `[DESIGN]` `discovery` 只读公开投影或索引；`adminops` 只调用业务命令，不复制业务规则。
- `[DESIGN]` 允许同一模块内直接访问自己的模型；跨模块聚合优先使用公开查询服务、只读视图或事件快照。
- `[DESIGN]` 依赖循环出现时先抽取公共契约或事件，不使用“互相 import models”解决。

## 4. 新模块最小模板

简单模块至少需要：`models.py`（如需数据）、`services.py`（如需写）、`api/`（如需接口）、`tests/`。复杂模块按需增加 `selectors.py/events.py/tasks.py/domain/`，不生成无内容的装饰性文件。

## 5. 迁移和配置

- `[DESIGN]` 每个业务模块拥有自己的 migrations；共享表归属清晰，禁止跨模块手写迁移。
- `[DESIGN]` 环境配置从环境变量/密钥服务读取；`.env.example` 只放变量名和安全说明。
- `[DESIGN]` `config/settings/prod.py` 禁止 DEBUG、测试绕过和默认密钥；开发配置不得用于生产。

