# ADR 0024: 服务按小时计价和下单前报价

- 状态：Accepted
- 日期：2026-11-02
- 范围：服务价格语义、订单金额试算和营销扩展边界

## 背景

服务允许不同时长，价格需要在下单前向用户明确展示。金额计算必须支持后续优惠券、活动、会员和平台费用，但当前阶段没有优惠活动。

## 决策

- `[DESIGN]` `ProviderService.price_amount_minor` 表示每小时价格，不表示固定总价。
- `[DESIGN]` 服务时长必须是 60 分钟倍数，订单原价等于每小时价格乘以预约小时数。
- `[DESIGN]` `POST /api/v1/orders/quotes/` 返回小时单价、小时数、原价、优惠、平台费、应付金额、明细和服务/时段版本。
- `[DESIGN]` 当前折扣和平台服务费为 0，`discounts` 和 `breakdown` 保留后续营销扩展。
- `[DESIGN]` 下单时后端重新计算金额，不接受前端提交的最终金额；报价版本用于发现价格或时段变化。
- `[DESIGN]` 金额继续使用 `BIGINT` 最小货币单位，展示字符串只读且不参与计算。

## 影响

- 服务接口通过 `pricing_unit=HOUR` 明确每小时价格语义。
- 多小时订单总价随预约小时数变化，订单保存优惠前原价和最终应付金额。
- 后续优惠活动可以新增折扣明细而不改变基础计价模型。

## 验证

- `tests/test_booking_flow.py`、`tests/test_documentation.py`。
- pytest、Ruff、Django check、迁移检查和 OpenAPI 校验。
