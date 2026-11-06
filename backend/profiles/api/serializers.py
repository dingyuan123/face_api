from __future__ import annotations

from rest_framework import serializers

from backend.media.api.serializers import MediaAssetSummarySerializer


class InterestTagResponseSerializer(serializers.Serializer):
    """兴趣标签配置。"""

    code = serializers.CharField(help_text="稳定兴趣标签代码")
    name = serializers.CharField(help_text="兴趣标签展示名称")
    category = serializers.CharField(help_text="兴趣标签分类")
    sort_order = serializers.IntegerField(help_text="标签展示排序值")


class CityOptionResponseSerializer(serializers.Serializer):
    """城市选项配置。"""

    code = serializers.CharField(help_text="稳定城市代码")
    name = serializers.CharField(help_text="城市展示名称")
    sort_order = serializers.IntegerField(help_text="城市展示排序值")


class TrustLevelResponseSerializer(serializers.Serializer):
    """安心用户等级预留信息。"""

    code = serializers.CharField(help_text="安心用户等级代码；当前仅预留")
    name = serializers.CharField(help_text="安心用户等级展示名；当前仅预留")
    updated_at = serializers.DateTimeField(allow_null=True, help_text="等级最近维护时间")


class ProfileResponseSerializer(serializers.Serializer):
    """当前用户个人资料响应。"""

    version = serializers.IntegerField(help_text="个人资料版本号，修改时用于并发控制")
    nickname = serializers.CharField(allow_null=True, help_text="个人昵称")
    avatar_media = MediaAssetSummarySerializer(
        allow_null=True,
        help_text="个人头像媒体摘要和临时展示地址",
    )
    gender = serializers.CharField(allow_null=True, help_text="性别，只能为 MALE 或 FEMALE")
    age = serializers.IntegerField(allow_null=True, help_text="用户填写年龄，范围 18 到 40")
    city_code = serializers.CharField(help_text="城市稳定代码")
    city_name = serializers.CharField(allow_null=True, help_text="城市展示名称")
    signature = serializers.CharField(help_text="个性签名")
    interest_tags = InterestTagResponseSerializer(
        many=True,
        help_text="已选择的兴趣标签列表",
    )
    trust_level = TrustLevelResponseSerializer(help_text="安心用户等级预留信息")
    profile_completeness = serializers.IntegerField(help_text="个人资料完整度百分比")
    updated_at = serializers.DateTimeField(allow_null=True, help_text="个人资料最近更新时间")


class ProfileUpdateRequestSerializer(serializers.Serializer):
    """个人资料局部修改请求。"""

    expected_version = serializers.IntegerField(
        min_value=0,
        help_text="查询接口返回的资料版本号；首次创建资料时为 0",
    )
    nickname = serializers.CharField(
        required=False,
        allow_null=True,
        help_text="个人昵称，1 到 30 个字符，忽略大小写唯一",
    )
    avatar_media_id = serializers.CharField(
        required=False,
        allow_null=True,
        help_text="本人上传的 USER_PROFILE_AVATAR 媒体 ID；传 null 可清空头像",
    )
    gender = serializers.ChoiceField(
        choices=["MALE", "FEMALE"],
        required=False,
        allow_null=True,
        help_text="性别，只能为 MALE 或 FEMALE",
    )
    age = serializers.IntegerField(
        required=False,
        allow_null=True,
        min_value=18,
        max_value=40,
        help_text="用户填写年龄，范围 18 到 40",
    )
    city_code = serializers.CharField(
        required=False,
        help_text="城市稳定代码，例如 LZ",
    )
    signature = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=100,
        help_text="个性签名，最多 100 个字符",
    )
    interest_tag_codes = serializers.ListField(
        child=serializers.CharField(),
        required=False,
        allow_empty=True,
        help_text="兴趣标签代码列表，最多 5 个，传入时整体替换",
    )


class ProfileUpdateResponseSerializer(ProfileResponseSerializer):
    """个人资料修改响应。"""

    changed = serializers.BooleanField(help_text="本次请求是否产生实际资料变化")


class ProfileSummaryResponseSerializer(serializers.Serializer):
    """我的页面订单、收藏和关注数量汇总。"""

    order_count = serializers.IntegerField(help_text="当前用户作为下单人的订单总数")
    provider_order_count = serializers.IntegerField(help_text="当前用户作为服务者的订单总数")
    favorite_count = serializers.IntegerField(help_text="我的收藏总数")
    following_count = serializers.IntegerField(help_text="我的关注总数")
    follower_count = serializers.IntegerField(help_text="关注我的用户总数")
    order_status_counts = serializers.DictField(help_text="用户订单状态数量")
    provider_order_status_counts = serializers.DictField(help_text="服务者订单状态数量")
