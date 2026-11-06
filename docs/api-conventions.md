# API 设计规范

## 1. 版本和入口

- `[DESIGN]` 客户端业务接口统一 `/api/v1`，管理接口统一 `/admin/v1`。
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
| `GET` | `/api/v1/profile-options/interest-tags/` | 公开 | 读取启用中的兴趣标签配置 |
| `GET` | `/api/v1/profile-options/cities/` | 公开 | 读取启用中的城市代码配置 |
| `GET` | `/api/v1/provider-profile/me/` | 服务者 Bearer | 查询服务者资料 |
| `PATCH` | `/api/v1/provider-profile/me/` | 服务者 Bearer | `expected_version` 乐观锁 |
| `GET` | `/api/v1/provider-services/` | 服务者 Bearer | `page/page_size/status` 列表和汇总 |
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

- `[DESIGN]` 服务者申请请求字段为 `introduction`、写入专用的 `real_name/id_card_number`、`avatar_media_id`、`life_photo_media_ids[]`。
- `[DESIGN]` 申请响应只返回申请号、状态、资料展示字段、实名/人脸状态、拒绝原因、时间和版本，不返回真实姓名、身份证号或密文。
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

## 12. 开发测试账号密码登录

- `[DESIGN]` `POST /api/v1/dev/auth/password-login/` 请求字段为 `phone/password`，响应复用 `TokenPairResponseSerializer`。
- `[DESIGN]` Swagger 使用步骤：调用该接口获取 `access_token`，点击 Authorize，选择 Bearer Token 并粘贴 `access_token`；页面会持久保存授权，直到浏览器清理或令牌失效。
- `[DESIGN]` `password` 只写不返回，日志过滤器必须脱敏；接口响应、trace、OpenAPI 示例和错误详情均不得记录明文密码。
- `[DESIGN]` 错误约定：账号或密码错误为 401 `AUTH_INVALID_CREDENTIALS`，账号状态异常为 403 `AUTH_ACCOUNT_NOT_ALLOWED`，开发开关关闭或生产环境为 404 `SYSTEM_NOT_FOUND`。
- `[DESIGN]` 创建独立会话并支持 `Idempotency-Key`；重复同键同请求复用令牌，不同请求返回 409 `AUTH_IDEMPOTENCY_CONFLICT`。
- `[CONFIRM]` 正式密码登录 API 不在当前版本承诺范围内，不能被 App 或生产客户端依赖。

