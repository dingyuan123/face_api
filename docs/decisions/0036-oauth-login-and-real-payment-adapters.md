# 0036. Apple/微信登录与微信/支付宝 App 支付适配

## 状态

已确认并实施，真实商户资料和生产域名仍待接入验证。

## 背景

- `[PRD]` 登录和支付需要支持第三方账号与外部支付渠道，不能把第三方用户标识或支付状态信任为客户端提交值。
- `[PRD]` 当前阶段允许模拟/沙箱联调，不接入生产商户资金。
- `[CONFIRM]` 微信开放平台 App 已注册；微信支付商户、支付宝商户、Apple App/Services ID、回调域名和生产密钥仍由业务方提供。

## 决策

- `[DESIGN]` Apple 登录只接受 iOS App 的 `identity_token`，由服务端验证 Apple JWKS 签名、issuer、audience、时效和 nonce；nonce 同时兼容 SDK 原文和 SHA-256 形式。
- `[DESIGN]` 微信登录只支持 App 登录，由服务端使用临时 `code` 调用微信 OAuth2 换取 `openid/unionid`；客户端提交的 `state` 只用于会话关联，不能作为身份凭证。
- `[DESIGN]` 第三方登录没有手机号时返回 `requires_phone_binding=true`，用户通过六位短信验证码手动绑定。
- `[DESIGN]` 手机号已存在且目标账号没有第三方绑定时，仅允许将“无业务数据”的第三方空账号合并；已有资料、订单、钱包、动态等业务数据时返回 `AUTH_ACCOUNT_MERGE_CONFLICT`，不做隐式迁移。
- `[DESIGN]` 支付方式为 `BALANCE`、`WECHAT_APP`、`ALIPAY_APP`。余额支付在数据库事务内扣款；外部支付只创建 `PENDING` 支付单并返回 App SDK 参数，订单只有在验签回调成功后推进。
- `[DESIGN]` 微信支付使用 APIv3 App 下单、RSA 请求签名、APIv3 密钥 AES-GCM 回调解密和平台公钥验签；支付宝使用 App 支付、RSA2 请求签名和通知验签。
- `[DESIGN]` 外部退款按原支付渠道执行；退款先登记退款单，再在数据库事务外调用渠道，退款通知按 `refund_no` 幂等落账。余额退款记录钱包流水，外部退款保存渠道退款号和状态。
- `[DESIGN]` 开发 `PAYMENT_GATEWAY_MODE=MOCK` 只返回模拟客户端参数和模拟退款，不产生真实资金；生产禁止 Mock，并要求密钥从环境变量或密钥服务读取。

## 影响

- 账号合并、支付回调、退款回调、订单状态和资金流水均为高风险区域；重复请求、乱序回调和金额不一致必须拒绝或幂等返回。
- 真实联调前必须提供 App 包名/Bundle ID、AppID、商户号、APIv3 密钥、商户/平台证书或公钥、支付宝应用和密钥、HTTPS 回调地址。
