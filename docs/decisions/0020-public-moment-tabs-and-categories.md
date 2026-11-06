# ADR 0020: 动态页筛选与动态类目

- 状态：Accepted
- 日期：2026-10-31
- 范围：公开动态页推荐、关注、附近 Tab 和动态类目配置

## 背景

前端动态页需要推荐、关注、附近和分类筛选。服务类目、服务标签和动态类目职责不同，当前也没有关注关系和真实位置数据。

## 决策

- `[PRD]` 动态页支持推荐、关注、附近和分类筛选。
- `[DESIGN]` 动态类目由 `moment_categories` 配置表提供，接口为 `/api/v1/moment-options/categories/`；动态保存独立 `category_code`。
- `[DESIGN]` `RECOMMENDED` 当前使用稳定 `NEWEST` 策略，只返回允许推荐的已发布公开动态。
- `[DESIGN]` `NEARBY` 当前使用 `city_code` 进行同城筛选，明确返回 `location_mode=CITY`、`distance_km=null`。
- `[DESIGN]` `FOLLOWING` 需要关注关系，当前返回空列表和 `available=false`，不伪造关注数据。
- `[DESIGN]` 动态邻居接口使用相同的 tab、类目、城市和关键词上下文，保证上下滑动不会跨筛选跳转。
- `[CONFIRM]` 关注关系、真实经纬度、附近距离、推荐算法、位置隐私和动态类目最终配置。

## 影响

- 前端类目导航从后端配置读取，后续运营调整不依赖客户端发版。
- 前端可以先展示推荐/同城，关注 Tab 可以显示未开放状态。

## 验证

- `tests/test_moments.py` 覆盖类目配置、推荐/同城/关注元信息和邻居筛选上下文。
- pytest、Ruff、Django check、迁移检查和 OpenAPI 校验作为提交门槛。
