# ADR 0014: 用户个人资料与兴趣标签配置

- 状态：Accepted
- 日期：2026-10-29
- 范围：当前用户资料、兴趣标签、城市代码和安心用户等级预留

## 背景

前端“我的页面”需要查询和编辑头像、昵称、性别、年龄、城市、签名、兴趣标签，并显示“安心用户 lv2”等级信息。兴趣标签和城市不能只维护在前端。

## 决策

- `[PRD]` 年龄使用用户填写的 `age`，范围 18 到 40；性别只允许 `MALE/FEMALE`。
- `[PRD]` 昵称长度 1 到 30，忽略大小写唯一；签名最多 100 个字符；兴趣标签最多 5 个。
- `[DESIGN]` 新增 `user_profiles`、`profile_interest_tags`、`profile_city_options` 和 `user_profile_interests`。
- `[DESIGN]` 兴趣标签使用稳定 `code`，展示名称、分类、排序和启用状态可配置；首批种子数据可通过配置表维护。
- `[DESIGN]` 城市保存 `city_code`，首期提供 `LZ/泸州`，后续扩展城市配置。
- `[DESIGN]` 头像使用 `USER_PROFILE_AVATAR` 媒体和临时 `display_url`，不接收任意 URL。
- `[DESIGN]` 修改接口使用 `expected_version`，相同内容重复提交不增加版本；昵称唯一性由数据库约束兜底。
- `[DESIGN]` `trust_level_code`、`trust_level_name`、`trust_level_updated_at` 仅预留，本期不接受客户端写入等级。
- `[CONFIRM]` 安心用户等级维护规则、昵称/签名审核、公开资料范围和头像公开审核。

## 影响

- 前端可以从后端读取标签和城市选项，保存稳定代码。
- 昵称冲突、标签配置停用和版本冲突都有稳定错误码。
- 未来公开个人主页复用资料字段，但必须另外定义公开可见性和内容审核状态。

## 验证

- `tests/test_profiles.py` 覆盖查询、修改、标签、昵称、年龄、版本和头像所有权。
- `tests/test_documentation.py` 检查数据库备注、业务说明和接口参数说明。
- pytest、Ruff、Django check、迁移检查和 OpenAPI 校验作为提交门槛。
