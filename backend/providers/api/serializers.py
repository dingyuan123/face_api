from __future__ import annotations

from rest_framework import serializers

from backend.media.api.serializers import MediaAssetSummarySerializer
from backend.providers.services import validate_application_payload


class ProviderApplicationInputSerializer(serializers.Serializer):
    """服务者入驻申请提交请求。"""

    introduction = serializers.CharField(help_text="服务者个人简介")
    real_name = serializers.CharField(write_only=True, help_text="真实姓名；仅写入，不返回")
    id_card_number = serializers.CharField(
        write_only=True,
        help_text="中国大陆身份证号；仅写入并加密保存，不返回",
    )
    avatar_media_id = serializers.CharField(help_text="本人上传的服务者申请头像媒体 ID")
    life_photo_media_ids = serializers.ListField(
        child=serializers.CharField(),
        allow_empty=True,
        help_text="本人上传的生活照媒体 ID 列表，数量受服务端配置限制",
    )

    def validate(self, attrs: dict) -> dict:
        validate_application_payload(attrs)
        return attrs


class ProviderApplicationUpdateRequestSerializer(ProviderApplicationInputSerializer):
    """被拒绝或已取消申请的重提请求。"""

    expected_version = serializers.IntegerField(
        min_value=1,
        help_text="查询时返回的当前申请版本号，用于防止并发覆盖",
    )


class ProviderApplicationResponseSerializer(serializers.Serializer):
    """脱敏服务者申请响应。"""

    application_no = serializers.CharField(allow_null=True, help_text="服务者申请业务编号")
    status = serializers.CharField(help_text="申请状态")
    introduction = serializers.CharField(help_text="服务者个人简介")
    avatar_media_id = serializers.CharField(allow_null=True, help_text="头像媒体 ID")
    life_photo_media_ids = serializers.ListField(
        child=serializers.CharField(),
        help_text="生活照媒体 ID 列表",
    )
    real_name_status = serializers.CharField(help_text="实名认证状态，不返回真实姓名")
    face_status = serializers.CharField(help_text="人脸认证状态")
    reject_reason = serializers.CharField(help_text="管理员拒绝原因；未拒绝时为空")
    submitted_at = serializers.DateTimeField(allow_null=True, help_text="申请提交时间")
    updated_at = serializers.DateTimeField(allow_null=True, help_text="申请最近更新时间")
    version = serializers.IntegerField(help_text="申请乐观锁版本号")
    user_public_id = serializers.UUIDField(help_text="申请人对外用户标识")
    user_phone_masked = serializers.CharField(help_text="申请人脱敏手机号")
    avatar_media = MediaAssetSummarySerializer(allow_null=True, help_text="头像媒体安全摘要")
    life_photo_media = MediaAssetSummarySerializer(many=True, help_text="生活照媒体安全摘要列表")


class ProviderReviewRequestSerializer(serializers.Serializer):
    """管理员审核请求。"""

    expected_version = serializers.IntegerField(
        min_value=1,
        help_text="审核前申请版本号，用于防止重复或并发审核",
    )
    reason = serializers.CharField(
        required=False,
        allow_blank=True,
        help_text="拒绝原因；拒绝时必填，通过时可省略",
    )
