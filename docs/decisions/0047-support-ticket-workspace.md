# ADR-0047：独立客服工单与客服工作台

- 状态：已接受
- 日期：2026-11-16
- 决策人：项目负责人

## 背景

- PRD 要求客服处理咨询、投诉、纠纷和退款问题。
- 现有订单 IM 只允许订单参与人通信，不能直接作为客服聊天使用。

## 决策

- `[DESIGN]` 新增 `SupportTicket/SupportMessage/SupportFAQ`，客服沟通使用独立工单消息。
- `[DESIGN]` 用户可创建工单、查看本人工单和追加消息；管理员可分配客服、回复、解决或关闭工单。
- `[DESIGN]` 工单支持分类、优先级、关联订单、状态、处理结论和版本控制。
- `[DESIGN]` 客服操作使用独立权限点并写统一 `AdminOperationLog`。
- `[DESIGN]` 第一阶段使用 HTTP 消息和序号增量读取，WebSocket 实时客服频道后续接入。

## 影响

- 用户接口：`/api/v1/support/tickets/`、`/api/v1/support/tickets/{ticket_no}/messages/`、`/api/v1/support/faqs/`。
- 管理接口：`/admin/v1/support/tickets/`、分配/回复/解决/关闭和常见问题管理。

## 风险与缓解

- 用户越权：工单详情和消息服务强制校验工单归属。
- 消息重复：使用工单内递增序号和 `client_message_id` 幂等。
- 客服误操作：状态修改使用 `expected_version`、处理结论和统一审计。

## 验证

- 自动化测试覆盖用户工单、消息幂等、管理员分配/回复/解决、FAQ 和权限。
