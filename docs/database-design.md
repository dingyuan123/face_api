# 数据库设计规范

## 1. 通用约定

- `[DESIGN]` PostgreSQL 为唯一主事实数据库；Redis 只用于缓存、限流、短期去重和任务锁。
- `[DESIGN]` 业务表包含 `id BIGINT GENERATED ALWAYS AS IDENTITY`、`public_id UUID`（对外）、`created_at/updated_at`（`timestamptz`）、必要时 `deleted_at`、`version`、`created_by/updated_by`。
- `[DESIGN]` 金额字段以 `BIGINT` 保存人民币分；字段名以 `_amount_minor` 或明确注释单位。禁止 `FLOAT/REAL/DOUBLE`。
- `[DESIGN]` 比例保存 `basis_points/rate_bp` 整数；时间保存 UTC，业务时区在展示层处理。
- `[DESIGN]` 状态字段使用受控枚举/短字符串和 CheckConstraint；核心状态变化必须有日志表。
- `[DESIGN]` JSON 只保存快照和非核心扩展；参与查询、约束、统计的字段独立建列。
- `[DESIGN]` 每张业务表使用 `Meta.db_table_comment` 写中文表备注；每个明确字段使用 `db_comment` 写中文列备注。
- `[DESIGN]` 字段备注说明业务用途、单位、状态、关联、敏感处理和生命周期。含义不明确的字段禁止猜测，进入 `docs/open-questions.md`。
- `[DESIGN]` 备注迁移只调整结构定义和 PostgreSQL `COMMENT`，不得借迁移修改业务数据。
- `[DESIGN]` `earning_accounts(user, account_type, currency)` 唯一；金额约束保证可用、冻结、累计收入和累计提现非负。
- `[DESIGN]` `earning_entries` 按账户、业务类型、业务单号和幂等键唯一；订单收入、结算和提现流水均不可覆盖。
- `[DESIGN]` `payout_methods(user, method_type, account_fingerprint)` 防止重复绑定；每个用户最多一个启用中的默认收款方式。
- `[DESIGN]` `withdrawals(user, idempotency_key)` 和 `withdrawal_status_logs(withdrawal, action, idempotency_key)` 保证重复请求不重复冻结或重复打款。
- `[DESIGN]` 收款方式账号使用 Fernet 密文和 HMAC 指纹保存，接口只读取脱敏字段；提现保存收款快照以支持历史审计。

## 2. 表分组

### 2.1 账号身份

- `users`：用户状态、`primary_role`、`default_workspace`、`provider_enabled/provider_status`、邀请字段、信用分。
- `user_auths`：手机号/密码/微信/Apple 凭据；`auth_type + auth_identifier` 唯一。
- `user_profiles`：昵称、头像、性别、用户填写年龄、城市代码、签名、安心用户预留等级、版本和资料时间。
- `profile_interest_tags`：可配置兴趣标签代码、中文名称、分类、排序和启用状态。
- `profile_city_options`：可配置城市代码、中文名称、排序和启用状态。
- `user_profile_interests`：个人资料与兴趣标签的有序关联，同一资料同一标签唯一。
- `user_roles`：角色授予/撤销历史。
- `identity_verifications`：实名、人脸认证类型、状态、第三方请求号和结果码；一个用户每种认证类型唯一。
- `provider_applications`：入驻申请、媒体 ID、个人简介、真实姓名/身份证密文、带密钥身份证 HMAC、Mock 状态、幂等键、版本和审核结果。
- `provider_application_events`：申请提交、重提、通过、拒绝的追加式状态事件、操作者、原因和 trace_id。
- `provider_profiles`：服务者昵称、签名、个人介绍、头像、版本和服务者资料时间。
- `provider_profile_categories`、`provider_profile_tags`、`provider_profile_media`：服务者类目、标签和照片墙有序关联。
- `service_categories`、`service_tags`、`provider_tags`：服务类目、服务标签和服务者标签配置。
- `provider_services`：服务 UUID、类目、价格最小单位、时长、介绍、封面、地点类型、状态、审核结果、只读已售数量和版本。
- `provider_service_media`、`provider_service_tags`：服务图集和服务标签有序关联。
- `provider_service_events`：服务创建、修改、审核、上下架和逻辑删除的追加式事件。
- `moments`：动态发布者、类型、文案、封面、可见范围、推荐开关、状态、挂载服务、互动计数、幂等和发布时间。
- `moment_media`、`moment_tag_links`：动态图片/视频有序媒体和标签关联。
- `moment_tags`：动态标签配置。
- `moment_events`：动态创建、修改、发布、审核和删除的追加式事件。
- `wallet_accounts`：用户币种余额、冻结金额和版本。
- `wallet_transactions`：不可变钱包 `CREDIT/DEBIT` 流水，关联业务单号和幂等键。
- `wallet_topups`：管理员开发测试充值记录。
- `payments`：订单支付单、渠道、金额、状态和幂等信息。
- `refunds`：支付退款单和退款金额。
- `user_follows`、`user_favorites`、`moment_likes`：关注、收藏和点赞唯一关系。
- `moment_comments`、`moment_comment_events`：动态评论和评论状态事件。
- `schedule_slots`：服务者预约时段、可选服务绑定、当前状态、最近预约结果、锁定订单和版本。
- `orders`、`order_schedule_slots`、`order_status_logs`：预约订单价格/资料/时段快照、连续小时单元关联和状态日志。
- `reviews`、`review_tags`、`review_tag_links`、`review_replies`、`provider_rating_stats`：用户评价、标签、服务者回复和评分聚合。
- `payout_methods`、`payout_method_events`：普通用户和服务者共用的银行卡、支付宝、微信收款方式；账号密文、脱敏展示、验证状态、默认状态和停用审计。
- `earning_accounts`、`earning_entries`、`earning_transactions`：服务者收入和普通用户推广收益账户、收益业务记录和不可变资金流水。
- `withdrawals`、`withdrawal_status_logs`：提现申请、手续费、收款快照、人工审核、模拟打款和完整状态审计。
- `discovery` 当前不新建首页落表；首页读取 `provider_profiles`、`user_profiles`、`provider_services`、申请/服务媒体和认证状态，后续动态推荐需要新增 `moments/moment_media` 与曝光数据。
- `provider_profiles`：展示资料、统计、在线状态、接单开关。
- `verification_codes`：手机号哈希、验证码哈希、用途、过期、尝试、消费和发送幂等信息。
- `verification_send_guards`：按手机号哈希保存下一次允许发送时间，用数据库行锁控制并发重发。
- `auth_login_requests`：登录请求指纹、幂等键、会话 ID 和成功结果，用于重复登录返回同一令牌结果。
- `auth_tokens`：访问/刷新令牌哈希、会话、过期、撤销和最后使用时间；不保存令牌明文。

### 2.2 内容服务

- `media_assets`：媒体所有者、用途、状态、本地存储键、内容类型、尺寸、大小、内容 SHA-256、上传幂等键和引用时间。
- `service_categories`：层级类目、图标、排序、状态、城市适用范围。
- `services`：服务快照基础、价格分、时长、地点规则、上下架和审核状态。
- `service_media`、`moment_media`：媒体元数据、CDN 引用、排序和审核状态。
- `moments`：动态可见性、推荐开关、审核状态、挂载服务和计数。
- `comments`、`likes`、`favorites`、`follows`：互动关系；对目标唯一约束防重复。
- `articles`：资讯内容、分类、来源、发布和审核状态。

### 2.3 排期交易

- `provider_schedule_rules`、`schedule_overrides`、`provider_schedule_revisions`：每周规则、日期休息/临时开放覆盖和排期版本。
- `schedule_slots`：具体起止、可选服务、当前状态、最近预约状态、订单引用；排除同一 provider 时间重叠。
- `orders`：用户/服务者/服务、服务快照、时间地点、金额、实付/退款/佣金/收入、订单状态和邀请快照。
- `order_status_logs`：状态转换、操作者、原因、版本和 trace。
- `order_checkins`：打卡人、类型、时间、坐标、精度和结果；对普通用户返回脱敏位置。
- `payments`、`payment_callbacks`、`refunds`：渠道单号、金额、状态、验签结果、回调原文和幂等键。

### 2.4 账务奖励

- `wallet_accounts`：订单余额账户；服务者收入和推广收益使用 `earning_accounts`，包含 `PROVIDER_INCOME`、`REFERRAL_REWARD` 类型。
- `wallet_transactions`：不可变双向流水，`business_type + biz_no + idempotency_key` 唯一。
- `withdrawals`：提现单、账户快照密文、费用、税费、渠道、审核和打款结果。
- `referral_attributions`：邀请人、被邀请人、渠道、设备/风险信息；被邀请人唯一。
- `referral_reward_policies`：万分比、基数、上限、资金来源、范围、生效区间、审批。
- `order_referral_snapshots`：订单支付时的归因、政策、比例和资金上限。
- `referral_rewards`：奖励计算、状态、可用/结算/取消/调整时间；订单唯一。
- `referral_reward_accounts`、`referral_reward_transactions`：收益余额和不可变流水。

### 2.5 消息运营安全

- `conversations`、`conversation_members`、`messages`：订单会话授权、消息类型、审核状态和第三方 ID。
- `notifications`、`notification_templates`、`notification_deliveries`：模板、渠道、发送记录和重试。
- `content_reports`、`appeals`、`blacklists`、`risk_events`：举报、申诉、黑名单和风险证据。
- `safety_alerts`、`trip_shares`、`emergency_contacts`：报警、行程和紧急联系人。
- `admin_users`、`admin_roles`、`admin_permissions`、`admin_operation_logs`：RBAC 和敏感操作审计。
- `app_configs` 或按域配置表：城市、类目、规则版本、协议版本、阈值。
- `outbox_events`、`inbox_messages`、`idempotency_records`、`task_runs`：可靠事件、消费幂等、请求幂等和任务执行记录。

## 3. 关键约束

### 3.1 用户与归因

- `users.phone_hash` 唯一；对外只返回 `public_id` 和脱敏手机号，完整手机号不保存为明文。
- `invite_code` 全局唯一。
- `referral_attributions.invitee_user_id` 唯一；`inviter_user_id <> invitee_user_id`。
- 同一第三方标识只能绑定一个用户；绑定/解绑留审计。
- `user_auths.auth_type + auth_identifier` 唯一；`verification_codes.idempotency_key` 和 `auth_tokens.token_hash` 唯一。
- 验证码消费必须同时满足未消费、未过期、未超尝试次数，并在数据库事务内更新 `consumed_at`。

### 3.2 服务与排期

- 服务 `service_no` 唯一；价格 `>= 0`，时长 `> 0`。
- `schedule_slots` 同一 provider 的 `tsrange(start_at,end_at)` 不得重叠；订单引用只能在有效订单状态存在。
- 一个 slot 同时只能被一个订单锁定；释放动作必须匹配当前订单。
- 时段状态只允许 `OPEN/CLOSED/LOCKED/BOOKED`；`last_booking_status` 保留最近预约结果，取消后时段重新开放但历史状态不清除。
- 排期版本只用于批量范围操作，时段版本只用于单时段和下单操作，不能互相替代。
- `order_schedule_slots` 按 `position` 保存订单锁定的连续小时单元；同一订单不能重复关联同一单元，同一位置不能重复。

### 3.3 订单与资金

- `order_no/payment_no/refund_no/transaction_no/reward_no/withdrawal_no` 唯一。
- `paid_amount >= 0`、`refunded_amount >= 0`、`refunded_amount <= paid_amount`。
- 金额守恒：当前 `platform_service_fee=0`，用户应付等于服务金额；`provider_income + platform_commission = paid_amount - refunded_amount`。
- `referral_rewards.order_id` 唯一；奖励金额 `>= 0` 且不超过确认后的政策上限。
- 支付渠道交易号唯一；退款渠道交易号唯一。

### 3.4 状态与历史

- 所有状态变更同时写日志，禁止只更新 `status`。
- 钱包流水、奖励流水、支付回调、配置版本、审计日志、认证结果禁止物理更新/删除。
- 软删除只用于用户内容/资料等业务删除；资金、合规证据和审计按保留策略归档。

## 4. 索引建议

- 用户：手机号哈希、`status`、`city_code`、`created_at`、`inviter_user_id`。
- 服务：`provider_id`、`category_id`、`status`、`price_amount`、`published_at`、地点/文本检索。
- 排期：`provider_id + start_at`、`service_id + start_at`、`locked_order_id`。
- 订单：`user_id + created_at`、`provider_id + status + scheduled_start_at`、`order_no`、`status + paid_at`。
- 支付/退款：订单、渠道交易号、状态、创建时间。
- 账务：账户、业务单号、幂等键、创建时间。
- 奖励：邀请人、订单、政策版本、状态、可用时间。
- 事件：未发布状态、事件类型、发生时间、重试次数。

## 5. 迁移规则

- `[DESIGN]` 所有结构变化必须生成 Django migration，并在 CI 中从空库和上一版本库分别迁移测试。
- `[DESIGN]` 旧迁移不修改；变更采用新迁移，破坏性变更先双写/兼容读再切换。
- `[DESIGN]` 部署顺序：先兼容列/索引，再切代码，再清理旧字段；回滚不删除业务数据。
- `[DESIGN]` 大表索引使用并发创建或维护窗口；迁移必须有锁影响评估。

## 6. 敏感数据和删除

- 手机号、身份证、人脸、银行卡、第三方 token 使用应用层信封加密；用于去重/风控的哈希与密文分开。
- 精确位置只在打卡/报警场景短期保存，普通查询返回模糊位置；保留期限由隐私策略确认。
- 聊天和合规证据按不少于 180 天留存；注销、删除、司法调取和备份清除流程必须有法务确认。
- 账户注销不能破坏历史订单、流水、审计的引用完整性；可匿名化展示字段，按合法依据保留必要密文/哈希。

## 7. 规则快照

- 服务下单保存 `service_snapshot_json`；订单保存价格、时长、地点、佣金、退款和奖励政策版本。
- 政策表只追加版本；历史订单和奖励永远引用快照，不用当前配置重算历史。
- 配置变更记录操作者、原因、审批、生效区间和前后值。

## 8. 资讯数据

- `[DESIGN]` `news_articles` 保存公开 UUID、来源、摘要、安全原文链接、来源署名、状态、版本和逻辑删除时间；外部文章用 `source_unique_key` 去重。
- `[DESIGN]` `news_article_categories/news_article_attachments/news_article_mounts` 分别保存有序分类、附件和服务者/服务/商家/链接卡片快照。
- `[DESIGN]` `news_article_events` 追加创建、编辑、审核、发布、下架、删除和同步审计；不覆盖历史。
- `[DESIGN]` `news_sources/news_sync_runs` 保存来源配置、同步筛选、计数、错误摘要和执行时间；同步错误不得保存密钥或完整凭据。
- `[DESIGN]` 所有资讯表和字段通过 Django `db_comment` 保存中文备注；外部正文和图片是否可长期保存必须遵循版权确认结果。

## 9. 搜索和热门搜索数据

- `[DESIGN]` `search_query_stats` 按 `search_date + normalized_keyword` 唯一聚合每日搜索次数，使用 `BIGINT` 计数，不保存用户、设备、IP 或精确请求时间。
- `[DESIGN]` `normalized_keyword` 保存兼容分解、去首尾空白、合并连续空白并忽略大小写后的搜索自然键；`display_keyword` 仅保存最近一次非敏感展示原文。
- `[DESIGN]` `search_trending_keywords.normalized_keyword` 唯一，作为自动热度与人工配置的合并键；`public_id` 对外返回，内部自增 ID 不暴露给客户端。
- `[DESIGN]` 热搜配置保存 `is_manual/display_status/manual_priority/hot_score/rank/version`；人工修改通过 `version` 乐观锁阻止并发覆盖，排名重算不得覆盖人工屏蔽状态。
- `[DESIGN]` 每日聚合唯一约束 `uniq_search_query_stat_date_keyword` 必须保留；并发首次写入通过数据库冲突处理实现幂等，不能依赖应用内存锁。
- `[DESIGN]` 热搜展示索引覆盖 `display_status + manual_priority + hot_score`；聚合查询索引覆盖 `search_date + search_count`。
- `[DESIGN]` 敏感搜索词在进入 `search_query_stats` 和人工热搜配置前过滤；数据库不保存用户原始搜索记录、搜索用户关联或可还原的搜索请求信息。
- `[DESIGN]` 热搜窗口和公式属于运行配置；如未来需要运营审计，应新增配置版本/审计表，不修改历史聚合数据。

## 10. 地点搜索配置数据

- `[DESIGN]` `location_search_keywords` 保存快捷关键词代码、展示名称、地图搜索词、图标、排序、启用状态、乐观锁版本和创建幂等信息。
- `[DESIGN]` `location_search_rules` 保存 `ALLOW/DENY`、匹配范围、匹配词、原因、优先级和启用状态；拒绝规则优先于允许规则，未命中允许规则的 POI 不返回。
- `[DESIGN]` 两张表都使用 `public_id/code` 作为稳定业务标识；配置变更通过 `version` 防止并发覆盖，快捷关键词删除为逻辑停用。
- `[DESIGN]` 搜索结果和用户坐标不建立长期业务表；如后续必须审计搜索，应单独确认匿名化、保留期限和访问权限。
- `[DESIGN]` 订单地点后续应保存完整地址、经纬度、POI 标识、地点规则版本和必要快照；精确位置的权限脱敏和保留期限必须遵守安全与隐私规则。

## 11. 服务者当前位置和订单见面地点

- `[DESIGN]` `provider_location_states` 只保存服务者当前位置，坐标使用 `LOCATION_ENCRYPTION_KEY` 加密；普通用户当前位置不建立数据库记录。
- `[DESIGN]` 服务者位置保存模糊后的 GCJ02 坐标、精度、来源、隐私授权版本、有效期、撤销时间和乐观锁版本。
- `[DESIGN]` `orders` 保存 `meeting_location_*` 完整地址、经纬度、POI、来源和规则版本；该地点是订单履约快照，不是任何用户的实时位置。
- `[DESIGN]` 订单地点字段只允许订单参与人通过业务接口读取，不能由公开服务者资料或首页接口反向查询。
- `[DESIGN]` 服务者位置状态采用覆盖更新，不建立连续轨迹历史；撤销只标记时间，不删除必要审计状态。

## 12. 第三方身份和外部支付数据

- `[DESIGN]` `user_auths` 保存第三方稳定 subject/openid/unionid 的哈希或受控标识；手机号哈希、脱敏手机号和第三方绑定关系支持安全合并，但不覆盖历史认证记录。
- `[DESIGN]` `payments` 保存支付方式、渠道、最小货币单位金额、渠道交易号、客户端 SDK 参数、渠道状态、幂等键、请求指纹和乐观锁版本；`channel_transaction_no` 按渠道唯一。
- `[DESIGN]` `refunds` 保存原支付单、退款方式、最小货币单位金额、渠道退款号、退款状态、失败原因、幂等键和完成时间；不得用更新流水替代新增退款记录。
- `[DESIGN]` `order_refund_requests` 状态为 `PENDING/PROCESSING/REFUNDED/REJECTED/FAILED/CANCELED`，同一订单只允许一个 `PENDING` 或 `PROCESSING` 申请。
- `[DESIGN]` 外部支付/退款回调不新增可篡改的“成功标志”作为事实来源，必须由验签通知更新支付、退款和订单状态，并保留状态日志。

## 13. 订单实时聊天数据

- `[DESIGN]` `messaging_conversations` 保存用户—服务者共享会话事实、开放/只读/关闭状态、最后消息序号和会话版本；`pair_key` 使用 `customer:<user_id>:provider:<provider_user_id>` 并建立唯一约束，同一用户—服务者只允许一个规范会话。
- `[DESIGN]` `messaging_conversations.order` 保留创建会话时的首个订单并保持唯一，仅作历史兼容；它不代表会话只属于一个订单。
- `[DESIGN]` `messaging_conversation_order_links` 保存共享会话与多个聊天资格订单的来源关系，订单与关联记录一对一，支持支付成功、历史补齐和新订单幂等复用。
- `[DESIGN]` `messaging_conversation_members` 保存共享会话双方成员、角色、已读序号、未读计数、加入/离开状态和 `hidden_at`；用户与会话建立唯一约束。`hidden_at` 只控制当前用户可见性，不物理删除会话或消息。
- `[DESIGN]` 旧的按订单创建的重复会话由兼容服务合并到规范共享会话：迁移消息和订单关联，并隐藏旧重复成员记录；不得删除历史消息或订单事实。
- `[DESIGN]` `messaging_messages` 保存消息事实、发送者、类型、正文或媒体引用、服务端递增序号、幂等 ID、撤回状态和时间；会话内序号唯一，用户消息按 `conversation + sender + client_message_id` 唯一，系统消息按 `conversation + client_message_id` 唯一。
- `[DESIGN]` 订单支付成功系统消息使用 `sender=NULL` 和确定性标识 `system:order-paid:<order_no>`，数据库约束保证支付回调、余额支付和历史补齐重复执行时不会生成第二条提示。
- `[DESIGN]` `messaging_connection_tickets` 只保存一次性 WebSocket 凭证哈希、绑定用户、过期时间、消费时间和请求摘要；不保存明文票据、Access Token 或消息正文。
- `[DESIGN]` `messaging_message_deliveries` 是消息实时投递 Outbox，按事件 ID、消费者和消息建立幂等记录；Redis Channel Layer 只负责转发，失败由 Celery 重试，不能成为消息事实来源。
- `[DESIGN]` 消息正文按项目安全策略保护；日志、审计和错误详情不得记录消息正文。媒体引用必须可追溯到 `media_assets` 的发送者、用途和访问策略。
- `[DESIGN]` 会话关闭、订单取消/退款和完成后的配置化发送窗口（`MESSAGING_COMPLETED_SEND_WINDOW_DAYS`，默认 7 天）只改变可发送状态，不覆盖或物理删除历史消息；180 天留存、匿名化和删除必须由法务确认后执行。
- `[DESIGN]` 关键查询索引覆盖配对键、订单到共享会话、会话成员可见性、消息序号、幂等键、未读汇总和 Outbox 待投递状态；所有结构变化必须通过 Django 迁移。

## 14. 分享推广数据

- `[DESIGN]` `referral_invite_codes` 保存用户唯一邀请码和启停状态；邀请码不包含用户内部主键。
- `[DESIGN]` `referral_share_links` 保存邀请人按渠道/活动生成的分享链接、幂等键和一致性摘要；同一用户和幂等键唯一。
- `[DESIGN]` `referral_visits` 只保存分享链接、访问者/IP/User-Agent 的不可逆摘要和转化用户，不保存明文 IP、设备号或完整 User-Agent。
- `[DESIGN]` `referral_attributions` 保存被邀请用户、直接邀请人、邀请码、来源链接、注册渠道、风险状态和绑定时间；`invitee_user` 唯一并禁止自邀请。
- `[DESIGN]` `referral_policies` 是不可变政策版本，保存万分比、单笔上限、最低订单金额、资金来源限制和结算延迟；历史订单引用原政策，不读取最新政策重算。
- `[DESIGN]` `order_referral_snapshots` 与订单一对一，锁定支付时归因和政策，保存实付、累计退款、奖励基数、比例和预期金额。
- `[DESIGN]` `referral_rewards` 与奖励快照一对一，保存当前基数、金额、状态、结算时间、收益业务号和乐观锁版本。
- `[DESIGN]` `referral_reward_adjustments` 保存退款重算、人工更正和已结算追回的正负变化量，按奖励和幂等键唯一，不覆盖原奖励。
- `[DESIGN]` `referral_reward_status_logs` 保存奖励状态变化、原因、管理员和 trace_id。资金变化仍以 `earning_accounts/earning_transactions` 为最终账务事实。
- `[DESIGN]` 关键唯一约束覆盖邀请码、用户邀请码、分享幂等键、归因被邀请人、订单快照、奖励快照和奖励调整幂等键；所有结构变化必须通过 Django 迁移。
- `[DESIGN]` `orders.platform_commission_amount_minor` 保存服务者佣金快照，单位为分；当前由 `PROVIDER_PLATFORM_COMMISSION_RATE_BPS=1000` 计算为 10%，不增加用户应付金额。

## 15. 实名认证与服务者证件资料

- `[DESIGN]` `provider_applications` 新增身份证正反面媒体 UUID；只引用本人上传且用途正确的 `IDENTITY_CARD_FRONT/IDENTITY_CARD_BACK` 媒体。
- `[DESIGN]` `identity_verifications` 新增真实姓名密文、身份证号密文、身份证 HMAC 和正反面媒体 UUID；`user + verification_type` 仍保持唯一。
- `[DESIGN]` 姓名和身份证号不保存明文，身份证 HMAC 仅用于受控查重；日志、错误详情、OpenAPI 示例和管理列表不得返回明文。
- `[DESIGN]` 证件媒体仍保存在 `media_assets`，业务表只保存媒体 UUID；后续对象存储、访问签名和删除策略由媒体模块统一管理。
- `[DESIGN]` `provider_applications` 新增紧急联系人姓名密文、手机号密文和脱敏手机号；不保存完整手机号明文，接口和日志只使用脱敏展示值。


## 16. 优惠券和会员数据

- `[DESIGN]` `coupon_templates` 保存固定金额、门槛、适用范围、有效期类型、发放限额和模板状态；模板规则变化不覆盖历史用户券。
- `[DESIGN]` `coupon_instances` 保存用户券实例、来源幂等键、有效期和领取时模板快照；`coupon_redemptions` 保存订单锁定、核销、释放和金额快照，同一订单或同一券不能重复存在活动核销。
- `[DESIGN]` `coupon_status_logs` 追加式记录领取、锁定、核销、释放、过期、撤销和订单退款影响，不物理删除历史。
- `[DESIGN]` `membership_plans` 和 `membership_plan_versions` 保存套餐当前配置与不可变价格/时长/权益版本，购买单引用版本快照。
- `[DESIGN]` `membership_purchases` 保存会员购买幂等、支付业务单号和金额；`membership_periods` 保存购买后的有效期周期，`membership_accounts` 只作为当前到期时间和续费并发锁。
- `[DESIGN]` `membership_benefit_grants` 保存权益发放结果，包括会员券实例引用和未成功发放原因；`membership_status_logs` 保存购买、支付、生效、续费顺延和到期审计。
- `[DESIGN]` `payments` 新增 `business_type/business_no`，兼容既有 `order_no`；成功支付按业务主体唯一，会员购买支付禁止退款。
- `[DESIGN]` 金额字段继续使用 `BIGINT` 最小货币单位；所有新增表和字段必须有中文表备注、列备注、唯一约束和必要索引。
