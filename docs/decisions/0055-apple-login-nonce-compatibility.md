# 0055. UniApp Apple 登录 nonce 兼容

- 日期：2026-11-24
- 状态：已实施

## 背景

UniApp X 内置 Apple 登录 SDK 不支持向 Apple 请求写入自定义 nonce，因此返回的 `identity_token` 不包含 `nonce` claim。后端原实现把 nonce 作为必填 claim，导致 Apple 登录无法联调；同时异常类名不存在，认证错误被错误升级为 500。

## 决定

- `[PRD]` 先按客户端兼容方案联调 Apple 登录，不要求当前 UniApp X SDK 在 token 中返回 nonce。
- `[DESIGN]` Apple token 仍必须通过 JWKS 签名、`iss`、`aud=APPLE_CLIENT_ID`、`iat`、`exp` 和 `sub` 校验。
- `[DESIGN]` 请求体继续接收客户端生成的 nonce；token 包含 nonce 时必须校验原文或 SHA-256 值，缺少 nonce 时记录兼容审计后接受。
- `[DESIGN]` 修复 PyJWT 异常捕获，缺少 claim 或凭据无效统一返回 `AUTH_OAUTH_INVALID`，不再产生 500。
- `[CONFIRM]` 后续自研原生 Apple 登录模块或 SDK 支持 nonce 后，恢复严格 nonce 防重放校验。

## 影响

- 降低当前 Apple 登录的 nonce 防重放强度，但保留 Apple 签名、签发方、受众、时效和用户标识校验。
- 不改变手机号登录、Apple 账号合并和现有令牌签发逻辑。
