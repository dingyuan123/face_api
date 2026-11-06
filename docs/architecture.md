# 后端架构设计

## 1. 当前状态

- `[DESIGN]` 仓库已建立 Django/DRF 模块化单体工程基础，包含 PostgreSQL、Redis、Celery、OpenAPI、统一响应、追踪、测试和 Docker Compose 配置。
- `[DESIGN]` `accounts` 已实现手机号验证码登录/自动注册、数据库验证码、访问/刷新令牌、当前会话查询和首次身份选择；真实短信、密码登录和第三方登录尚未实现。
- `[DESIGN]` `identity` 已实现实名/人脸认证状态和开发 Mock 边界；`media` 已实现本地图片上传、安全处理、私有读取和所有权校验；`providers` 已实现当前范围的服务者申请、拒绝重提、幂等、版本控制和最小管理员审核。
- `[DESIGN]` 当前认证采用数据库保存验证码哈希和不透明令牌哈希；生产短信 mock 强制关闭，后续通过 `integrations` 短信适配器接入。

## 2. 架构结论

### 2.1 推荐技术栈

| 层级 | 选择 | 说明 |
|---|---|---|
| Web/API | Django + Django REST Framework | 成熟 ORM、迁移、认证、权限、序列化和后台能力 |
| OpenAPI | drf-spectacular | 生成并校验 `/api/v1` 与 `/admin/v1` 文档 |
| 主数据库 | PostgreSQL 16+ | 事务、约束、JSONB、全文检索和地理扩展能力 |
| 缓存/限流 | Redis | 缓存、限流、短期去重辅助；不作为资金最终事实 |
| 异步任务 | Celery + Redis broker | 通知、索引、补偿、结算和对账任务 |
| 测试 | pytest + pytest-django + Factory Boy | 单元、API、数据库、迁移和并发测试 |
| 工程检查 | Ruff | 格式、静态检查和导入规则 |
| 本地环境 | Docker Compose | Web、worker、beat、PostgreSQL、Redis |
| 对象存储 | OSS/COS 适配接口 | 图片、视频、证件密文引用 |

`[DESIGN]` 第一阶段不引入微服务、Kubernetes、Kafka、Elasticsearch 或独立规则引擎。搜索先使用 PostgreSQL 全文检索/索引；达到明确容量阈值后再通过适配层切换 Elasticsearch/Meilisearch。

### 2.2 为什么不直接采用 FastAPI

- `[DESIGN]` FastAPI 适合轻量 API 和高并发 I/O，但本项目主要难点是复杂事务、状态机、账务、审计、迁移、后台权限和长期维护，Django/DRF 提供更完整的一致性基础设施。
- `[DESIGN]` Django 的同步事务模型与 PostgreSQL 行锁、唯一约束、Outbox 更容易形成清晰的资金一致性方案。
- `[DESIGN]` Django Admin 可先支撑内部运营，但仍需自建 RBAC、敏感操作审批和审计 API，不能直接把模型后台暴露为全部运营能力。

## 3. 总体结构

```text
UniApp X Client
      │ HTTPS / JSON
      ▼
Nginx / Cloud Gateway
      │
      ▼
Django + DRF Modular Monolith
├── Public API /api/v1
├── Admin API /admin/v1
├── Application Services
├── Domain State Machines & Policies
├── Query Services
├── PostgreSQL
├── Outbox / Inbox
└── Celery Workers + Beat
      ├── Notification & Push
      ├── Search Index
      ├── Payment/Refund Reconciliation
      ├── Settlement & Rewards
      └── Scheduled State Transitions

External adapters:
Payment, Identity/Face, IM, Moderation, Map, Storage/CDN, Push
```

### 3.1 请求处理层次

1. 接口层：认证、输入反序列化、资源权限入口、输出格式。
2. 应用服务：编排事务、状态转换、领域事件和权限结果。
3. 领域层：状态机、金额计算、政策快照、幂等规则。
4. 持久化/查询层：模型约束、事务、公开查询和 Outbox。
5. 适配层：第三方 SDK/HTTP，不允许业务模块直接依赖厂商 SDK。

`[DESIGN]` 视图可调用应用服务，但不得直接拼接跨模块更新；序列化器不得决定资金结果。

## 4. 模块清单

当前已落地的业务调用关系为：`accounts.api -> accounts.services -> accounts.models`；服务者申请由 `providers.api -> providers.services` 调用 `identity.services` 完成开发 Mock，并通过 `accounts.models.User` 的公开字段更新服务者状态。正式认证接入后，`providers` 只依赖 `identity` 的稳定服务接口，不导入第三方 SDK。

- `accounts`：用户、认证凭据、验证码、令牌轮换/退出、首次身份和默认工作区。
- `identity`：实名/人脸认证记录、Mock/真实适配器边界和认证状态。
- `media`：媒体元数据、本地存储、图片规范化、私有读取、所有权/用途校验和上传幂等。
- `providers`：服务者申请、敏感资料密文、申请状态事件、幂等/版本控制和最小审核命令。
- `backend/common`：响应、错误、追踪、加密、分页和日志；不得反向依赖以上业务模块。

| 模块 | 职责 | 可独立演进 |
|---|---|---|
| `accounts` | 用户、登录凭据、首次身份、工作区、注销 | 是 |
| `identity` | 实名、人脸、技能认证、敏感凭证 | 是 |
| `media` | 图片规范化、本地/云存储、私有读取、媒体引用 | 是 |
| `providers` | 服务陪伴者入驻、资料、启用/停用、在线状态 | 依赖 accounts/identity/media |
| `catalog` | 服务类目、服务、媒体关联、审核 | 依赖 providers/media |
| `scheduling` | 周规则、时段、锁定与释放 | 依赖 providers/catalog |
| `content` | 动态、评论、点赞、资讯、举报 | 依赖 accounts/providers/catalog |
| `discovery` | 搜索、筛选、推荐接口 | 只读依赖多个公开模型 |
| `orders` | 下单、接单、改期、打卡、完成、状态日志 | 核心交易模块 |
| `payments` | 支付单、渠道回调、退款 | 依赖 orders，被资金模块订阅 |
| `wallets` | 托管账务、服务者收入、推广收益、流水、提现 | 依赖订单/支付结果 |
| `referrals` | 邀请归因、政策快照、奖励、冲减 | 依赖 accounts/orders/wallets |
| `messaging` | 订单会话、消息、解锁和留存 | 依赖 orders，IM 通过适配器 |
| `social` | 收藏、关注、评价、信用、黑名单 | 依赖 accounts/providers/orders |
| `safety` | 报警、行程分享、紧急联系人 | 依赖 orders/accounts |
| `notifications` | 站内信、推送、模板、发送记录 | 事件消费者 |
| `moderation` | 内容审核、风险事件、举报处理 | 事件消费者 |
| `adminops` | 管理员、RBAC、审核、仲裁、配置、审计 | 调用各模块公开命令 |
| `integrations` | 支付、实名、IM、地图、存储、推送、审核适配器 | 是 |
| `common` | ID、时间、金额、分页、错误、幂等、Outbox、追踪 | 不依赖业务模块 |

## 5. 依赖边界

- `[DESIGN]` 业务模块只依赖 `common` 和被依赖模块的 `services.py`、`events.py`、只读查询接口，不导入对方 `models.py` 后直接写入。
- `[DESIGN]` `orders` 是交易编排中心，但支付结果只能由 `payments` 验签后发布 `payment.succeeded.v1`，订单服务消费并更新订单。
- `[DESIGN]` `wallets` 不自行猜测订单收入，只消费带订单/支付/退款业务 ID 的已验证事件。
- `[DESIGN]` `referrals` 不读取订单内部状态自由计算，必须使用订单事件和订单奖励快照。
- `[DESIGN]` `discovery` 可读取公开投影或索引，不参与写事务。
- `[DESIGN]` `adminops` 不直接改业务表；调用业务模块公开命令并留下审计。

## 6. 一致性设计

### 6.1 数据库事务

- 下单：订单、服务快照、时段占用和订单状态日志在同一 PostgreSQL 事务内创建。
- 支付成功：支付单、订单支付状态、私信解锁意图、奖励快照和 Outbox 在同一事务内提交。
- 退款成功：退款、订单累计退款、收入/奖励调整意图和 Outbox 同一事务。
- 提现审核：冻结/扣减可用余额和提现单状态同一事务，打款结果异步回写。

### 6.2 Outbox/Inbox

- `[DESIGN]` 关键领域事件先写 `outbox_events`，提交后由 Celery 投递。
- `[DESIGN]` 消费端写 `inbox_messages`，以 `event_id + consumer_name` 唯一约束防止重复消费。
- `[DESIGN]` Redis 锁只减少重复执行，不替代数据库唯一约束和事务。

### 6.3 对账

- 每日核对订单、支付、退款、钱包流水、奖励和提现。
- 余额必须可由流水重放；差异进入告警和人工对账任务，不自动抹平。

## 7. 性能与扩展

- `[DESIGN]` 列表使用稳定游标分页，热点资料可缓存，缓存失效以事件驱动。
- `[DESIGN]` 视频使用对象存储和 CDN，API 只保存元数据与受控引用。
- `[DESIGN]` 位置搜索先用 PostgreSQL/地图服务；推荐算法通过 `RecommendationProvider` 接口解耦。
- `[DESIGN]` 城市、类目、文案和规则配置化；多语言先保持 API 文案 code + locale 能力，不在 MVP 实现完整翻译后台。
- `[CONFIRM]` 10 万同时在线服务者的目标需要结合消息推送、IM、视频并发和真实容量测试重新估算，不应据此提前引入集群架构。

## 8. 部署边界

- `[DESIGN]` 本地和验收环境使用 Docker Compose：`web`、`worker`、`beat`、`postgres`、`redis`。
- `[DESIGN]` 生产初期可部署多个无状态 Web/Worker 实例，由云负载均衡接入；不强制 Kubernetes。
- `[DESIGN]` PostgreSQL 使用托管高可用、定期备份和恢复演练；Redis 不承载不可恢复事实。
- `[CONFIRM]` 云厂商、支付商户主体、实名/人脸、内容审核、IM 和推送厂商需业务与合规确认。

