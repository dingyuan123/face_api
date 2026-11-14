"""普通用户实名认证接口请求和响应模型。"""

from __future__ import annotations

from rest_framework import serializers

from backend.media.api.serializers import MediaAssetSummarySerializer


class RealNameVerificationRequestSerializer(serializers.Serializer):
    """提交真实姓名、身份证号和正反面照片请求。"""

    real_name = serializers.CharField(write_only=True, help_text="真实姓名；仅写入加密保存")
    id_card_number = serializers.CharField(
        write_only=True,
        help_text="中国大陆身份证号；仅写入加密保存",
    )
    id_card_front_media_id = serializers.CharField(
        help_text="本人上传的身份证正面照片媒体 ID",
    )
    id_card_back_media_id = serializers.CharField(
        help_text="本人上传的身份证反面照片媒体 ID",
    )
    expected_version = serializers.IntegerField(
        required=False,
        default=0,
        min_value=0,
        help_text="查询返回的认证版本号；首次提交为 0",
    )


class IdentityVerificationResponseSerializer(serializers.Serializer):
    """实名认证脱敏状态响应。"""

    verification_no = serializers.UUIDField(allow_null=True, help_text="实名认证业务 UUID")
    status = serializers.CharField(help_text="实名认证状态")
    real_name_status = serializers.CharField(help_text="实名认证状态兼容字段")
    id_card_front_media_id = serializers.CharField(
        allow_null=True,
        help_text="身份证正面照片媒体 ID",
    )
    id_card_back_media_id = serializers.CharField(
        allow_null=True,
        help_text="身份证反面照片媒体 ID",
    )
    id_card_front_media = MediaAssetSummarySerializer(
        allow_null=True,
        help_text="身份证正面照片安全摘要",
    )
    id_card_back_media = MediaAssetSummarySerializer(
        allow_null=True,
        help_text="身份证反面照片安全摘要",
    )
    reject_reason = serializers.CharField(help_text="人工审核拒绝原因")
    submitted_at = serializers.DateTimeField(allow_null=True, help_text="提交时间")
    reviewed_at = serializers.DateTimeField(allow_null=True, help_text="人工审核时间")
    version = serializers.IntegerField(help_text="认证乐观锁版本号")
    user_public_id = serializers.UUIDField(help_text="申请人对外用户标识")


class IdentityReviewRequestSerializer(serializers.Serializer):
    """管理员人工审核实名认证请求。"""

    expected_version = serializers.IntegerField(min_value=1, help_text="认证记录版本号")
    reason = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=255,
        help_text="拒绝原因；审核通过可为空",
    )
