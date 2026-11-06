from __future__ import annotations

from rest_framework import serializers

from backend.content.api.news_serializers import NewsArticleResponseSerializer
from backend.content.api.serializers import MomentResponseSerializer
from backend.media.api.serializers import MediaAssetSummarySerializer


class HomeProviderSerializer(serializers.Serializer):
    """首页卡片中的服务者资料。"""

    nickname = serializers.CharField(help_text="服务者昵称")
    age = serializers.IntegerField(allow_null=True, help_text="服务者年龄")
    gender = serializers.CharField(allow_null=True, help_text="服务者性别")
    city_code = serializers.CharField(allow_null=True, help_text="城市代码")
    signature = serializers.CharField(help_text="服务者签名")
    avatar_media = MediaAssetSummarySerializer(
        allow_null=True,
        help_text="服务者头像媒体摘要",
    )


class HomeServiceSerializer(serializers.Serializer):
    """首页卡片中的已上架服务摘要。"""

    id = serializers.UUIDField(help_text="服务 UUID")
    title = serializers.CharField(help_text="服务名称")
    category_code = serializers.CharField(help_text="服务类目代码")
    price = serializers.DictField(help_text="服务基础价格")
    duration_minutes = serializers.IntegerField(help_text="服务时长")


class HomeVerificationSerializer(serializers.Serializer):
    """首页服务者认证状态。"""

    real_name_status = serializers.CharField(help_text="实名认证状态")
    face_status = serializers.CharField(help_text="人脸认证状态")


class HomeFeedItemSerializer(serializers.Serializer):
    """首页服务者卡片。"""

    provider_public_id = serializers.UUIDField(help_text="服务者对外用户标识")
    provider = HomeProviderSerializer(help_text="服务者资料")
    category_codes = serializers.ListField(
        child=serializers.CharField(),
        help_text="服务者关联类目代码",
    )
    recent_photo_media = MediaAssetSummarySerializer(
        many=True,
        help_text="最近服务者相关照片，最多 5 张",
    )
    recent_photo_count = serializers.IntegerField(help_text="本卡片返回的照片数量")
    services = HomeServiceSerializer(many=True, help_text="最近可预约的已上架服务")
    verification = HomeVerificationSerializer(help_text="认证状态")
    online_status = serializers.CharField(help_text="在线状态；当前数据未接入时为 UNKNOWN")
    distance_km = serializers.FloatField(
        allow_null=True,
        help_text="距离，单位千米；位置数据未接入时为空",
    )
    rating = serializers.FloatField(allow_null=True, help_text="评分；评价数据未接入时为空")


class SearchProviderGroupSerializer(serializers.Serializer):
    """综合搜索中的服务者结果分组。"""

    total = serializers.IntegerField(help_text="服务者搜索结果总数")
    items = HomeFeedItemSerializer(many=True, help_text="服务者搜索预览列表")
    has_more = serializers.BooleanField(help_text="服务者结果是否还有更多数据")


class SearchMomentGroupSerializer(serializers.Serializer):
    """综合搜索中的动态结果分组。"""

    total = serializers.IntegerField(help_text="动态搜索结果总数")
    items = MomentResponseSerializer(many=True, help_text="动态搜索预览列表")
    has_more = serializers.BooleanField(help_text="动态结果是否还有更多数据")


class SearchNewsGroupSerializer(serializers.Serializer):
    """综合搜索中的资讯结果分组。"""

    total = serializers.IntegerField(help_text="资讯搜索结果总数")
    items = NewsArticleResponseSerializer(many=True, help_text="资讯搜索预览列表")
    has_more = serializers.BooleanField(help_text="资讯结果是否还有更多数据")


class SearchResponseSerializer(serializers.Serializer):
    """服务者、动态和资讯综合搜索响应。"""

    keyword = serializers.CharField(help_text="本次搜索展示关键词")
    providers = SearchProviderGroupSerializer(help_text="服务者搜索结果分组")
    moments = SearchMomentGroupSerializer(help_text="动态搜索结果分组")
    news = SearchNewsGroupSerializer(help_text="资讯搜索结果分组")


class SearchProviderListResponseSerializer(serializers.Serializer):
    """服务者关键词搜索游标分页响应。"""

    items = HomeFeedItemSerializer(many=True, help_text="服务者搜索结果列表")
    total = serializers.IntegerField(help_text="服务者搜索结果总数")
    next_cursor = serializers.CharField(
        allow_null=True,
        help_text="下一页游标；没有更多数据时为空",
    )
    has_more = serializers.BooleanField(help_text="是否还有下一页")
    limit = serializers.IntegerField(help_text="本次分页数量")


class SearchMomentListResponseSerializer(serializers.Serializer):
    """动态关键词搜索游标分页响应。"""

    items = MomentResponseSerializer(many=True, help_text="动态搜索结果列表")
    total = serializers.IntegerField(help_text="动态搜索结果总数")
    next_cursor = serializers.CharField(
        allow_null=True,
        help_text="下一页游标；没有更多数据时为空",
    )
    has_more = serializers.BooleanField(help_text="是否还有下一页")
    limit = serializers.IntegerField(help_text="本次分页数量")


class SearchNewsListResponseSerializer(serializers.Serializer):
    """资讯关键词搜索页码分页响应。"""

    items = NewsArticleResponseSerializer(many=True, help_text="资讯搜索结果列表")
    total = serializers.IntegerField(help_text="资讯搜索结果总数")
    page = serializers.IntegerField(help_text="当前页码")
    page_size = serializers.IntegerField(help_text="每页数量")


class TrendingKeywordResponseSerializer(serializers.Serializer):
    """公开热门搜索词响应。"""

    keyword = serializers.CharField(help_text="规范化热门搜索词")
    display_text = serializers.CharField(help_text="热门搜索展示词")
    hot_type = serializers.ChoiceField(
        choices=["AUTO", "MANUAL"],
        help_text="热门来源：自动热度或人工配置",
    )
    hot_score = serializers.IntegerField(
        allow_null=True,
        help_text="热度分数；未配置公开展示时为空",
    )
    rank = serializers.IntegerField(help_text="热榜名次，从 1 开始")
    updated_at = serializers.DateTimeField(help_text="热门搜索最近更新时间")


class TrendingListResponseSerializer(serializers.Serializer):
    """公开热门搜索列表响应。"""

    items = TrendingKeywordResponseSerializer(many=True, help_text="热门搜索列表")
    total = serializers.IntegerField(help_text="本次返回热门搜索数量")
    limit = serializers.IntegerField(help_text="本次返回数量上限")


class AdminTrendingKeywordResponseSerializer(TrendingKeywordResponseSerializer):
    """管理员热门搜索配置响应。"""

    trending_id = serializers.UUIDField(help_text="热门搜索配置 UUID")
    display_status = serializers.ChoiceField(
        choices=["ACTIVE", "HIDDEN", "BLOCKED"],
        help_text="展示状态：展示、下线或屏蔽",
    )
    manual_priority = serializers.IntegerField(help_text="人工置顶优先级，0 表示不置顶")
    version = serializers.IntegerField(help_text="人工配置乐观锁版本号")


class AdminTrendingCreateResponseSerializer(AdminTrendingKeywordResponseSerializer):
    """管理员创建热门搜索幂等响应。"""

    reused = serializers.BooleanField(help_text="是否为相同人工配置的重复创建请求")


class AdminTrendingUpdateResponseSerializer(AdminTrendingKeywordResponseSerializer):
    """管理员更新热门搜索响应。"""

    reused = serializers.BooleanField(help_text="固定为 false，表示本次执行了更新")


class AdminTrendingListResponseSerializer(serializers.Serializer):
    """管理员热门搜索配置列表响应。"""

    items = AdminTrendingKeywordResponseSerializer(many=True, help_text="热门搜索配置列表")
    total = serializers.IntegerField(help_text="热门搜索配置总数")


class AdminTrendingCreateSerializer(serializers.Serializer):
    """管理员创建人工热门搜索请求。"""

    display_keyword = serializers.CharField(help_text="热门搜索展示词，最多 100 个字符")
    display_status = serializers.ChoiceField(
        choices=["ACTIVE", "HIDDEN", "BLOCKED"],
        default="ACTIVE",
        help_text="初始展示状态：展示、下线或屏蔽",
    )
    manual_priority = serializers.IntegerField(
        default=0,
        min_value=0,
        help_text="人工置顶优先级，数值越小越靠前，0 表示不置顶",
    )


class AdminTrendingUpdateSerializer(serializers.Serializer):
    """管理员更新人工热门搜索请求。"""

    expected_version = serializers.IntegerField(min_value=1, help_text="当前配置版本号")
    display_keyword = serializers.CharField(
        required=False,
        help_text="新的热门搜索展示词；规范化词变化时同步更新",
    )
    display_status = serializers.ChoiceField(
        choices=["ACTIVE", "HIDDEN", "BLOCKED"],
        required=False,
        help_text="展示状态：展示、下线或屏蔽",
    )
    manual_priority = serializers.IntegerField(
        required=False,
        min_value=0,
        help_text="人工置顶优先级，数值越小越靠前，0 表示不置顶",
    )
