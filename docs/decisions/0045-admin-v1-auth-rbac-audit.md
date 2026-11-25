# ADR-0045：Vue 管理后台认证、RBAC 和审计基础

- 状态：已接受
- 日期：2026-11-16
- 决策人：项目负责人

## 背景

- `/management/` 是开发测试会话后台，不适合作为 Vue 管理后台的 Token API。
- 原有管理接口依赖 `User.is_staff`，没有独立管理员令牌、权限点和统一审计查询。

## 决策

- `[DESIGN]` 新增 `/admin/v1/` 管理 API，使用独立 `AdminAuthToken`，支持登录、当前管理员、刷新和退出。
- `[DESIGN]` 登录支持开发测试图形验证码，忘记/重置密码使用独立 `PASSWORD_RESET` 短信验证码；生产短信和图形验证码必须接入真实服务后启用。
- `[DESIGN]` 新增 `AdminPermission/AdminRole/AdminRolePermission/AdminRoleMember`，权限点在后端逐接口校验。
- `[DESIGN]` 新增 `AdminOperationLog`，记录操作者、动作、目标、前后状态、原因、幂等键和 trace_id。
- `[DESIGN]` 首批提供后台总览、用户列表/详情/封禁/解封、服务者列表/详情/停用/恢复、权限和角色成员管理。
- `[DESIGN]` 后台首页提供概览、7/30 天趋势和待处理预览；角色支持创建、修改、删除和权限点替换，`SUPER_ADMIN` 不允许删除或修改。
- `[DESIGN]` 财务模块提供支付、退款、平台佣金、服务者收入和提现汇总，支持合并流水查询、CSV 导出和佣金概览/趋势/订单明细。
- `[DESIGN]` 平台分析提供用户、服务者、服务、订单、内容、收入概览、趋势和城市/类目/服务者/支付渠道分组；基础设置和公告由管理后台维护。
- `[DESIGN]` 退款审核允许管理员按不超过申请金额的部分金额退款；部分退款不关闭订单，全额退款才释放预约时段。提现审核、财务对账和 CSV 导出纳入管理后台。
- `[DESIGN]` 用户和服务者状态写操作使用 `expected_version`，封禁/停用同时撤销现有登录令牌。

## 备选方案

- 继续复用 Django Admin 会话：无法满足 Vue Token 登录、权限点和 API 集成。
- 只依赖 `is_staff`：无法实现职责分离和最小权限。
- 直接改数据库状态：缺少审计、幂等和并发保护。

## 影响

- `accounts.User` 新增账号管理版本号。
- `/admin/v1/auth/*`、`/admin/v1/dashboard/overview/`、`/admin/v1/users/*`、`/admin/v1/providers/*`、`/admin/v1/audit-logs/` 和 RBAC 查询接口已建立。
- 现有 `/api/v1/admin/*` 业务审核接口继续兼容，后续逐步统一到 `/admin/v1/` 或增加代理入口。

## 风险与缓解

- 密码登录和验证码策略仍需生产安全评审；当前管理员必须是 `is_staff + ACTIVE`。
- 存量 `is_staff` 用户首次登录自动初始化 `SUPER_ADMIN`，后续应通过角色成员接口收敛权限。
- 管理写操作审计已覆盖用户和服务者状态，其他业务写操作需继续接入统一审计。

## 验证

- 测试覆盖管理员登录、权限、总览、用户封禁/解封、服务者停用/恢复和审计记录。
- 运行 Django check、迁移检查、完整 pytest、Ruff 和 OpenAPI。
