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

