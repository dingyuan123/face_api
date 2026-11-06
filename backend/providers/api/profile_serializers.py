from __future__ import annotations

from rest_framework import serializers

from backend.media.api.serializers import MediaAssetSummarySerializer


class ProviderProfileInputSerializer(serializers.Serializer):
    """服务者资料修改请求。"""

    expected_version = serializers.IntegerField(
        min_value=0,
        help_text="查询接口返回的服务者资料版本号；首次创建资料时为 0",
    )
    nickname = serializers.CharField(
        required=False,
        help_text="服务者昵称，1 到 20 个字符，服务者之间忽略大小写唯一",
    )
    signature = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=100,
        help_text="服务者个性签名，最多 100 个字符",
    )
    introduction = serializers.CharField(
        required=False,
        help_text="服务者个人介绍，20 到 200 个字符",
    )
    avatar_media_id = serializers.CharField(
        required=False,
        help_text="本人上传的服务者资料头像或申请阶段头像媒体 ID",
    )
    photo_media_ids = serializers.ListField(
        child=serializers.CharField(),
        required=False,
        help_text="服务者照片墙媒体 ID，可复用申请阶段生活照，必须为 3 到 6 张",
    )
    category_codes = serializers.ListField(
        child=serializers.CharField(),
        required=False,
        help_text="服务类目代码列表，至少选择 1 个",
    )
    tag_codes = serializers.ListField(
        child=serializers.CharField(),
        required=False,
        help_text="服务者标签代码列表，最多 8 个",
    )


class ProviderProfileResponseSerializer(serializers.Serializer):
    """服务者资料安全响应。"""

    version = serializers.IntegerField(help_text="服务者资料版本号")
    nickname = serializers.CharField(allow_null=True, help_text="服务者昵称")
    signature = serializers.CharField(help_text="服务者个性签名")
    introduction = serializers.CharField(help_text="服务者个人介绍")
    avatar_media = MediaAssetSummarySerializer(
        allow_null=True,
        help_text="服务者头像媒体摘要和临时展示地址",
    )
    photo_media = MediaAssetSummarySerializer(
        many=True,
        help_text="服务者照片墙媒体摘要列表",
    )
    category_codes = serializers.ListField(
        child=serializers.CharField(),
        help_text="服务者资料关联的服务类目代码",
    )
    tag_codes = serializers.ListField(
        child=serializers.CharField(),
        help_text="服务者资料标签代码",
    )
    updated_at = serializers.DateTimeField(allow_null=True, help_text="资料最近更新时间")


class ProviderProfileUpdateResponseSerializer(ProviderProfileResponseSerializer):
    """服务者资料修改响应。"""

    changed = serializers.BooleanField(help_text="本次请求是否产生实际资料变化")
