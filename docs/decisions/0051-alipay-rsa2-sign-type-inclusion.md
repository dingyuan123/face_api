# 0051. 支付宝 RSA2 请求签名包含 sign_type

- 日期：2026-11-21
- 状态：已实施

## 背景

支付宝 App 支付和交易查询在支付宝网关返回 `isv.invalid-signature`，但后端密钥已能正常解析，且订单串包含 `app_id`、`method`、`sign_type` 和 `sign`。

## 决定

- `[DESIGN]` 支付宝 RSA2 请求待签名字符串使用参数名字典序排序，排除 `sign`，但保留 `sign_type=RSA2`。
- `[DESIGN]` 这与支付宝官方 Python SDK 的 `get_sign_content` 和 `DefaultAlipayClient` 请求签名行为保持一致。
- `[DESIGN]` 支付宝异步通知验签继续排除 `sign` 和 `sign_type`，不改变通知验签语义。
- `[DESIGN]` 增加回归测试验证订单串签名可由对应 RSA2 公钥验签，避免再次回归。

## 影响

- 修复后支付宝查询返回正常的 `ACQ.TRADE_NOT_EXIST` 业务结果，说明请求签名已经被支付宝接受。
- 前端需重新请求支付，使用新的 `order_string`；旧订单串可能仍使用旧签名。
