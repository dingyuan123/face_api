from __future__ import annotations

from rest_framework import serializers

from backend.catalog.api.serializers import ServiceResponseSerializer
from backend.content.api.serializers import MomentResponseSerializer
from backend.media.api.serializers import MediaAssetSummarySerializer


class ProviderPublicSummarySerializer(serializers.Serializer):
    """公开服务者资料。"""

    public_id = serializers.UUIDField(help_text="服务者公开用户 UUID")
    nickname = serializers.CharField(help_text="服务者昵称")
    gender = serializers.CharField(allow_null=True, help_text="服务者性别")
    age = serializers.IntegerField(allow_null=True, help_text="服务者年龄")
    city_code = serializers.CharField(allow_null=True, help_text="城市代码")
    signature = serializers.CharField(help_text="服务者签名")
    introduction = serializers.CharField(help_text="服务者介绍")
    avatar_media = MediaAssetSummarySerializer(allow_null=True, help_text="头像媒体")


class ProviderPublicResponseSerializer(serializers.Serializer):
    """公开服务者资料页响应。"""

    provider = ProviderPublicSummarySerializer(help_text="服务者资料")
    category_codes = serializers.ListField(child=serializers.CharField(), help_text="服务类目代码")
    tag_codes = serializers.ListField(child=serializers.CharField(), help_text="服务者标签代码")
    photo_media = MediaAssetSummarySerializer(many=True, help_text="服务者照片墙")
    services = ServiceResponseSerializer(many=True, help_text="已上架服务")
    moments = MomentResponseSerializer(many=True, help_text="最近已发布动态")
    statistics = serializers.DictField(help_text="收藏、关注、评分和评价统计")
    viewer_state = serializers.DictField(help_text="当前用户关注和收藏状态")
