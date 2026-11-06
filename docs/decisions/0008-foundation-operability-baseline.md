# ADR 0008：工程基础与可运维性基线

- 状态：Accepted
- 日期：2026-10-28

## 背景

项目需要在不实现具体业务模块的前提下建立可持续开发、可验证、可部署的后端基础。

## 决策

- `[DESIGN]` 使用 Django 分层配置；开发配置禁止用于 `production`，生产配置对关键变量和默认密钥快速失败。
- `[DESIGN]` 基础测试使用 SQLite/locmem 隔离外部依赖；真实 PostgreSQL、Redis 和 Celery 行为由后续集成测试及 Docker Compose 验证。
- `[DESIGN]` 所有 API 使用统一成功/错误响应、稳定错误码和请求追踪 ID；日志为结构化 JSON，并对敏感键值和常见凭据格式脱敏。
- `[DESIGN]` 健康检查拆为 live 与 ready；ready 只公开布尔依赖状态，不泄露连接字符串或配置。
- `[DESIGN]` OpenAPI 由 `drf-spectacular` 从代码生成，接口提交前运行 schema 生成和自动化检查。
- `[DESIGN]` Celery 与 Redis 作为后续可靠异步任务基础设施；当前阶段仅提供配置和 Worker 入口，不实现业务任务。

## 后果

- 本地测试快速且可重复，但不能替代针对 PostgreSQL 约束、事务和 Redis 并发行为的集成测试。
- 基础接口保持最小化；认证、幂等、业务异常码等能力随业务模块按规范补充。
- Docker Compose 仅作为开发编排基线，不代表生产部署方案。
