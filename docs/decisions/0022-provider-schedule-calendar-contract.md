# ADR 0022: 服务者排期日历接口契约与状态模型

- 状态：Accepted
- 日期：2026-11-02
- 范围：排期日历查询、时段状态、批量排期、规则修改和公开可预约接口

## 背景

前端排期管理页需要稳定解析月历、周历、单日时段和批量设置结果。原接口使用泛型响应、`revision` 与 `version` 语义不清晰，公开可预约接口还复用了管理端时段结构。

## 决策

- `[DESIGN]` 日历查询统一支持 `view=MONTH/WEEK/CUSTOM`、`date`、`date_from/date_to` 和 IANA `timezone`，默认时区为 `Asia/Shanghai`。
- `[DESIGN]` 日历、单日和批量响应使用明确的 OpenAPI 模型，并统一返回 `schedule_version`；单时段并发控制继续使用 `version`。
- `[DESIGN]` 时段当前状态为 `OPEN/CLOSED/LOCKED/BOOKED`。订单创建后为 `LOCKED`，支付成功后为 `BOOKED`；服务者只能切换 `OPEN` 与 `CLOSED`。
- `[DESIGN]` 订单取消或退款后时段恢复 `OPEN`，`last_booking_status=CANCELLED` 保留最近预约结果，符合 PRD 的取消释放语义。
- `[DESIGN]` 排期以服务者日历为主，新时段统一为不绑定服务的通用时段；历史服务绑定记录仅作兼容读取。
- `[DESIGN]` 周规则修改只影响后续生成，不自动重写已生成、已锁定或已预约时段；生成器不得创建与现有时段重叠的新时段。
- `[DESIGN]` 公开可预约接口只返回预约所需的最小服务和时段字段，保留 `slot_version` 作为下单乐观锁令牌，不返回订单号或管理字段。

## 影响

- 排期模型新增 `last_booking_status`，订单支付、取消、退款和完成同步维护预约状态。
- 批量操作会返回成功、打开、关闭、删除、保护性跳过和失败数量，并提供结构化 `warnings/errors`。
- 后续多人容量、跨日服务、节假日和真实时区策略仍按开放问题单独设计。

## 验证

- `tests/test_schedule_management.py`、`tests/test_booking_flow.py`、`tests/test_documentation.py`。
- pytest、Ruff、Django check、迁移检查、OpenAPI 校验和 PostgreSQL 中文备注检查。
