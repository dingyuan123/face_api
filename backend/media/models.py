from __future__ import annotations

import uuid
from typing import ClassVar

from django.conf import settings
from django.db import models


class MediaAsset(models.Model):
    """媒体文件元数据和存储引用表。"""

    class Purpose(models.TextChoices):
        USER_PROFILE_AVATAR = "USER_PROFILE_AVATAR", "用户个人资料头像"
        PROVIDER_PROFILE_AVATAR = "PROVIDER_PROFILE_AVATAR", "服务者资料头像"
        PROVIDER_PROFILE_PHOTO = "PROVIDER_PROFILE_PHOTO", "服务者资料照片"
        PROVIDER_APPLICATION_AVATAR = "PROVIDER_APPLICATION_AVATAR", "服务者申请头像"
        PROVIDER_APPLICATION_LIFE_PHOTO = "PROVIDER_APPLICATION_LIFE_PHOTO", "服务者申请生活照"
        PROVIDER_SERVICE_COVER = "PROVIDER_SERVICE_COVER", "服务封面"
        PROVIDER_SERVICE_GALLERY = "PROVIDER_SERVICE_GALLERY", "服务图集"
        MOMENT_IMAGE = "MOMENT_IMAGE", "动态图片"
        MOMENT_VIDEO = "MOMENT_VIDEO", "动态视频"
        NEWS_IMAGE = "NEWS_IMAGE", "资讯图片"

    class Status(models.TextChoices):
        AVAILABLE = "AVAILABLE", "可用"
        DELETED = "DELETED", "已删除"

    id = models.BigAutoField(primary_key=True, db_comment="媒体资产自增主键")
    public_id = models.UUIDField(
        default=uuid.uuid4,
        unique=True,
        editable=False,
        db_comment="接口使用的媒体 UUID，避免暴露自增主键或存储路径",
    )
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="media_assets",
        db_comment="媒体上传者和当前所有者；用户删除时同步删除媒体元数据",
    )
    purpose = models.CharField(
        max_length=64,
        choices=Purpose.choices,
        db_comment="媒体用途，例如服务者申请头像或生活照",
    )
    status = models.CharField(
        max_length=16,
        choices=Status.choices,
        default=Status.AVAILABLE,
        db_comment="媒体状态：可用或已删除",
    )
    storage_key = models.CharField(
        max_length=255, unique=True, db_comment="服务端或对象存储中的媒体对象键"
    )
    content_type = models.CharField(max_length=64, db_comment="服务端校验后的媒体 MIME 类型")
    extension = models.CharField(max_length=16, db_comment="规范化后的媒体文件扩展名")
    byte_size = models.PositiveIntegerField(db_comment="规范化媒体文件大小，单位为字节")
    width = models.PositiveIntegerField(db_comment="图片宽度，单位为像素")
    height = models.PositiveIntegerField(db_comment="图片高度，单位为像素")
    sha256 = models.CharField(
        max_length=64, db_comment="规范化媒体内容 SHA-256 摘要，用于去重和完整性校验"
    )
    idempotency_key = models.CharField(
        max_length=128,
        null=True,
        blank=True,
        db_comment="上传请求幂等键，按用户隔离重复上传",
    )
    request_fingerprint = models.CharField(
        max_length=64,
        db_comment="上传用途和内容摘要的 HMAC，用于识别同幂等键不同请求",
    )
    created_at = models.DateTimeField(auto_now_add=True, db_comment="媒体元数据创建时间")
    last_referenced_at = models.DateTimeField(
        null=True,
        blank=True,
        db_comment="最近被业务记录引用的时间，用于后续孤儿文件清理",
    )
    deleted_at = models.DateTimeField(
        null=True, blank=True, db_comment="媒体逻辑删除时间；空值表示未删除"
    )

    class Meta:
        db_table = "media_assets"
        db_table_comment = "媒体文件元数据、所有权和存储引用表"
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.UniqueConstraint(
                fields=["owner", "purpose", "sha256"],
                name="uniq_media_owner_purpose_content",
            ),
            models.UniqueConstraint(
                fields=["owner", "idempotency_key"],
                name="uniq_media_owner_idempotency",
            ),
        ]
        indexes: ClassVar[list[models.Index]] = [
            models.Index(fields=["owner", "purpose", "status"]),
            models.Index(fields=["status", "created_at"]),
        ]

    def __str__(self) -> str:
        return f"MediaAsset({self.public_id})"
