# ADR-0002：采用 Django + Django REST Framework

- 状态：提议（待项目负责人确认）
- 日期：2026-10-27
- 决策人：待项目负责人确认 `[CONFIRM]`

## 背景

需求包含复杂 ORM、迁移、权限、后台、审计、API 文档、资金事务和长期维护。README 只有 FastAPI 备忘，没有现有实现可迁移。

## 决策

- `[DESIGN]` 使用 Python + Django + DRF + PostgreSQL + Redis + Celery + pytest + Ruff + Docker Compose。
- `[DESIGN]` 使用 `drf-spectacular` 维护 OpenAPI；Django Admin 仅作为内部运营起点，敏感运营能力通过自建 RBAC/API。
- `[DESIGN]` 如果后续团队已有 FastAPI 标准，可单独评估适配层或迁移，不在本阶段切换。

## 备选方案

- FastAPI + SQLAlchemy/Alembic：轻量、异步友好，但需要自建后台、迁移、权限和运营工具。
- Flask：灵活但需要组合更多基础设施，资金/审计一致性成本更高。

## 影响

- 统一 ORM、迁移、事务、权限、序列化和测试入口。
- 需要严格分层，避免 Django 视图/模型承担所有业务。

## 风险与缓解

- 风险：Django Admin 绕过业务规则。缓解：后台命令走应用服务，权限和审计强制。
- 风险：同步 ORM 不适合高并发 I/O。缓解：关键 I/O 放 Celery/适配器，按压测优化。

## 验证

- 项目骨架、迁移、API、权限、测试和 OpenAPI 基线。

