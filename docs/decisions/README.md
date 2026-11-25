# 技术决策记录

## 规则

- 每个重要架构、数据、资金、安全和第三方边界决定一个 ADR。
- ADR 只追加状态变更和替代方案，不覆盖历史决定；被替代时新建 ADR 并互相引用。
- 结论必须区分 `[PRD]`、`[DESIGN]`、`[CONFIRM]`；在负责人确认前，ADR 状态保持“提议”。
- 资金、支付、退款、奖励、提现、隐私和权限的 ADR 变更需要明确审批。

## 模板

```markdown
# ADR-XXXX：标题

- 状态：提议 / 已接受 / 已替代 / 已废弃
- 日期：
- 决策人：

## 背景
## 决策
## 备选方案
## 影响
## 风险与缓解
## 验证
```

## 索引

- `0001-modular-monolith.md`：模块化单体和依赖边界。
- `0002-django-drf-stack.md`：Django/DRF 技术栈。
- `0003-postgres-ledger-and-money.md`：PostgreSQL 账务和金额。
- `0004-celery-redis-outbox.md`：异步任务和可靠事件。
- `0005-api-versioning-openapi-idempotency.md`：API 版本、OpenAPI、幂等。
- `0006-third-party-adapter-boundaries.md`：第三方适配边界。
- `0007-search-deferral.md`：搜索技术延迟决策。
- `0009-phone-sms-login.md`：手机号验证码登录、mock 短信边界和不透明令牌。
- `0010-provider-onboarding-and-mock-identity.md`：服务者入驻申请和开发期身份 Mock。
- `0011-local-media-storage.md`：开发期本地媒体存储、安全处理和云存储适配边界。
- `0012-current-session-logout.md`：退出当前设备会话和令牌撤销边界。
- `0013-temporary-signed-media-display-urls.md`：媒体临时展示地址和未来公开媒体边界。
- `0014-user-profile-and-interest-tags.md`：个人资料、兴趣标签配置和安心用户等级预留。
- `0015-provider-profile-and-service-management.md`：服务者资料、服务状态机和金额/价格快照边界。
- `0016-admin-service-list-and-home-feed.md`：管理员服务列表和首页服务者卡片聚合。
- `0017-provider-moments-image-publishing.md`：图文动态管理、发布即通过和动态媒体边界。
- `0018-django-admin-readonly-development.md`：开发期 Django Admin 只读查看和手机号登录边界。
- `0019-moment-vertical-neighbor-navigation.md`：动态详情上下滑动前后导航和稳定排序。
- `0020-public-moment-tabs-and-categories.md`：动态页推荐/关注/附近和动态类目配置。
- `0021-balance-wallet-booking-social-reviews.md`：钱包余额支付、预约订单、社交互动和评价窗口。
- `0022-provider-schedule-calendar-contract.md`：排期日历查询、响应模型、版本和预约状态语义。
- `0023-hourly-grid-and-contiguous-booking.md`：默认小时网格、服务者主动开放和多小时连续锁定。
- `0024-hourly-service-pricing-and-order-quote.md`：服务按小时计价、下单前报价和营销扩展边界。
- `0025-order-participants-contact-and-progress.md`：订单双方信息、加密电话联系和进度时间线。
- `0026-api-time-format-and-reviewed-refunds.md`：API 统一时间和后台审核全额退款。
- `0027-reviews-and-payouts.md`：评价管理、收款方式和收益提现测试流程。
- `0028-news-rss-favorites-share.md`：资讯 RSS 聚合、摘要版权边界、收藏和可配置分享域名。
- `0029-google-news-general-feed.md`：Google News 综合资讯来源适配。
- `0030-news-sync-cover-summary-policy.md`：资讯同步标题、摘要和封面补全策略。
- `0031-postgres-comprehensive-search.md`：PostgreSQL 综合搜索、搜索聚合和热门搜索控制。
- `0032-development-password-login-for-api-docs.md`：Swagger 联调用开发账号密码登录和生产禁用边界。
- `0033-location-search-and-tencent-map.md`：地图选点、公共场所过滤、距离计算和腾讯地图适配边界。
- `0034-provider-location-home-feed-order-location.md`：服务者加密位置、普通用户临时浏览位置和订单见面地点快照。
- `0035-role-promotion-after-provider-approval.md`：首次身份与服务者审核通过后的当前主身份提升。
- `0036-oauth-login-and-real-payment-adapters.md`：Apple/微信登录、手机号安全合并和微信/支付宝 App 支付适配。
- `0037-wechat-channel-reference-format.md`：微信支付商户渠道关联标识格式。
- `0038-order-based-realtime-chat.md`：基于订单的 WebSocket 聊天、消息事实和 Outbox 投递。
- `0039-shared-conversation-and-configurable-window.md`：用户—服务者共享会话、多订单复用、用户级隐藏和配置化发送窗口。
- `0040-profile-share-poster-data-contract.md`：个人分享海报数据、可配置文案、主页链接和前端二维码边界。
- `0041-referral-binding-and-reward-ledger.md`：一级邀请绑定、分享归因、奖励政策快照和推广收益冲减。
- `0042-identity-card-evidence-fields.md`：服务者申请和实名认证的身份证正反面资料边界。
- `0043-test-management-review-dashboard.md`：开发测试管理后台总览和实名/服务者人工审核界面。
- `0044-provider-dashboard-metrics.md`：服务者工作台指标、浏览事件和转化漏斗口径。
- `0045-admin-v1-auth-rbac-audit.md`：Vue 管理后台独立令牌、权限点、审计和用户/服务者管理基础。
- `0046-content-reports-and-sensitive-words.md`：内容举报、敏感词配置和管理员处理流程。
- `0047-support-ticket-workspace.md`：独立客服工单、客服消息、分配处理和常见问题。
- `0048-company-profile-admin-management.md`：管理后台公司简介、单例版本和营业执照媒体边界。
- `0049-public-company-profile-api.md`：普通用户公开查询公司简介和短期营业执照地址。
- `0050-code-and-display-label-responses.md`：状态、标签和审计代码与中文展示并列响应。
- `0051-alipay-rsa2-sign-type-inclusion.md`：支付宝 RSA2 请求签名保留 `sign_type` 的官方 SDK 对齐修复。
- `0052-account-deletion-lifecycle.md`：账号注销条件、验证码、个人数据清理和保留审计。
- `0053-admin-force-deletion-and-balance-clear.md`：管理员清空低额余额并强制注销的资金审计边界。
- `0054-account-security-phone-password.md`：账号密码设置、找回密码和更换绑定手机号流程。
- `0055-apple-login-nonce-compatibility.md`：UniApp Apple 登录 nonce 兼容与安全权衡。
- `0056-production-password-login.md`：正式账号密码登录、统一错误和失败次数锁定。

