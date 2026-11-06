# ADR 0019: 动态详情上下滑动导航

- 状态：Accepted
- 日期：2026-10-31
- 范围：动态详情前后切换、浏览上下文和稳定排序

## 背景

前端动态详情需要上下滑动切换内容。直接进入详情时缺少原列表上下文，推荐排序变化还可能导致用户看到重复或跳过动态。

## 决策

- `[PRD]` 动态详情支持上下滑动查看上一条和下一条动态。
- `[DESIGN]` `GET /api/v1/moments/{moment_id}/neighbors/` 返回 `current/previous/next/has_previous/has_next/feed_context`。
- `[DESIGN]` 动态顺序固定为 `published_at DESC, public_id DESC`；当前只支持 `sort=NEWEST`。
- `[DESIGN]` 筛选上下文保持 `keyword/category_code/sort`，相邻动态只在相同筛选范围内计算。
- `[DESIGN]` 前端从列表进入详情时优先使用已有列表顺序和游标翻页；直接进入详情时使用 neighbors，并在边界加载更多列表。
- `[DESIGN]` 只有 `PUBLISHED + PUBLIC` 动态进入导航；草稿、拒绝、私密和删除动态不返回。
- `[DESIGN]` 推荐、关注、附近和距离模式后续需要固定会话排序或提供导航游标，不能简单按实时热度重排。
- `[CONFIRM]` 推荐模式、视频播放、相关推荐和跨页面保存浏览上下文。

## 影响

- 前端可以实现稳定的全屏上下滑动，不需要把完整动态列表写入详情接口。
- 直接分享链接也能恢复同筛选条件下的前后动态。

## 验证

- `tests/test_moments.py` 覆盖前后顺序、首尾边界、筛选上下文和排序错误。
- pytest、Ruff、Django check、迁移检查和 OpenAPI 校验作为提交门槛。
