from __future__ import annotations

from rest_framework import serializers

from backend.media.models import MediaAsset


class MediaUploadRequestSerializer(serializers.Serializer):
    """服务者申请图片上传请求。"""

    purpose = serializers.ChoiceField(
        choices=MediaAsset.Purpose.choices,
        help_text="媒体用途，包括用户资料、服务者资料、服务、动态和资讯图片",
    )
    file = serializers.FileField(help_text="JPEG、PNG 或 WebP 图片文件")


class MediaAssetSummarySerializer(serializers.Serializer):
    """媒体安全摘要，不包含存储路径。"""

    media_id = serializers.UUIDField(help_text="媒体唯一标识")
    purpose = serializers.CharField(help_text="媒体用途")
    content_type = serializers.CharField(help_text="服务端校验后的 MIME 类型")
    byte_size = serializers.IntegerField(help_text="规范化文件大小，单位为字节")
    width = serializers.IntegerField(help_text="图片宽度，单位为像素")
    height = serializers.IntegerField(help_text="图片高度，单位为像素")
    content_url = serializers.CharField(help_text="受认证保护的媒体内容地址")
    display_url = serializers.CharField(
        help_text="可直接加载的短期签名图片地址，不需要 Authorization"
    )
    display_url_expires_at = serializers.DateTimeField(
        help_text="display_url 过期时间，过期后重新请求业务接口获取新地址"
    )
    created_at = serializers.DateTimeField(help_text="媒体创建时间，RFC 3339 UTC 时间")


class MediaAssetResponseSerializer(MediaAssetSummarySerializer):
    """媒体上传结果。"""

    reused = serializers.BooleanField(help_text="是否为幂等重放或内容去重结果")
