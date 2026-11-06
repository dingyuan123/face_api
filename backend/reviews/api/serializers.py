from __future__ import annotations

from rest_framework import serializers

from backend.media.api.serializers import MediaAssetSummarySerializer


class ReviewServiceSummarySerializer(serializers.Serializer):
    """评价关联服务的展示摘要。"""

    id = serializers.CharField(allow_null=True, help_text="服务公开标识")
    title = serializers.CharField(help_text="服务名称")
    category_code = serializers.CharField(
        allow_null=True,
        help_text="服务类目稳定代码",
    )
    price = serializers.DictField(help_text="下单时每小时价格，包含币种、最小单位和展示值")
    duration_minutes = serializers.IntegerField(
        allow_null=True,
        help_text="下单时服务时长，单位为分钟",
    )
    introduction = serializers.CharField(help_text="下单时服务介绍摘要")
    cover_media = MediaAssetSummarySerializer(
        allow_null=True,
        help_text="服务封面短期展示地址",
    )


class ReviewUserSummarySerializer(serializers.Serializer):
    """评价用户的公开资料摘要，匿名评价返回空值。"""

    public_id = serializers.UUIDField(help_text="用户公开 UUID")
    nickname = serializers.CharField(allow_null=True, help_text="用户昵称")
    avatar_media = MediaAssetSummarySerializer(
        allow_null=True,
        help_text="用户头像短期展示地址",
    )


class ReviewProviderVerificationSerializer(serializers.Serializer):
    """服务者对外认证状态摘要。"""

    real_name_status = serializers.CharField(help_text="实名认证状态")
    face_status = serializers.CharField(help_text="人脸认证状态")


class ReviewProviderRatingSerializer(serializers.Serializer):
    """服务者评分汇总。"""

    rating_average = serializers.CharField(help_text="平均评分，保留两位小数")
    review_count = serializers.IntegerField(help_text="有效评价数量")


class ReviewProviderSummarySerializer(ReviewUserSummarySerializer):
    """待评价和已评价服务者公开资料摘要。"""

    verification = ReviewProviderVerificationSerializer(help_text="实名和人脸认证状态")
    rating = ReviewProviderRatingSerializer(help_text="服务者评分")
    completed_order_count = serializers.IntegerField(help_text="已完成订单数量")


class ReviewReplySummarySerializer(serializers.Serializer):
    """服务者评价回复摘要。"""

    id = serializers.IntegerField(help_text="回复记录 ID")
    content = serializers.CharField(help_text="回复内容")
    created_at = serializers.DateTimeField(help_text="回复时间")


class ReviewRequestSerializer(serializers.Serializer):
    """用户订单评价请求。"""

    rating = serializers.IntegerField(help_text="评分，1 到 5")
    content = serializers.CharField(required=False, allow_blank=True, help_text="评价文字内容")
    tag_codes = serializers.ListField(
        child=serializers.CharField(),
        required=False,
        help_text="评价标签代码，最多 5 个",
    )
    is_anonymous = serializers.BooleanField(default=False, help_text="是否匿名展示")


class ReviewResponseSerializer(serializers.Serializer):
    """用户评价响应。"""

    id = serializers.UUIDField(help_text="评价 UUID")
    order_no = serializers.UUIDField(help_text="关联订单 UUID")
    rating = serializers.IntegerField(help_text="评分")
    content = serializers.CharField(help_text="评价内容")
    is_anonymous = serializers.BooleanField(help_text="是否匿名")
    tag_codes = serializers.ListField(child=serializers.CharField(), help_text="评价标签")
    provider_public_id = serializers.UUIDField(help_text="服务者用户 UUID")
    service = ReviewServiceSummarySerializer(allow_null=True, help_text="评价服务摘要")
    provider = ReviewProviderSummarySerializer(help_text="服务者公开资料摘要")
    user_public_id = serializers.UUIDField(
        allow_null=True,
        help_text="评价用户 UUID；匿名评价不返回",
    )
    user = ReviewUserSummarySerializer(
        allow_null=True,
        help_text="评价用户昵称和头像；匿名评价返回 null",
    )
    reply = ReviewReplySummarySerializer(allow_null=True, help_text="服务者回复")
    has_reply = serializers.BooleanField(help_text="是否已经回复")
    review_expires_at = serializers.DateTimeField(help_text="评价截止时间")
    created_at = serializers.DateTimeField(help_text="评价创建时间")
    updated_at = serializers.DateTimeField(help_text="评价最近更新时间")


class ReviewReplyRequestSerializer(serializers.Serializer):
    """服务者评价回复请求。"""

    content = serializers.CharField(help_text="回复内容，1 到 500 个字符")


class ReviewReplyResponseSerializer(serializers.Serializer):
    """评价回复响应。"""

    review_id = serializers.UUIDField(help_text="评价 UUID")
    reply_id = serializers.IntegerField(help_text="回复记录 ID")
    content = serializers.CharField(help_text="回复内容")
    created_at = serializers.DateTimeField(help_text="回复创建时间")


class ReviewTagResponseSerializer(serializers.Serializer):
    """评价标签配置。"""

    code = serializers.CharField(help_text="评价标签稳定代码")
    name = serializers.CharField(help_text="评价标签展示名称")
    category = serializers.CharField(help_text="评价标签分类")
    sort_order = serializers.IntegerField(help_text="标签展示排序值")


class MyReviewItemSerializer(serializers.Serializer):
    """我的评价页单项，包含待评价订单或已评价记录。"""

    item_type = serializers.ChoiceField(
        choices=["PENDING_REVIEW", "REVIEWED"],
        help_text="条目类型：待评价或已评价",
    )
    status = serializers.ChoiceField(
        choices=["PENDING", "REVIEWED"],
        help_text="评价状态",
    )
    order_no = serializers.UUIDField(help_text="订单 UUID")
    service = ReviewServiceSummarySerializer(allow_null=True, help_text="订单服务摘要")
    provider = ReviewProviderSummarySerializer(
        allow_null=True,
        help_text="服务项目所属服务者摘要",
    )
    review = ReviewResponseSerializer(allow_null=True, help_text="已评价记录")
    review_deadline = serializers.DateTimeField(
        allow_null=True,
        help_text="评价截止时间",
    )
    created_at = serializers.DateTimeField(help_text="订单完成或评价创建时间")


class ReviewListSummarySerializer(serializers.Serializer):
    """我的评价列表统计。"""

    pending_count = serializers.IntegerField(help_text="待评价数量")
    reviewed_count = serializers.IntegerField(help_text="已评价数量")


class MyReviewListResponseSerializer(serializers.Serializer):
    """我的评价页列表响应。"""

    items = MyReviewItemSerializer(many=True, help_text="待评价和已评价列表")
    total = serializers.IntegerField(help_text="筛选后条目总数")
    page = serializers.IntegerField(help_text="当前页码")
    page_size = serializers.IntegerField(help_text="每页数量")
    summary = ReviewListSummarySerializer(help_text="评价数量汇总")


class ProviderReviewSummarySerializer(serializers.Serializer):
    """服务者评价管理评分汇总。"""

    average_rating = serializers.CharField(help_text="平均评分，保留两位小数")
    review_count = serializers.IntegerField(help_text="评价总数")
    reply_count = serializers.IntegerField(help_text="已回复评价数量")
    reply_rate = serializers.CharField(help_text="回复率，保留两位小数")
    rating_distribution = serializers.DictField(help_text="1 到 5 星评价数量")


class ProviderReviewListResponseSerializer(serializers.Serializer):
    """服务者评价管理列表响应。"""

    items = ReviewResponseSerializer(many=True, help_text="服务者收到的评价")
    total = serializers.IntegerField(help_text="筛选后评价总数")
    page = serializers.IntegerField(help_text="当前页码")
    page_size = serializers.IntegerField(help_text="每页数量")
    summary = ProviderReviewSummarySerializer(help_text="评分和回复率汇总")
