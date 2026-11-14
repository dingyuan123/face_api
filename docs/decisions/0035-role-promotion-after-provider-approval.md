# ADR 0035：服务者审核通过后的角色提升

- 状态：已确认
- 日期：2026-11-07
- 决策人：产品、前端和后端共同确认

## 背景

用户首次选择普通用户后，可以继续提交服务者申请。审核通过后旧接口仍返回 `primary_role=USER`，前端误判用户没有服务者身份。

## 决策

- `[PRD]` 首次身份选择仍然一次性完成，用户不能通过该接口直接切换身份。
- `[DESIGN]` 新增 `initial_role` 保存首次选择；`primary_role` 语义调整为当前主身份。
- `[DESIGN]` 服务者审核通过后，同一事务内将 `primary_role` 更新为 `PROVIDER`，`default_workspace` 更新为 `PROVIDER_WORKSPACE`。
- `[DESIGN]` 会话响应新增 `current_role` 和 `roles`；服务者用户返回 `USER + PROVIDER`，继续保留普通用户能力。
- `[DESIGN]` 服务者申请被拒绝或未通过时不改变普通用户主身份。

## 影响

- 前端可通过 `current_role/default_workspace` 稳定判断工作区。
- 历史首次身份仍可追溯，不受服务者审核通过影响。

## 验证

- 自动化测试覆盖首次选择幂等、审核后角色提升、双角色列表和审核拒绝不提升。
- 迁移为已有用户回填 `initial_role`，不修改历史主身份。
