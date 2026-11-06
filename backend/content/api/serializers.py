from __future__ import annotations

from rest_framework import serializers

from backend.catalog.api.serializers import ServiceResponseSerializer
from backend.media.api.serializers import MediaAssetSummarySerializer


class MomentTagResponseSerializer(serializers.Serializer):
    """动态标签配置。"""

    code = serializers.CharField(help_text="动态标签稳定代码")
    name = serializers.CharField(help_text="动态标签展示名称")
    category = serializers.CharField(help_text="动态标签分类")
    sort_order = serializers.IntegerField(help_text="标签展示排序值")


class MomentCategoryResponseSerializer(serializers.Serializer):
    """动态内容类目配置。"""

    code = serializers.CharField(help_text="动态类目稳定代码")
    name = serializers.CharField(help_text="动态类目展示名称")
    sort_order = serializers.IntegerField(help_text="类目展示排序值")


class MomentInputSerializer(serializers.Serializer):
    """图文动态创建请求。"""

    type = serializers.CharField(
        default="IMAGE_TEXT",
        help_text="动态类型，当前仅支持 IMAGE_TEXT",
    )
    category_code = serializers.CharField(help_text="动态内容类目稳定代码")
    content = serializers.CharField(help_text="动态文案，最多 2000 个字符")
    cover_media_id = serializers.CharField(
        required=False,
        allow_null=True,
        help_text="封面媒体 ID；省略时使用第一张动态图片",
    )
    media_ids = serializers.ListField(
        child=serializers.CharField(),
        allow_empty=False,
        help_text="动态图片媒体 ID，1 到 9 张",
    )
    visibility = serializers.CharField(
        default="PUBLIC", help_text="动态可见范围，当前仅支持 PUBLIC"
    )
    allow_recommend = serializers.BooleanField(
        default=True,
        help_text="是否允许平台推荐该动态",
    )
    attached_service_id = serializers.UUIDField(
        required=False,
        allow_null=True,
        help_text="可选挂载服务 UUID，只能挂载本人 ONLINE 服务",
    )
    tag_codes = serializers.ListField(
        child=serializers.CharField(),
        required=False,
        help_text="动态标签代码列表，最多 5 个",
    )


class MomentUpdateRequestSerializer(serializers.Serializer):
    """图文动态修改请求。"""

    expected_version = serializers.IntegerField(min_value=1, help_text="当前动态版本号")
    category_code = serializers.CharField(
        required=False,
        help_text="动态内容类目稳定代码",
    )
    type = serializers.CharField(
        required=False,
        help_text="动态类型，当前仅支持 IMAGE_TEXT",
    )
    content = serializers.CharField(required=False, help_text="动态文案，最多 2000 个字符")
    cover_media_id = serializers.CharField(
        required=False,
        allow_null=True,
        help_text="封面媒体 ID",
    )
    media_ids = serializers.ListField(
        child=serializers.CharField(),
        required=False,
        allow_empty=False,
        help_text="动态图片媒体 ID，1 到 9 张",
    )
    visibility = serializers.CharField(required=False, help_text="动态可见范围")
    allow_recommend = serializers.BooleanField(
        required=False,
        help_text="是否允许平台推荐该动态",
    )
    attached_service_id = serializers.UUIDField(
        required=False,
        allow_null=True,
        help_text="可选挂载服务 UUID",
    )
    tag_codes = serializers.ListField(
        child=serializers.CharField(),
        required=False,
        help_text="动态标签代码列表",
    )


class MomentProviderSerializer(serializers.Serializer):
    """动态发布者摘要。"""

    user_public_id = serializers.UUIDField(help_text="服务者对外用户标识")
    nickname = serializers.CharField(allow_null=True, help_text="服务者昵称")
    avatar_media = MediaAssetSummarySerializer(
        allow_null=True,
        help_text="服务者头像媒体摘要",
    )
    verification = serializers.DictField(help_text="服务者实名和人脸认证状态")


class MomentViewerStateSerializer(serializers.Serializer):
    """当前访问者与动态和作者的互动状态。"""

    is_liked = serializers.BooleanField(help_text="当前访问者是否已点赞该动态")
    is_favorited = serializers.BooleanField(help_text="当前访问者是否已收藏该动态")
    is_following = serializers.BooleanField(help_text="当前访问者是否已关注动态作者")


class MomentResponseSerializer(serializers.Serializer):
    """图文动态安全响应。"""

    id = serializers.UUIDField(help_text="动态 UUID")
    type = serializers.CharField(help_text="动态类型")
    category_code = serializers.CharField(allow_null=True, help_text="动态内容类目代码")
    content = serializers.CharField(help_text="动态文案")
    cover_media = MediaAssetSummarySerializer(allow_null=True, help_text="动态封面")
    media = MediaAssetSummarySerializer(many=True, help_text="动态媒体列表")
    visibility = serializers.CharField(help_text="动态可见范围")
    allow_recommend = serializers.BooleanField(help_text="是否允许推荐")
    status = serializers.CharField(help_text="动态状态")
    reject_reason = serializers.CharField(help_text="审核拒绝原因")
    provider = MomentProviderSerializer(help_text="动态发布者摘要")
    viewer_state = MomentViewerStateSerializer(help_text="当前访问者互动状态")
    attached_service = ServiceResponseSerializer(allow_null=True, help_text="可选挂载服务")
    tag_codes = serializers.ListField(child=serializers.CharField(), help_text="动态标签代码")
    like_count = serializers.IntegerField(help_text="点赞数")
    comment_count = serializers.IntegerField(help_text="评论数")
    share_count = serializers.IntegerField(help_text="分享数")
    view_count = serializers.IntegerField(help_text="浏览数")
    version = serializers.IntegerField(help_text="动态版本号")
    published_at = serializers.DateTimeField(allow_null=True, help_text="动态发布时间")
    updated_at = serializers.DateTimeField(help_text="动态最近更新时间")


class MomentFeedContextSerializer(serializers.Serializer):
    """动态上下滑动时使用的浏览上下文。"""

    tab = serializers.CharField(help_text="动态筛选标签：RECOMMENDED/FOLLOWING/NEARBY")
    keyword = serializers.CharField(help_text="动态关键词")
    category_code = serializers.CharField(help_text="动态类目代码")
    city_code = serializers.CharField(help_text="同城动态城市代码")
    sort = serializers.CharField(help_text="动态排序方式，当前支持 NEWEST")
    strategy = serializers.CharField(help_text="当前排序策略，推荐算法接入前为 NEWEST")
    location_mode = serializers.CharField(
        allow_null=True,
        help_text="位置模式；同城筛选为 CITY，其他情况为空",
    )


class MomentNeighborsResponseSerializer(serializers.Serializer):
    """当前动态及其前后相邻动态。"""

    current = MomentResponseSerializer(help_text="当前动态")
    previous = MomentResponseSerializer(
        allow_null=True,
        help_text="上一条动态；页面顶部边界时为空",
    )
    next = MomentResponseSerializer(
        allow_null=True,
        help_text="下一条动态；页面底部边界时为空",
    )
    has_previous = serializers.BooleanField(help_text="是否存在上一条动态")
    has_next = serializers.BooleanField(help_text="是否存在下一条动态")
    feed_context = MomentFeedContextSerializer(help_text="保持前后动态一致的筛选上下文")


class MomentListResponseSerializer(serializers.Serializer):
    """服务者动态管理列表响应。"""

    items = MomentResponseSerializer(many=True, help_text="动态列表")
    total = serializers.IntegerField(help_text="动态总数")
    page = serializers.IntegerField(help_text="当前页码")
    page_size = serializers.IntegerField(help_text="每页数量")


class MomentSummarySerializer(serializers.Serializer):
    """管理员动态状态汇总。"""

    total = serializers.IntegerField(help_text="全部未删除动态数量")
    draft = serializers.IntegerField(help_text="草稿数量")
    pending = serializers.IntegerField(help_text="审核中数量")
    published = serializers.IntegerField(help_text="已发布数量")
    rejected = serializers.IntegerField(help_text="审核拒绝数量")
    deleted = serializers.IntegerField(help_text="已删除数量")


class AdminMomentListResponseSerializer(serializers.Serializer):
    """管理员动态列表响应。"""

    items = MomentResponseSerializer(many=True, help_text="动态列表")
    total = serializers.IntegerField(help_text="筛选后的动态总数")
    page = serializers.IntegerField(help_text="当前页码")
    page_size = serializers.IntegerField(help_text="每页数量")
    summary = MomentSummarySerializer(help_text="全平台动态状态汇总")


class MomentExpectedVersionSerializer(serializers.Serializer):
    """动态状态操作请求。"""

    expected_version = serializers.IntegerField(min_value=1, help_text="当前动态版本号")


class MomentReviewRequestSerializer(serializers.Serializer):
    """管理员动态审核请求。"""

    expected_version = serializers.IntegerField(min_value=1, help_text="当前动态版本号")
    reason = serializers.CharField(
        required=False,
        allow_blank=True,
        help_text="拒绝原因；拒绝时必填，通过时可省略",
    )


class MountableServiceSerializer(serializers.Serializer):
    """动态可挂载服务摘要。"""

    id = serializers.UUIDField(help_text="服务 UUID")
    title = serializers.CharField(help_text="服务名称")
    category_code = serializers.CharField(help_text="服务类目代码")
    price = serializers.DictField(help_text="服务基础价格")
    price_display = serializers.CharField(help_text="只读金额展示字符串")
    duration_minutes = serializers.IntegerField(help_text="服务时长")
    cover_media = MediaAssetSummarySerializer(allow_null=True, help_text="服务封面")
