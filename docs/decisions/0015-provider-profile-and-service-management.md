# ADR 0015: 服务者资料与服务管理

- 状态：Accepted
- 日期：2026-10-30
- 范围：服务者资料、服务配置、服务草稿/审核/上下架和金额接口

## 背景

前端需要联调服务者资料管理、服务列表、创建/编辑服务、审核和上下架。金额还涉及未来折扣、退款和财务对账，不能使用字符串或浮点数作为唯一事实。

## 决策

- `[PRD]` 服务者资料字段为昵称、签名、个人介绍、头像、照片墙、服务类目和服务者标签。
- `[PRD]` 服务字段为名称、类目、价格、时长、介绍、封面、图集、服务标签和公共场所地点类型。
- `[DESIGN]` 新增 `providers` 服务者资料模型和 `catalog` 服务配置/服务模型；服务者资料昵称 1 到 20，服务者间忽略大小写唯一。
- `[DESIGN]` 服务者资料头像为空时回退展示最近一次服务者申请头像；资料可以复用申请阶段头像和生活照，保存专用资料媒体后覆盖回退值。
- `[DESIGN]` 服务价格保存 `currency + amount_minor` 整数金额，CNY 单位为分；`price_display` 只读生成，不接受字符串作为唯一金额来源。
- `[DESIGN]` 未来折扣使用整数比例/基点、明确舍入规则，并在订单/活动快照保存原价、折扣、应付金额和政策版本；服务当前只保存基础价格。
- `[DESIGN]` 服务状态为 DRAFT/PENDING/APPROVED/REJECTED/ONLINE/OFFLINE；创建默认 DRAFT，只有 DRAFT/REJECTED 可编辑和逻辑删除，DRAFT/REJECTED 可提交审核，APPROVED/OFFLINE 可上架，ONLINE 可下架。
- `[DESIGN]` 服务创建支持 `Idempotency-Key`；修改、状态转换、审核和删除使用 `expected_version`，并记录追加式服务事件。
- `[DESIGN]` `sold_count` 只读，后续由订单完成事件维护；前端不能提交销售数量。
- `[DESIGN]` 服务类目、服务标签、服务者标签均由配置表提供，首批数据通过种子迁移写入，不在客户端硬编码。
- `[CONFIRM]` 服务介绍长度、审核 SLA、APPROVED 后编辑策略、删除保留、活动折扣和优惠券价格快照。

## 影响

- 前端可以使用 `price_display` 展示金额，同时用 `amount_minor` 参与后端计算。
- 服务状态机、版本和事件为后续订单、支付、退款、佣金和对账保留可靠价格/状态快照边界。
- 未完成真实订单前，`sold_count` 保持只读默认值，不伪造业务数据。

## 验证

- `tests/test_provider_services.py` 覆盖资料、配置、金额、创建幂等、状态转换、版本冲突、删除和权限。
- `tests/test_documentation.py` 检查模型备注、业务模块说明和接口参数说明。
- pytest、Ruff、Django check、迁移检查、OpenAPI 校验和 PostgreSQL 备注检查作为提交门槛。
