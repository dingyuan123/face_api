# API 设计规范

## 1. 版本和入口

- `[DESIGN]` 客户端业务接口统一 `/api/v1`，管理接口统一 `/admin/v1`。
- `[DESIGN]` Vue 管理后台使用独立 `AdminBearerTokenAuth`：`POST /admin/v1/auth/login/` 登录，`GET /admin/v1/auth/me/` 获取权限，`POST /admin/v1/auth/refresh/` 轮换令牌，`POST /admin/v1/auth/logout/` 撤销会话。
- `[DESIGN]` 管理员登录启用验证码时先调用 `POST /admin/v1/auth/captcha/`，登录提交 `captcha_token/captcha_answer`；密码找回使用 `POST /admin/v1/auth/password/forgot/` 和 `POST /admin/v1/auth/password/reset/`，验证码按 `PASSWORD_RESET` 用途消费。
- `[DESIGN]` 既有 `/api/v1/admin/*` 接口兼容 `AdminBearerTokenAuth` 和平台用户 Bearer Token；迁移期间 Vue 管理后台可以统一使用 `/admin/v1/auth/login/` 获取的 Token 调用两套管理接口。
- `[DESIGN]` 管理后台权限点必须在服务端逐接口校验，当前首批包括 `admin.dashboard.read/admin.user.read/admin.user.ban/admin.provider.read/admin.provider.status/admin.audit.read/admin.rbac.*`。
- `[DESIGN]` 管理员写操作统一记录 `AdminOperationLog`，用户封禁/解封和服务者停用/恢复要求 `expected_version`、原因并可使用 `Idempotency-Key`。
- `[DESIGN]` 管理列表统一返回 `items,total,page,page_size`；详情返回单对象；所有新接口必须维护 OpenAPI 分页对象，不再把分页响应声明成数组。
- `[DESIGN]` 管理后台首页支持 `GET /admin/v1/dashboard/overview/`、`GET /admin/v1/dashboard/trends/?range=7d|30d` 和 `GET /admin/v1/dashboard/todos/`。
- `[DESIGN]` 角色管理支持创建、查看、修改、删除和整体替换权限点；删除仅允许无成员且非 `SUPER_ADMIN` 的角色，所有写操作记录统一审计。
- `[DESIGN]` 管理员订单列表和详情支持 `GET /admin/v1/orders/`、`GET /admin/v1/orders/{order_no}/`，统一使用 `admin.order.read` 权限点。
- `[DESIGN]` 管理员财务接口支持 `GET /admin/v1/finance/overview/`、`GET /admin/v1/finance/transactions/`、`GET /admin/v1/finance/transactions/export/`，流水合并钱包和收益账本且不导出收款账户。
- `[DESIGN]` 管理员佣金接口支持 `GET /admin/v1/commission/overview/`、`GET /admin/v1/commission/trends/`、`GET /admin/v1/commission/details/`；当前佣金类型为 `PROVIDER_COMMISSION`。
- `[DESIGN]` 退款审核支持管理员指定 `refund_amount_minor` 进行部分退款，申请金额与实际同意金额分别返回 `refund_amount_minor/approved_refund_amount_minor`。
- `[DESIGN]` 财务对账支持 `GET /admin/v1/finance/reconciliation/`；提现管理支持 `GET /admin/v1/withdrawals/` 和 `POST /admin/v1/withdrawals/{request_no}/actions/{action}/`，动作支持 `approve/reject/retry`。
- `[DESIGN]` 用户举报接口为 `POST /api/v1/reports/`；管理员举报接口为 `GET /admin/v1/reports/` 和 `POST /admin/v1/reports/{report_no}/actions/{action}/`，动作支持 `resolve/reject`。
- `[DESIGN]` 敏感词管理接口为 `GET/POST /admin/v1/sensitive-words/`、`PATCH/DELETE /admin/v1/sensitive-words/{word_id}/`；删除采用停用状态并保留审计。
- `[DESIGN]` 平台数据看板支持 `GET /admin/v1/analytics/overview/`、`/analytics/trends/`、`/analytics/breakdown/`，维度支持 `city/category/service_category/provider/channel`；`category` 与 `service_category` 为兼容别名。
- `[DESIGN]` 系统设置支持 `GET/PATCH /admin/v1/settings/basic/` 和公告 `GET/POST /admin/v1/settings/announcements/`、`PATCH/DELETE /admin/v1/settings/announcements/{announcement_no}/`；基础配置修改需要版本号并记录审计。
- `[DESIGN]` 系统设置支持城市、服务类目和佣金规则：`GET/POST /admin/v1/settings/cities/`、`PATCH/DELETE /admin/v1/settings/cities/{code}/`、`GET/POST /admin/v1/settings/service-categories/`、`PATCH/DELETE /admin/v1/settings/service-categories/{code}/`、`GET/PATCH /admin/v1/settings/commission-rules/`。
- `[DESIGN]` 客服模块使用独立工单，不复用订单 IM 权限：用户接口位于 `/api/v1/support/`，客服工作台位于 `/admin/v1/support/`。工单支持分类、优先级、订单关联、消息、分配、解决和关闭。
- `[DESIGN]` 同一版本内只做向后兼容新增；删除/改语义/改类型必须新建版本或经过迁移窗口。
- `[DESIGN]` 每个接口由 `drf-spectacular` 生成 OpenAPI；发布前校验 schema、示例、错误码和幂等说明。
- `[DESIGN]` 请求和响应使用 UTF-8 JSON；文件、音视频使用对象存储短期签名地址，不直接回传大文件。

## 2. 统一响应

成功响应：

```json
{
  "code": 0,
  "message": "success",
  "data": {},
  "meta": {"trace_id": "01J..."},
  "trace_id": "01J..."
}
```

失败响应：

```json
{
  "code": "ORDER_STATE_CONFLICT",
  "message": "订单状态不允许该操作",
  "details": {"current_status": "PENDING_ACCEPT"},
  "trace_id": "01J..."
}
```

规则：

- `[DESIGN]` HTTP 状态码表达传输/语义大类，`code` 是稳定机器码；客户端不得依赖 `message`。
- `[DESIGN]` `message` 为可本地化的安全文案；`details` 不得包含敏感数据。
- `[DESIGN]` OpenAPI 请求参数和响应字段必须提供中文 `description`；serializer 通过 `help_text` 维护，方便前端理解取值、单位、是否可空和敏感写入规则。
- `[DESIGN]` 所有请求生成 `trace_id`/`request_id`，响应始终返回 `trace_id`。
- `[DESIGN]` 202 表示已接受异步任务，`data` 返回业务单号和查询地址。

## 3. 错误码

| 系列 | HTTP 示例 | 场景 |
|---|---:|---|
| `AUTH_*` | 400/401/403 | 凭据、验证码、令牌、工作区 |
| `USER_*` | 400/403/409/422 | 资料、身份、年龄、状态 |
| `PROVIDER_*` | 400/403/409/422 | 入驻、认证、服务者状态 |
| `SERVICE_*` | 400/404/409/422 | 服务、类目、排期、上架 |
| `ORDER_*` | 400/403/404/409/422 | 订单状态、排期、操作权限 |
| `PAYMENT_*` | 400/402/409/422 | 支付单、渠道、回调、金额 |
| `REFUND_*` | 400/402/409/422 | 退款、仲裁、金额 |
| `WALLET_*` | 400/403/409/422 | 账本、余额、提现、对账 |
| `REFERRAL_*` | 400/403/409/422 | 归因、政策、奖励、收益 |
| `CONTENT_*` | 400/403/404/409/422 | 动态、资讯、评论、审核 |
| `RISK_*` | 403/423/429 | 风控冻结、反刷、限流 |
| `ADMIN_*` | 401/403/409/422 | RBAC、审批、审计 |
| `SYSTEM_*` | 500/503 | 依赖不可用、内部失败 |

`[DESIGN]` 错误码命名、文案和 OpenAPI 维护在代码常量/枚举，禁止散落在视图字符串中。

### 3.1 枚举和配置标签展示

- `[DESIGN]` 请求继续提交稳定代码；响应保留原代码字段，不使用中文文本作为写入值。
- `[DESIGN]` 固定状态响应使用 `code + code_text` 并列结构，例如 `status/status_text`，中文由服务端统一映射。
- `[DESIGN]` 兴趣标签、服务类目、服务标签和资料标签返回 `code/name/category/sort_order` 对象；同时保留 `*_codes` 便于旧客户端兼容。
- `[DESIGN]` 管理审计返回 `action/action_text/target_type/target_type_text`，未知动作只回退为“未知操作”，原始代码仍保留用于排查。
- `[DESIGN]` 历史订单服务标签可回退当前配置名称；后续如需完全历史一致，应增加下单时名称快照。

## 4. 分页、排序和查询

- `[DESIGN]` 列表默认游标分页：`limit`（默认 20，最大 100）、`cursor`、`sort`、`order`；响应 `meta.next_cursor/has_more`。
- `[DESIGN]` 后台报表允许页码分页，但必须固定排序键并返回 `page/page_size/total`。
- `[DESIGN]` 排序字段白名单化；搜索词长度、筛选组合、时间范围和坐标范围限制。
- `[DESIGN]` 未登录只能访问公开内容；登录接口返回的资源必须按用户权限脱敏。

## 5. 时间、金额和标识

- `[DESIGN]` API 对外时间统一 `YYYY-MM-DD HH:mm:ss`，按 `Asia/Shanghai` 展示，例如 `2026-10-27 14:00:00`；数据库内部继续保存 UTC 时间，日期字段保持 `YYYY-MM-DD`。
- `[DESIGN]` API 金额统一 `currency` + `amount_minor`（CNY 最小单位分），例如 `{"currency":"CNY","amount_minor":9900}`；禁止 Float 和隐式元/分转换。
- `[DESIGN]` 内部数据库金额统一 `BIGINT` 分；百分比/比例用 `basis_points` 或 `rate_bp` 整数。
- `[DESIGN]` 公共资源使用不可枚举的 `public_id`（UUID），业务单号使用带前缀的 `order_no/payment_no/refund_no`。
- `[DESIGN]` 客户端传入 `client_request_id` 时必须按用户、接口和请求体哈希做幂等。

## 6. 认证和授权

- `[DESIGN]` 公共端使用短期访问令牌和可轮换的刷新令牌；刷新令牌按设备保存，支持退出、封禁和异常撤销。
- `[DESIGN]` 管理端使用独立管理员账号、MFA（高风险角色）、RBAC 和审计；管理员令牌不与用户令牌混用。
- `[DESIGN]` 每个资源接口同时校验身份认证、角色、对象归属、状态和细粒度动作权限；只校验“已登录”不算权限控制。
- `[DESIGN]` 高风险动作要求二次确认、原因和 `expected_version`/乐观锁。
- `[CONFIRM]` 第三方登录绑定/解绑、注销、设备并发数、令牌有效期和客服脱敏级别。

## 7. 幂等和并发

- `[DESIGN]` `POST` 写接口支持 `Idempotency-Key`；服务端将用户、路由、请求体哈希、结果状态写入幂等记录，重复请求返回同一业务结果。
- `[DESIGN]` 支付/退款回调使用渠道事件 ID、渠道交易号和业务单号幂等，不使用 HTTP 重试次数作为幂等依据。
- `[DESIGN]` 状态变更要求 `expected_version` 或状态条件；冲突返回 `409`，不得覆盖最近状态。
- `[DESIGN]` 重试只对网络错误、429、5xx 和明确的可重试错误进行；业务错误不自动重试。

## 8. 资源接口约束

- `[DESIGN]` 订单、支付、退款、奖励、钱包、提现接口必须记录业务单号、状态日志和 `trace_id`。
- `[DESIGN]` 回调接口不使用普通用户认证；必须验签、来源限制、时间戳/随机数防重放，并返回渠道要求的响应。
- `[DESIGN]` 文件上传先获取受控上传凭证，服务端校验 MIME、大小、哈希和审核状态；不接受任意 URL 当作内容。

### 9.1 当前本地媒体上传

- `[DESIGN]` `POST /api/v1/media/uploads/` 使用 `multipart/form-data`，字段为 `purpose` 和 `file`；当前用途仅限服务者申请头像/生活照。
- `[DESIGN]` 上传只接受单帧 JPEG、PNG、WebP，并校验真实格式、尺寸、像素量和大小；服务端重新编码并移除 EXIF。
- `[DESIGN]` 上传可携带 `Idempotency-Key`；同用户、同用途、同内容去重，同键不同内容返回 409。
- `[DESIGN]` `GET /api/v1/media/{media_id}/content/` 返回原图内容，只允许上传者或 `is_staff` 访问，并设置 `private, no-store`。
- `[DESIGN]` `display_url` 指向 `GET /api/v1/media/display/{media_id}/`，带 `expires/key_version/signature` 查询参数，不要求 Authorization，有效期内可重复加载。
- `[DESIGN]` `display_url_expires_at` 返回 RFC 3339 过期时间；前端过期后重新请求业务接口获取新地址。
- `[DESIGN]` 后续接入 OSS/COS 时保持 `media_id` 和业务接口不变，通过存储适配器或短期签名 URL 替换本地内容读取。
- `[DESIGN]` 接口不返回身份证、人脸、完整手机号、银行卡、精确位置或第三方原始凭据；后台查看需单独权限和审计。

## 9. 事件和异步查询

- `[DESIGN]` 异步接口返回业务单号；事件通知采用版本化事件名，例如 `order.paid.v1`。
- `[DESIGN]` 事件 payload 只包含必要标识和快照引用，敏感原文按权限解密。
- `[DESIGN]` 客户端轮询使用资源状态接口和 `ETag/If-Match` 或版本号，避免用无界长轮询替代必要通知。

## 10. 当前账号和服务者入驻接口

| 方法 | 路径 | 权限 | 幂等/并发 |
|---|---|---|---|
| `POST` | `/api/v1/auth/logout/` | 用户 Bearer | 状态幂等；撤销当前会话令牌 |
| `POST` | `/api/v1/users/me/initial-role/` | 用户 Bearer | 同值重复成功，异值返回 409 |
| `POST` | `/api/v1/provider-applications/` | 用户 Bearer | `Idempotency-Key` 按用户作用域去重 |
| `GET` | `/api/v1/provider-applications/me/` | 用户 Bearer | 只返回本人最新申请 |
| `PATCH` | `/api/v1/provider-applications/me/` | 用户 Bearer | 仅拒绝/取消后可重提；要求 `expected_version` |
| `GET` | `/api/v1/admin/provider-applications/` | `is_staff` Bearer | 游标分页 |
| `GET` | `/api/v1/admin/provider-applications/{application_no}/` | `is_staff` Bearer | 无 |
| `POST` | `/api/v1/admin/provider-applications/{application_no}/approve/` | `is_staff` Bearer | 要求 `expected_version` |
| `POST` | `/api/v1/admin/provider-applications/{application_no}/reject/` | `is_staff` Bearer | 要求 `expected_version` 和拒绝原因 |
| `POST` | `/api/v1/media/uploads/` | 用户 Bearer | `Idempotency-Key` + 内容哈希去重 |
| `GET` | `/api/v1/media/{media_id}/content/` | 上传者或 `is_staff` Bearer | 仅私有读取 |
| `GET` | `/api/v1/media/display/{media_id}/` | 签名 URL | 10 分钟内可重复加载 |
| `GET` | `/api/v1/users/me/profile/` | 用户 Bearer | 查询本人资料 |
| `PATCH` | `/api/v1/users/me/profile/` | 用户 Bearer | `expected_version` 乐观锁 |
| `GET` | `/api/v1/users/me/share-poster/` | 用户 Bearer | 获取个人分享海报数据 |
| `GET` | `/api/v1/referrals/me/` | 用户 Bearer | 分享赚钱页总览 |
| `POST` | `/api/v1/referrals/me/share-links/` | 用户 Bearer | 按渠道生成分享链接 |
| `GET` | `/api/v1/referrals/me/rewards/summary/` | 用户 Bearer | 奖励状态汇总 |
| `GET` | `/api/v1/referrals/me/rewards/` | 用户 Bearer | 奖励明细分页 |
| `POST` | `/api/v1/referrals/visits/` | 公开 | 记录匿名分享访问，不绑定账号 |
| `GET` | `/api/v1/profile-options/interest-tags/` | 公开 | 读取启用中的兴趣标签配置 |
| `GET` | `/api/v1/profile-options/cities/` | 公开 | 读取启用中的城市代码配置 |
| `GET` | `/api/v1/provider-profile/me/` | 服务者 Bearer | 查询服务者资料 |
| `PATCH` | `/api/v1/provider-profile/me/` | 服务者 Bearer | `expected_version` 乐观锁 |
| `GET` | `/api/v1/provider-services/` | 服务者 Bearer | `page/page_size/status` 列表和汇总 |
| `GET` | `/api/v1/provider-dashboard/` | 服务者 Bearer | `range=7d/30d` 工作台和数据看板 |
| `POST` | `/api/v1/provider-services/` | 服务者 Bearer | 创建 `DRAFT`，支持 `Idempotency-Key` |
| `GET/PATCH/DELETE` | `/api/v1/provider-services/{service_id}/` | 服务者 Bearer | 查询、编辑、逻辑删除草稿 |
| `POST` | `/api/v1/provider-services/{service_id}/submit-review/` | 服务者 Bearer | `expected_version` |
| `POST` | `/api/v1/provider-services/{service_id}/online/` | 服务者 Bearer | `expected_version` |
| `POST` | `/api/v1/provider-services/{service_id}/offline/` | 服务者 Bearer | `expected_version` |
| `GET` | `/api/v1/provider-options/service-categories/` | 公开 | 服务类目配置 |
| `GET` | `/api/v1/provider-options/service-tags/` | 公开 | 服务标签配置 |
| `GET` | `/api/v1/provider-options/provider-tags/` | 公开 | 服务者资料标签配置 |
| `GET` | `/api/v1/admin/provider-services/` | `is_staff` Bearer | 服务管理列表、筛选、分页和汇总 |
| `GET` | `/api/v1/home/feed/` | 公开/可选 Bearer | 首页服务者卡片流 |
| `GET/POST` | `/api/v1/provider-moments/` | 服务者 Bearer | 动态列表、创建草稿 |
| `GET/PATCH/DELETE` | `/api/v1/provider-moments/{moment_id}/` | 服务者 Bearer | 动态详情、修改、逻辑删除 |
| `POST` | `/api/v1/provider-moments/{moment_id}/publish/` | 服务者 Bearer | 当前直接发布，未来可进入审核 |
| `GET` | `/api/v1/provider-moments/mountable-services/` | 服务者 Bearer | 获取可挂载的 ONLINE 服务 |
| `GET` | `/api/v1/moments/` | 公开 | 公开已发布动态列表 |
| `GET` | `/api/v1/moments/{moment_id}/` | 公开 | 公开动态详情 |
| `GET` | `/api/v1/moments/{moment_id}/neighbors/` | 公开 | 上下滑动的前驱/后继动态 |
| `GET` | `/api/v1/moment-options/categories/` | 公开 | 动态内容类目配置 |
| `GET` | `/api/v1/providers/{provider_public_id}/` | 公开 | 服务者公开资料页 |
| `GET` | `/api/v1/services/{service_id}/` | 公开 | 普通用户查询已上架服务详情 |
| `POST/DELETE` | `/api/v1/users/{user_public_id}/follow/` | 用户 Bearer | 关注/取消关注 |
| `POST/DELETE` | `/api/v1/favorites/` | 用户 Bearer | 收藏/取消收藏 |
| `GET` | `/api/v1/me/following/` | 用户 Bearer | 关注列表 |
| `GET` | `/api/v1/me/favorites/` | 用户 Bearer | 收藏列表 |
| `POST/DELETE` | `/api/v1/moments/{moment_id}/like/` | 用户 Bearer | 动态点赞/取消 |
| `GET/POST` | `/api/v1/moments/{moment_id}/comments/` | 用户 Bearer | 动态评论列表/发表 |
| `DELETE` | `/api/v1/comments/{comment_id}/` | 用户 Bearer | 删除本人评论 |
| `GET/POST` | `/api/v1/provider-schedule-slots/` | 服务者 Bearer | 预约时段管理 |
| `DELETE` | `/api/v1/provider-schedule-slots/{slot_id}/` | 服务者 Bearer | 删除未锁定时段 |
| `PATCH` | `/api/v1/provider-schedule-slots/{slot_id}/status/` | 服务者 Bearer | 切换时段可约/不可约状态 |
| `GET` | `/api/v1/provider-schedule/calendar/` | 服务者 Bearer | 月历、周历或自定义排期 |
| `GET` | `/api/v1/provider-schedule/calendar/{day}/` | 服务者 Bearer | 单日排期和时段 |
| `POST` | `/api/v1/provider-schedule/bulk-update/` | 服务者 Bearer | 工作日、周末或全部日期批量设置 |
| `GET/POST` | `/api/v1/provider-schedule/rules/` | 服务者 Bearer | 周排期规则查询和创建 |
| `PATCH/DELETE` | `/api/v1/provider-schedule/rules/{rule_id}/` | 服务者 Bearer | 修改或删除周排期规则 |
| `GET` | `/api/v1/providers/{provider_public_id}/availability/` | 公开 | 可预约时段 |
| `GET/POST` | `/api/v1/orders/` | 用户 Bearer | 订单列表/创建 |
| `POST` | `/api/v1/orders/quotes/` | 用户 Bearer | 下单前按小时计算金额 |
| `GET` | `/api/v1/orders/summary/` | 用户 Bearer | 用户或服务者订单状态数量 |
| `GET` | `/api/v1/orders/{order_no}/` | 用户 Bearer | 订单详情 |
| `GET/POST` | `/api/v1/orders/{order_no}/refund-requests/` | 用户 Bearer | 查询和提交退款申请 |
| `POST` | `/api/v1/refund-requests/{request_no}/cancel/` | 用户 Bearer | 撤销待审核退款申请 |
| `GET` | `/api/v1/admin/refund-requests/` | `is_staff` Bearer | 查询退款申请 |
| `POST` | `/api/v1/admin/refund-requests/{request_no}/approve/` | `is_staff` Bearer | 同意并执行全额退款 |
| `POST` | `/api/v1/admin/refund-requests/{request_no}/reject/` | `is_staff` Bearer | 拒绝退款申请 |
| `POST` | `/api/v1/admin/refund-requests/{request_no}/retry/` | `is_staff` Bearer | 重试失败退款申请 |
| `POST` | `/api/v1/orders/{order_no}/pay/` | 用户 Bearer | 钱包余额支付 |
| `POST` | `/api/v1/orders/{order_no}/cancel/` | 用户 Bearer | 用户取消订单 |
| `POST` | `/api/v1/orders/{order_no}/actions/{action}/` | 用户/服务者 Bearer | 接单、开始、完成、确认 |
| `POST` | `/api/v1/orders/{order_no}/reject/` | 服务者 Bearer | 服务者拒绝订单 |
| `GET/POST` | `/api/v1/orders/{order_no}/reviews/` | 用户 Bearer | 订单评价 |
| `GET` | `/api/v1/providers/{provider_public_id}/reviews/` | 公开 | 服务者评价列表 |
| `POST` | `/api/v1/reviews/{review_id}/replies/` | 服务者 Bearer | 回复评价 |
| `GET` | `/api/v1/me/reviews/` | 用户 Bearer | 我的待评价和已评价列表 |
| `GET` | `/api/v1/provider-reviews/` | 服务者 Bearer | 服务者收到的评价管理列表 |
| `GET` | `/api/v1/provider-reviews/{review_id}/` | 服务者 Bearer | 服务者评价详情 |
| `POST` | `/api/v1/provider-reviews/{review_id}/reply/` | 服务者 Bearer | 服务者评价回复 |
| `GET` | `/api/v1/wallet/` | 用户 Bearer | 钱包余额 |
| `GET` | `/api/v1/wallet/transactions/` | 用户 Bearer | 钱包流水 |
| `POST` | `/api/v1/admin/wallet/topups/` | `is_staff` Bearer | 开发测试充值 |
| `GET` | `/api/v1/users/me/summary/` | 用户 Bearer | 我的订单、收藏和关注数量 |
| `GET/POST` | `/api/v1/payout-methods/` | 用户 Bearer | 查询和绑定收款方式 |
| `POST` | `/api/v1/payout-methods/{id}/set-default/` | 用户 Bearer | 设置默认收款方式 |
| `POST` | `/api/v1/payout-methods/{id}/deactivate/` | 用户 Bearer | 逻辑停用收款方式 |
| `GET` | `/api/v1/earnings/account/` | 用户 Bearer | 查询服务者收入或推广收益账户 |
| `GET` | `/api/v1/earnings/entries/` | 用户 Bearer | 查询收益明细 |
| `GET` | `/api/v1/earnings/transactions/` | 用户 Bearer | 查询收益不可变流水 |
| `GET/POST` | `/api/v1/withdrawals/` | 用户 Bearer | 查询和提交提现申请 |
| `POST` | `/api/v1/withdrawals/{id}/cancel/` | 用户 Bearer | 撤销待审核提现 |
| `GET` | `/api/v1/admin/withdrawals/` | `is_staff` Bearer | 管理员提现审核列表 |
| `POST` | `/api/v1/admin/withdrawals/{id}/approve/` | `is_staff` Bearer | 审核通过并模拟打款 |
| `POST` | `/api/v1/admin/withdrawals/{id}/reject/` | `is_staff` Bearer | 拒绝提现并解冻余额 |
| `POST` | `/api/v1/admin/withdrawals/{id}/retry/` | `is_staff` Bearer | 失败提现重试打款 |

- `[DESIGN]` 订单支付当前只支持 `payment_method=BALANCE`，后续微信/支付宝通过支付适配器增加。
- `[DESIGN]` 订单评价窗口为完成后 7 天，超过窗口返回 `REVIEW_WINDOW_EXPIRED`。
- `[DESIGN]` 用户不能自主充值，测试充值只能由管理员在测试配置中调用。
- `[DESIGN]` 评价响应包含服务摘要、评价用户摘要、服务者摘要和回复；匿名评价不返回评价用户昵称、头像或公开 UUID。
- `[DESIGN]` 我的评价支持 `status=ALL|PENDING|REVIEWED`，服务者评价管理支持 `rating/has_reply/date_from/date_to` 筛选。
- `[DESIGN]` 收款方式支持 `BANK_CARD/ALIPAY/WECHAT_PAY`，当前使用模拟验证和模拟打款，账号只返回脱敏字段；接口幂等键使用 `Idempotency-Key`。
- `[DESIGN]` 提现必须人工审核，状态为 `PENDING_REVIEW/PROCESSING/SUCCESS/FAILED/REJECTED/CANCELED`；最低金额、手续费、佣金和结算周期由环境/规则配置，当前测试默认值不代表生产规则。
| `GET` | `/api/v1/admin/moments/` | `is_staff` Bearer | 动态管理列表 |
| `POST` | `/api/v1/admin/moments/{moment_id}/approve/` | `is_staff` Bearer | 审核通过 |
| `POST` | `/api/v1/admin/moments/{moment_id}/reject/` | `is_staff` Bearer | 审核拒绝 |

- `[DESIGN]` 当前动态发布接口在 `MOMENT_REVIEW_MODE=IMMEDIATE` 下直接进入 `PUBLISHED`；管理员审核接口保留给未来 `REVIEW_REQUIRED` 模式。
- `[DESIGN]` 动态挂载服务是可选字段，公开动态挂载服务必须是服务者本人的 `ONLINE` 服务。
- `[DESIGN]` 图文动态只接受 `MOMENT_IMAGE` 媒体，动态响应只返回媒体摘要和临时 `display_url`。
- `[DESIGN]` 动态邻居接口使用 `published_at DESC, public_id DESC` 稳定顺序，并返回 `feed_context` 保持分类、关键词和排序一致。
- `[DESIGN]` 公开动态列表支持 `tab=RECOMMENDED/FOLLOWING/NEARBY`；当前推荐使用 NEWEST，附近使用城市代码，关注暂未开放。
- `[DESIGN]` 动态列表、详情和相邻动态响应包含 `viewer_state`：`is_liked`、`is_favorited`、`is_following`；服务端依据登录会话计算，未登录时均返回 `false`。
- `[DESIGN]` 评论列表和发表响应包含评论用户公开摘要 `user.public_id`、`user.nickname`、`user.avatar_media`；`user_public_id` 继续保留用于兼容，响应不得包含用户敏感信息。

- `[DESIGN]` 服务价格响应使用 `pricing_unit=HOUR`、`price.currency/price.amount_minor`，另提供只读每小时 `price_display`；不接受 `68.00` 字符串作为唯一金额来源。
- `[DESIGN]` 金额试算响应返回小时单价、预约小时数、原价、优惠、平台费、应付金额、明细、服务版本和时段版本；当前折扣为空，后续营销可以扩展 `discounts/breakdown`。
- `[DESIGN]` 公开服务详情只返回 `ONLINE` 未删除服务，草稿、审核中、拒绝和下架服务返回 404。
- `[DESIGN]` 订单列表支持 `role=USER/PROVIDER` 和状态筛选；订单汇总分别统计普通用户下单和服务者接单数量。
- `[DESIGN]` 我的页面汇总返回用户订单数、服务者订单数、收藏数、关注数、粉丝数及订单状态数量。
- `[DESIGN]` 订单列表和详情返回结构化 `service`，包含服务名称、计价、时长、介绍、封面和图集媒体；服务记录缺失时使用下单时保存的服务快照和媒体 ID 恢复展示。
- `[DESIGN]` 订单详情返回 `participants.contact.progress`：双方昵称和头像、服务者评分/评价数/完成单数、当前用户可联系的对方电话、按钮文案和完整状态时间线。
- `[DESIGN]` `contact.phone_dial/tel_uri` 只返回当前登录者需要联系的对方号码；订单进行中可拨号，订单完成后仅在评价窗口内可拨号。
- `[DESIGN]` 订单履约状态不单独设置“待评价”；`progress.review_status` 使用 `NOT_AVAILABLE/NOT_REVIEWED/REVIEWED/EXPIRED` 派生展示状态和 `can_review`。
- `[DESIGN]` 服务状态操作只接受当前版本号，拒绝重复提交、越权、无效状态和并发覆盖。
- `[DESIGN]` `provider-profile/me` 没有资料头像时，允许回退展示服务者申请头像，避免已上传申请头像在资料接口中丢失。
- `[DESIGN]` 首页照片卡片按最近创建时间取最多 5 张，来源包括申请生活照、资料照片墙和服务相关媒体；没有完整动态数据时明确标记 `UNKNOWN/null`。
- `[DESIGN]` 服务列表为后台页码分页，返回 `items/total/page/page_size/summary`；公开列表仍使用游标分页。

- `[DESIGN]` 排期日历支持 `view=MONTH/WEEK/CUSTOM`、锚点 `date`、自定义 `date_from/date_to` 和 IANA `timezone`；月历为自然月，周历固定 7 天，自定义范围最长 366 天。
- `[DESIGN]` 日历/单日响应返回 `schedule_version/date_from/date_to/days/summary`，日期返回 `date/weekday/is_today/is_rest/status/counts/slots`，不再返回泛型对象。
- `[DESIGN]` 批量响应返回新 `schedule_version`、`updated/opened/closed/deleted/skipped_locked/skipped_booked/failed` 数量以及结构化 `warnings/errors`。
- `[DESIGN]` 批量请求的 `expected_version` 取日历或单日 `schedule_version`；时段 PATCH 的 `expected_version` 取时段 `version`；规则 PATCH/DELETE 的 `expected_version` 取规则 `version`。
- `[DESIGN]` 时段响应状态为 `OPEN/CLOSED/LOCKED/BOOKED`，最近预约结果由 `last_booking_status` 返回；取消后 `status=OPEN` 且 `last_booking_status=CANCELLED`。
- `[DESIGN]` 公开可预约响应只返回下单所需最小字段，`slot_version` 用于创建订单的 `expected_slot_version`，不返回 `locked_order_no`、拒绝原因、销量或管理版本字段。
- `[DESIGN]` 公开可预约接口支持 `date=YYYY-MM-DD` 查询指定日期；不传日期时默认返回服务者本地当天，`date` 不能与 `date_from/date_to` 同时使用。
- `[DESIGN]` `service_id` 为兼容预留参数；当前所有服务共用服务者通用时段，传入后不参与可预约时间筛选，后续服务级排期开放时再启用。
- `[DESIGN]` 每天默认提供 `00:00–24:00` 的 60 分钟单元，初始 `CLOSED`；服务者可单个或批量切换为 `OPEN`，客户端不得把默认单元视为已开放。
- `[DESIGN]` 服务时长必须为 60 分钟倍数。创建订单的 `slot_id` 是预约起始小时单元，后端根据服务时长锁定连续单元；缺少任一连续单元时整个请求失败。
- `[DESIGN]` 当前 `SCHEDULE_MAX_BOOKING_MINUTES=0` 表示不限制单次预约总时长，后续可通过配置限制。

- `[DESIGN]` 个人资料修改支持局部字段；`interest_tag_codes` 传入时整体替换，最多 5 个稳定标签代码。
- `[DESIGN]` 响应中的 `trust_level` 当前仅为预留字段，客户端不得通过资料修改接口写入等级。
- `[DESIGN]` 个人分享海报响应字段为 `brand_name/brand_label/slogan_line_1/slogan_line_2/slogan_subtitle/cover/nickname/age/city/signature/interest_tags/profile_url/qr_image_url/qr_image_expires_at/card_footer/bottom_slogan/share`。
- `[DESIGN]` `cover` 复用 `MediaAssetSummary`；`age` 未填写时为 `null`，`interest_tags` 返回展示名称。`share` 包含 `link_url/title/description`。
- `[DESIGN]` `profile_url` 与 `share.link_url` 相同，格式为 `PUBLIC_SHARE_BASE_URL/invite/` 并携带 `invite_code/share_no`；H5 页面公开托管，不包含 Bearer Token、手机号或身份证信息。
- `[DESIGN]` `qr_image_url` 是后端生成的二维码 PNG 短期签名地址，`qr_image_expires_at` 返回 `YYYY-MM-DD HH:mm:ss`；二维码内容编码 `profile_url`，不是 `qr_image_url`。
- `[DESIGN]` 二维码图片地址可不带 Authorization 加载，但必须校验签名和过期时间；过期后前端重新请求海报接口获取新地址。
- `[DESIGN]` 扫码后的落地方式应优先使用 App Universal Link/Deep Link；若微信或浏览器无法直接打开 App，则使用携带 `invite_code/share_no` 的 H5 落地页引导注册，归因参数最终由登录请求提交。
- `[DESIGN]` 海报文案由 `SHARE_POSTER_*` 配置读取，OpenAPI 返回当前运行配置值，客户端不得把示例文案当作不可变业务规则。

### 分享推广接口

- `[DESIGN]` 登录接口统一支持可选 `referral_context`：`invite_code/share_no（兼容 share_id）/channel/campaign_code/visitor_id`；只有新用户注册或 OAuth 首次完成手机号绑定时会创建归因。
- `[DESIGN]` `GET /api/v1/referrals/me/` 返回 `invite_code/share_link/registered_count/ordered_user_count/valid_order_amount_minor/reward_summary`。
- `[DESIGN]` `POST /api/v1/referrals/me/share-links/` 请求 `channel/campaign_code`，支持 `Idempotency-Key`；重复同键同请求返回同一链接，同键异参返回 409。
- `[DESIGN]` `POST /api/v1/referrals/visits/` 请求 `share_no` 或 `invite_code` 以及可选 `visitor_id`；接口只记录匿名访问，不直接绑定邀请人。
- `[DESIGN]` 奖励响应包含 `reward_no/order_no/currency/reward_base_minor/reward_rate_bps/amount_minor/status/settle_after/settled_at/version/policy_version`，不返回邀请人内部主键或账户流水。
- `[DESIGN]` 管理员接口为 `GET/POST /api/v1/admin/referral-policies/`、`POST /api/v1/admin/referral-policies/{policy_no}/retire/`、`GET /api/v1/admin/referrals/attributions/`、`GET /api/v1/admin/referrals/rewards/`、`POST /api/v1/admin/referrals/rewards/{reward_no}/actions/{action}/` 和 `POST .../adjust/`。
- `[DESIGN]` 服务者数据看板响应包含 `range/today/overview/comparison/income_trend/funnel/suggestions`；待评价数量只统计用户未评价订单。
- `[DESIGN]` 公开服务者主页和服务详情接口接受 `X-Visitor-ID` 或 `visitor_id` 匿名访问标识，服务端只保存 HMAC 摘要；正常下单、支付、完成接口会自动记录转化事件。
- `[DESIGN]` 奖励状态动作只接受 `freeze/unfreeze/cancel`，调整接口提交 `expected_version/amount_delta_minor/reason` 和 `Idempotency-Key`；所有人工操作写状态日志。
- `[DESIGN]` 奖励政策版本只创建和停止生效，不修改历史版本；订单始终按支付时快照计算。
- `[DESIGN]` 下单试算和订单价格响应新增 `platform_commission_amount_minor`；它表示服务者收入中的平台佣金，不改变用户 `payable_amount_minor`。当前 `platform_fee_amount_minor` 保持 0。

- `[DESIGN]` 服务者申请请求字段为 `introduction`、写入专用的 `real_name/id_card_number`、`avatar_media_id`、`life_photo_media_ids[]`。
- `[DESIGN]` 申请响应只返回申请号、状态、资料展示字段、实名/人脸状态、拒绝原因、时间和版本，不返回真实姓名、身份证号或密文。
- `[DESIGN]` 申请请求新增必填 `id_card_front_media_id/id_card_back_media_id`；响应返回对应媒体 ID 和 `MediaAssetSummary`，方便本人回显和管理员审核。
- `[DESIGN]` 身份证照片只能使用本人上传的 `IDENTITY_CARD_FRONT/IDENTITY_CARD_BACK` 媒体；错主、错用途、已删除媒体统一返回 `MEDIA_NOT_FOUND`。
- `[DESIGN]` 服务者申请新增 `emergency_contact_name/emergency_contact_phone`；响应只返回 `emergency_contact_name/emergency_contact_phone_masked`，不返回完整手机号。
- `[DESIGN]` 普通用户实名接口为 `GET /api/v1/identity/real-name/me/` 和 `POST /api/v1/identity/real-name/submit/`，提交后返回 `PENDING`，不执行人脸认证。
- `[DESIGN]` 管理员人工审核接口为 `GET /api/v1/admin/identity/verifications/` 和 `POST /api/v1/admin/identity/verifications/{verification_no}/actions/{action}/`，动作只接受 `approve/reject`，要求 `expected_version`。
- `[DESIGN]` 服务者申请提交后也进入实名 `PENDING`，管理员通过服务者申请前必须先通过实名人工审核；服务者申请响应的 `face_status` 当前为 `NOT_SUBMITTED`。
- `[DESIGN]` 当前最小管理员接口使用 `is_staff`，只用于开发和早期运营；正式后台必须替换为独立管理员认证、RBAC、MFA 和审计权限。

### 资讯接口

- `[DESIGN]` App 只读接口为 `GET /api/v1/news/`、`GET /api/v1/news/{news_id}/`、`GET /api/v1/news/categories/` 和 `GET /api/v1/news/{news_id}/share/`。
- `[DESIGN]` 管理员接口为 `GET/POST /api/v1/admin/news/`、`GET/PATCH/DELETE /api/v1/admin/news/{news_id}/`、`POST .../publish/`、`POST .../reject/`。
- `[DESIGN]` 外部来源和一键同步接口为 `GET/POST /api/v1/admin/news/sources/`、`PATCH /api/v1/admin/news/sources/{source_code}/`、`POST /api/v1/admin/news/sync/` 和 `GET /api/v1/admin/news/sync/{run_no}/`。
- `[DESIGN]` 资讯创建支持 `Idempotency-Key`；编辑、审核和删除必须提交 `expected_version`，版本冲突返回 `NEWS_VERSION_CONFLICT`。
- `[DESIGN]` 资讯附件和挂载卡片只接受安全 `http/https` 外链；平台图片使用 `NEWS_IMAGE` 媒体 ID，不直接上传文件到资讯接口。
- `[DESIGN]` 分享响应为 `share_url/share_title/share_summary/share_image_url`，不返回用户 ID、登录态或签名令牌。

## 11. 搜索接口约定

- `[DESIGN]` 综合搜索入口为 `GET /api/v1/search/?keyword=台球&limit=3`，响应按 `providers/moments/news` 分组，每组包含 `total/items/has_more`；`limit` 为每组预览数量，默认 3、最大 20。
- `[DESIGN]` 分类搜索入口为 `GET /api/v1/search/providers/`、`GET /api/v1/search/moments/`、`GET /api/v1/search/news/`，统一接受 `keyword`、`limit` 和 `cursor`，返回 `items/total/next_cursor/has_more/limit`；资讯列表额外支持 `category_code`。
- `[DESIGN]` `GET /api/v1/search/trending/?limit=10` 为公开“大家都在搜”接口，返回 `items/total/limit`；每项包含 `keyword/display_text/hot_type/hot_score/rank/updated_at`，默认 `hot_score=null`。
- `[DESIGN]` `GET/POST /api/v1/admin/search/trending/` 和 `PATCH /api/v1/admin/search/trending/{trending_id}/` 只允许管理员访问；创建/修改使用 `display_keyword/display_status/manual_priority/expected_version`。
- `[DESIGN]` 热门展示状态为 `ACTIVE/HIDDEN/BLOCKED`，分别表示展示、下线和屏蔽；人工置顶数字越小越靠前，0 表示不置顶。
- `[DESIGN]` 搜索写操作的幂等自然键是规范化关键词；相同配置的重复创建返回 `reused=true`，不同配置返回 `SEARCH_TRENDING_STATE_INVALID`；更新并发返回 `SEARCH_VERSION_CONFLICT`。
- `[DESIGN]` 搜索接口不接受客户端提交用户身份、结果可见范围、排序权重或热度分数；服务端只使用登录者身份补充公开动态的互动状态。

## 12. 开发测试账号密码登录

- `[DESIGN]` `POST /api/v1/dev/auth/password-login/` 请求字段为 `phone/password`，响应复用 `TokenPairResponseSerializer`。
- `[DESIGN]` Swagger 使用步骤：调用该接口获取 `access_token`，点击 Authorize，选择 Bearer Token 并粘贴 `access_token`；页面会持久保存授权，直到浏览器清理或令牌失效。
- `[DESIGN]` `password` 只写不返回，日志过滤器必须脱敏；接口响应、trace、OpenAPI 示例和错误详情均不得记录明文密码。
- `[DESIGN]` 错误约定：账号或密码错误为 401 `AUTH_INVALID_CREDENTIALS`，账号状态异常为 403 `AUTH_ACCOUNT_NOT_ALLOWED`，开发开关关闭或生产环境为 404 `SYSTEM_NOT_FOUND`。
- `[DESIGN]` 创建独立会话并支持 `Idempotency-Key`；重复同键同请求复用令牌，不同请求返回 409 `AUTH_IDEMPOTENCY_CONFLICT`。
- `[CONFIRM]` 正式密码登录 API 不在当前版本承诺范围内，不能被 App 或生产客户端依赖。

## 17. 管理后台公司资料接口

- `[DESIGN]` `GET/PATCH /admin/v1/settings/company-profile/` 返回和维护公司全称、公司简介、营业执照媒体摘要及 `version`。
- `[DESIGN]` 首次创建提交 `expected_version=0`，更新提交查询响应返回的版本；版本冲突返回 409 `ADMIN_VERSION_CONFLICT`。
- `[DESIGN]` `POST /admin/v1/settings/company-profile/license/` 使用 multipart 上传营业执照并返回 `media_id` 和短期 `display_url`；重复上传使用 `Idempotency-Key` 去重。
- `[DESIGN]` 公司资料写接口可选 `Idempotency-Key`；同键同请求复用结果，同键不同请求返回 409 `ADMIN_IDEMPOTENCY_CONFLICT`。

## 18. 账号注销接口

- `[DESIGN]` `GET /api/v1/account/deletion/check/` 固定返回 `orders/wallet/services/security` 四项条件和 `can_delete`，未通过项返回操作文案与前端路由。
- `[DESIGN]` `POST /api/v1/account/deletion/sms-code/` 只向绑定手机号发送注销验证码；沿用 60 秒频率限制、5 分钟有效和验证码尝试次数限制。
- `[DESIGN]` `POST /api/v1/account/deletion/` 校验 `code/confirm` 与注销条件后执行清理；成功后撤销全部用户令牌并立即拒绝后续请求。
- `[DESIGN]` 清理个人资料、动态、评论、点赞、收藏、关注和登录绑定；交易、支付、退款、提现、聊天、客服、评价和安全审计按隐私要求保留或匿名化。
- `[DESIGN]` 注销审计保留条件快照、清理数量、验证码请求标识和完成时间；服务层重复调用不会重复执行清理。
- `[CONFIRM]` 生产短信服务商、会员/优惠券权益清理和更长期的合规留存周期仍需接入对应模块后确认。

### 18.1 管理员强制注销和资金清空

- `[DESIGN]` `POST /admin/v1/users/{user_public_id}/balances/clear/` 仅允许 `admin.finance.adjust` 权限，清空钱包和收益余额并写入不可变调整流水。
- `[DESIGN]` `POST /admin/v1/users/{user_public_id}/force-delete/` 仅允许 `admin.user.force_delete` 权限，跳过用户注销资金门槛但强制清空余额后执行个人资料和内容清理。
- `[DESIGN]` 两个接口必须填写管理员原因，支持 `Idempotency-Key`，返回清空/取消的资金明细和审计结果。
- `[DESIGN]` 强制注销仍保留交易、支付、退款、提现、聊天、客服、评价和安全审计，不允许删除用户主键和资金流水。

## 19. 账号密码、忘记密码和手机号更换

- `[DESIGN]` `GET /api/v1/users/me/security/` 返回手机号脱敏值、是否设置密码、登录方式、换绑/找回能力和有效设备会话数。
- `[DESIGN]` 首次设置密码和修改密码使用 `POST /api/v1/users/me/password/`；首次设置需要绑定手机号验证码，修改已有密码还需当前密码。
- `[DESIGN]` 忘记密码使用 `POST /api/v1/auth/password/forgot/sms-code/` 和 `POST /api/v1/auth/password/reset/`，成功后撤销全部设备令牌。
- `[DESIGN]` 换绑手机号使用 `POST /api/v1/users/me/phone-change/` 和 `POST /api/v1/users/me/phone-change/confirm/`；已有手机号需要新旧手机号双验证码，无手机号账号使用当前密码和新手机号验证码。
- `[DESIGN]` 新手机号已经绑定其他账号时返回 `AUTH_PHONE_ALREADY_BOUND`，不在换绑流程中隐式合并账号。
- `[DESIGN]` 密码和手机号安全事件写入不可变审计，不记录明文密码、手机号、验证码或令牌；密码/换绑成功后保留当前设备并撤销其他设备令牌。

## 20. Apple 登录 nonce 兼容

- `[DESIGN]` Apple 登录继续强制校验 `identity_token` 的签名、`iss=https://appleid.apple.com`、`aud=APPLE_CLIENT_ID`、`exp`、`iat` 和 `sub`。
- `[DESIGN]` 当前 UniApp X 内置 Apple 登录 SDK 不支持向 Apple 传入自定义 nonce，因此 token 缺少 `nonce` claim 时进入兼容模式；请求体仍接收 `nonce` 用于审计。
- `[DESIGN]` 如果 Apple token 包含 `nonce`，后端必须验证其等于请求 nonce 原文或 SHA-256 值。
- `[CONFIRM]` 后续接入支持 nonce 的原生 Apple 登录模块后，应恢复严格 nonce 防重放校验。

## 21. 正式账号密码登录

- `[DESIGN]` `POST /api/v1/auth/password/login/` 请求 `phone/password/referral_context`，响应复用 `TokenPairResponseSerializer`，包含 `requires_phone_binding` 和 `requires_identity_selection`。
- `[DESIGN]` 账号不存在、未设置密码或密码错误统一返回 401 `AUTH_INVALID_CREDENTIALS`，提示“手机号或密码错误”，不泄露账号是否存在。
- `[DESIGN]` 连续 5 次密码错误临时锁定 15 分钟；锁定期间返回 423 `AUTH_LOGIN_LOCKED`，成功登录后清零失败次数。
- `[DESIGN]` `Idempotency-Key` 与验证码登录一致；同键同请求复用令牌，同键不同请求返回 409 `AUTH_IDEMPOTENCY_CONFLICT`。

## 18. 普通用户公司资料接口

- `[DESIGN]` `GET /api/v1/company-profile/` 无需登录，返回公司全称、公司简介和营业执照展示信息。
- `[DESIGN]` 营业执照仅返回 `media_id/content_type/width/height/display_url/display_url_expires_at`，不返回 `content_url`、存储路径、管理员信息或版本号。
- `[DESIGN]` 公司资料未初始化时返回空资料和 `business_license_media=null`，接口保持 200。

## 16. 订单实时聊天接口与 WebSocket

- `[PRD]` 聊天仅围绕已建立的预约订单关系；客户端不能自行创建任意私聊或选择非订单参与人。
- `[DESIGN]` 同一预约用户与同一服务者共享一个会话，多个有效订单复用该会话；订单接口返回的会话也是该共享会话，最新关联订单决定当前聊天状态。
- `[DESIGN]` HTTP 路由：
  - `GET /api/v1/orders/{order_no}/conversation/`：获取订单会话、参与人摘要和订单摘要。
  - `GET /api/v1/messaging/conversations/providers/{provider_public_id}/`：按服务者打开或恢复当前用户可见的共享会话。
  - `GET /api/v1/conversations/`：分页获取当前用户会话列表。
  - `DELETE /api/v1/conversations/{conversation_id}/`：仅对当前用户隐藏会话，不删除聊天记录。
  - `GET /api/v1/conversations/{conversation_id}/messages/`：按 `limit/before_sequence/after_sequence` 获取历史消息或断线补偿。
  - `POST /api/v1/conversations/{conversation_id}/messages/`：发送 `TEXT` 或 `IMAGE` 消息。
  - `POST /api/v1/conversations/{conversation_id}/read/`：更新单调递增的已读序号。
  - `GET /api/v1/messaging/unread-summary/`：获取会话未读数汇总。
  - `POST /api/v1/messaging/ws-ticket/`：签发短时效一次性 WebSocket 票据。
- `[DESIGN]` 消息请求固定为 `client_message_id/message_type/content/media_id`；`client_message_id` 由客户端生成并保证同一用户同一会话内唯一，服务端按 `conversation + sender + client_message_id` 幂等。
- `[DESIGN]` 会话响应增加 `orders/order_count`，返回双方全部聊天资格订单安全摘要；`order` 为决定当前状态的最新订单。消息创建响应包含 `message/ack`。
- `[DESIGN]` 订单支付成功后，服务端在同一业务事务内幂等创建或恢复共享会话、双方成员和订单关联，并写入 `sender_public_id=null`、`sender_role=SYSTEM`、`message_type=SYSTEM` 的支付成功提示；服务者是否接单不影响双方打开会话。
- `[DESIGN]` 支付成功系统消息的 `client_message_id` 固定为 `system:order-paid:<order_no>`，会出现在消息历史、双方会话列表的 `last_message` 和 `unread_count`；重复支付确认不会产生第二条消息。
- `[DESIGN]` 历史已支付订单可执行 `python manage.py backfill_paid_order_conversations --dry-run` 核对范围，再执行不带参数的命令幂等补齐；命令重复执行复用已有会话和系统消息。
- `[DESIGN]` 同一幂等 ID 复用首次请求内容时返回首次消息；内容不同返回 409 `MESSAGING_IDEMPOTENCY_CONFLICT`。消息响应返回服务端分配的严格递增 `sequence`。
- `[DESIGN]` 时间字段统一返回 `YYYY-MM-DD HH:mm:ss`；消息历史采用 `sequence` 游标，不使用时间作为唯一游标。
- `[DESIGN]` WebSocket 连接为 `/ws/messages/?ticket=<ticket>`，生产通过 `wss://`；票据由 `POST /api/v1/messaging/ws-ticket/` 获取，默认 60 秒过期、只能消费一次，URL 不接受长期 Access Token。
- `[DESIGN]` WebSocket 连接成功后必须发送 `subscribe` 才接收该会话广播，推荐订阅帧为 `{"action":"subscribe","conversation_id":"<conversation_id>"}`；不订阅时不会主动推送任意用户会话。
- `[DESIGN]` WebSocket 客户端事件：`subscribe`、`message.send`、`read`；服务端事件：`connection.ready`、`subscription.confirmed`、`message.ack`、`message.created`、`read.updated`、`error`。
- `[DESIGN]` WebSocket 每次订阅都校验当前用户是否为订单会话成员；消息发送复用 HTTP 的订单状态、幂等、序号和媒体校验服务。
- `[DESIGN]` `IMAGE` 消息只能引用发送者本人上传且 `purpose=CHAT_IMAGE` 的媒体；请求返回媒体 ID、`display_url` 和 `display_url_expires_at`，不得返回存储原路径。
- `[DESIGN]` 订单支付成功后开放聊天；订单完成后的发送窗口由 `MESSAGING_COMPLETED_SEND_WINDOW_DAYS` 配置，默认 7 天，超过窗口只读。取消、退款或订单关闭后会话只读/关闭；新订单可恢复共享会话。
- `[DESIGN]` `DELETE /api/v1/conversations/{conversation_id}/` 只设置当前成员的 `hidden_at`，会话和消息仍按留存策略保存；再次访问服务者会话入口可恢复可见。
- `[PRD]` 聊天记录按要求至少保存 180 天；发送窗口结束不等于记录删除，两者是独立规则。
- `[DESIGN]` 会话响应只返回参与人公开摘要、脱敏手机号和必要订单摘要，不返回身份证、完整手机号、精确位置或支付凭据。
- `[CONFIRM]` 生产环境发送窗口天数、聊天撤回规则、离线推送、消息审核/敏感词策略以及 180 天后的删除和司法调取流程。

## 13. 第三方登录与支付接口

- `[DESIGN]` `POST /api/v1/auth/apple/login/` 请求 `identity_token/nonce/platform`，仅允许 iOS App；`POST /api/v1/auth/wechat/login/` 请求 `code/state/platform`，仅允许 App 登录。
- `[DESIGN]` `POST /api/v1/users/me/phone-binding/` 请求 `phone/code`，响应复用令牌结构并增加 `already_bound/merged`；成功后旧第三方空账号令牌被撤销。
- `[DESIGN]` `POST /api/v1/orders/{order_no}/pay/` 请求 `expected_version/payment_method`，支付方式枚举为 `BALANCE/WECHAT_APP/ALIPAY_APP`。余额支付同步成功，外部支付返回 `payment_action=NATIVE_PAY` 和客户端 SDK 参数。
- `[DESIGN]` `GET /api/v1/payments/{payment_no}/` 只允许付款用户查询；微信/支付宝 notify 接口不暴露在普通业务权限体系内，必须验签、核对商户、支付单和金额并幂等处理。
- `[DESIGN]` 外部支付单未收到有效回调前保持 `PENDING`，订单保持 `PENDING_PAYMENT`；前端不得根据 SDK 唤起成功自行把订单标记为已支付。
- `[DESIGN]` 退款申请状态增加 `PROCESSING`，表示审核通过且原渠道退款执行中；请求幂等键、支付幂等键和退款幂等键分别隔离，不互相复用。

## 13. 地点搜索接口约定

- `[DESIGN]` `GET /api/v1/location-search/quick-keywords/` 返回启用中的快捷关键词，登录用户可读取 `code/label/query_keyword/icon/sort_order`。
- `[DESIGN]` `GET /api/v1/location-search/` 接受 `keyword` 或 `quick_keyword_code`、`latitude`、`longitude`、`coordinate_system=GCJ02|WGS84`、`radius_m` 和 `limit`。
- `[DESIGN]` 搜索响应返回 `query_keyword/center/coordinate_system/radius_m/provider/provider_total/items/filtered_count`；每个地点包含地址、POI ID、分类、经纬度、`distance_m` 和 `distance_text`。
- `[DESIGN]` `GET/POST /api/v1/admin/location-search/quick-keywords/` 和 `PATCH/DELETE /api/v1/admin/location-search/quick-keywords/{keyword_id}/` 只允许管理员访问；创建支持 `Idempotency-Key`，修改和停用必须提交 `expected_version`。
- `[DESIGN]` 地点搜索只读操作不使用幂等键；管理员创建使用 `Idempotency-Key + request_fingerprint`，同键同请求复用，同键不同请求返回 `LOCATION_QUICK_KEYWORD_CONFLICT`。
- `[DESIGN]` 参数错误返回 `LOCATION_SEARCH_INVALID`，请求词不允许返回 422 `LOCATION_KEYWORD_NOT_ALLOWED`，快捷词不存在返回 `LOCATION_QUICK_KEYWORD_NOT_FOUND`，地图服务失败返回 503 `LOCATION_PROVIDER_UNAVAILABLE`，并发修改返回 409 `LOCATION_QUICK_KEYWORD_VERSION_CONFLICT`。
- `[DESIGN]` OpenAPI 必须完整描述查询参数、坐标系枚举、距离单位、过滤数量和管理员版本字段；不得出现腾讯 Key、内部请求地址或日志字段。

## 14. 位置更新、首页和订单地点接口

- `[DESIGN]` `GET/PUT/DELETE /api/v1/provider/location/` 只允许已开通服务者查询、更新和撤销当前位置；响应不包含经纬度。
- `[DESIGN]` `POST /api/v1/home/feed/` 的浏览者坐标只在请求处理期间使用，响应距离保留一位小数；原 `GET /api/v1/home/feed/` 继续支持不带位置的城市浏览。
- `[DESIGN]` 地点搜索项增加 `selection_token/selection_expires_at`，凭证包含 POI 地址、经纬系坐标、分类和地点规则版本。
- `[DESIGN]` `POST /api/v1/orders/quotes/` 可选提交 `location_selection_token`，`POST /api/v1/orders/` 必须提交该凭证。
- `[DESIGN]` 订单响应新增 `meeting_location`，只向订单参与人返回完整地址和经纬度；不包含用户当前位置。
- `[DESIGN]` 地点凭证签名错误返回 `LOCATION_SELECTION_INVALID`，过期或规则版本变化返回 `LOCATION_SELECTION_EXPIRED`。

## 15. 会话身份字段

- `[DESIGN]` 会话和首次身份响应返回 `primary_role/current_role/roles/default_workspace/provider_status`。
- `[DESIGN]` `primary_role` 是当前主身份，服务者审核通过后为 `PROVIDER`；`roles` 表示可用身份，普通用户始终保留 `USER`。
- `[DESIGN]` `initial_role` 只用于后端一次性首次身份校验，不再作为客户端当前身份展示字段。
- `[DESIGN]` 客户端路由优先使用 `current_role/default_workspace`，避免把首次选择身份误认为当前服务者状态。

## 12. 开发测试账号密码登录

- `[DESIGN]` `POST /api/v1/dev/auth/password-login/` 请求字段为 `phone/password`，响应复用 `TokenPairResponseSerializer`。
- `[DESIGN]` Swagger 使用步骤：调用该接口获取 `access_token`，点击 Authorize，选择 Bearer Token 并粘贴 `access_token`；页面会持久保存授权，直到浏览器清理或令牌失效。
- `[DESIGN]` `password` 只写不返回，日志过滤器必须脱敏；接口响应、trace、OpenAPI 示例和错误详情均不得记录明文密码。
- `[DESIGN]` 错误约定：账号或密码错误为 401 `AUTH_INVALID_CREDENTIALS`，账号状态异常为 403 `AUTH_ACCOUNT_NOT_ALLOWED`，开发开关关闭或生产环境为 404 `SYSTEM_NOT_FOUND`。
- `[DESIGN]` 创建独立会话并支持 `Idempotency-Key`；重复同键同请求复用令牌，不同请求返回 409 `AUTH_IDEMPOTENCY_CONFLICT`。
- `[CONFIRM]` 正式密码登录 API 不在当前版本承诺范围内，不能被 App 或生产客户端依赖。

