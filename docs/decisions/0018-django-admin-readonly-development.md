# ADR 0018: 开发期 Django Admin 只读查看

- 状态：Accepted
- 日期：2026-10-30
- 范围：开发环境 Django Admin、管理员账号创建和业务后台安全边界

## 背景

开发者需要快速查看用户、服务者申请、服务、动态、媒体和配置数据。现有 API 管理接口已经具备业务状态控制，Django Admin 只作为开发查看入口。

## 决策

- `[DESIGN]` 启用 Django Admin 的 `/admin/` 路由、会话、消息和管理日志依赖。
- `[DESIGN]` 登录用户名使用完整手机号，后台表单在认证时转换为手机号 HMAC；管理命令 `create_admin_user` 创建或提升开发管理员账号。
- `[DESIGN]` 当前业务模型后台默认只读，禁止直接添加、修改、删除，状态修改继续通过业务服务和 API 执行。
- `[DESIGN]` 管理员密码通过命令创建，不提交 Git、镜像或日志；账号具备 `is_staff` 和活动状态。
- `[DESIGN]` 生产环境启用前必须替换为独立管理员账号、MFA、RBAC、IP 限制、敏感字段展示策略和操作审计。
- `[CONFIRM]` 生产 Admin 启用范围、管理员权限矩阵、二次确认、敏感字段和审计留存。

## 影响

- 不改变现有 Bearer Token API 和业务数据语义。
- 新增 Django 会话和管理日志数据表。
- 开发者可以登录后台查看数据，但不能从后台绕过动态、服务、申请和资金业务规则。

## 验证

- `tests/test_admin.py` 验证手机号登录和后台首页可访问。
- Django check、迁移检查、Ruff、pytest 和 OpenAPI 校验作为提交门槛。
