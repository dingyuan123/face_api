from __future__ import annotations

from typing import ClassVar

from django.conf import settings
from django.db import models


class IdentityVerification(models.Model):
    """实名和人脸认证状态记录表。"""

    class Type(models.TextChoices):
        REAL_NAME = "REAL_NAME", "实名认证"
        FACE = "FACE", "人脸认证"

    class Status(models.TextChoices):
        NOT_SUBMITTED = "NOT_SUBMITTED", "未提交"
        PENDING = "PENDING", "认证中"
        MOCK_PASSED = "MOCK_PASSED", "Mock 已通过"
        PASSED = "PASSED", "已通过"
        FAILED = "FAILED", "未通过"

    id = models.BigAutoField(primary_key=True, db_comment="身份认证记录自增主键")
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="identity_verifications",
        db_comment="认证记录所属用户；用户删除时同步删除认证记录",
    )
    verification_type = models.CharField(
        max_length=16,
        choices=Type.choices,
        db_comment="认证类型：实名认证或人脸认证",
    )
    status = models.CharField(
        max_length=16,
        choices=Status.choices,
        default=Status.NOT_SUBMITTED,
        db_comment="认证状态：未提交、认证中、Mock 已通过、真实通过或失败",
    )
    provider_request_no = models.CharField(
        max_length=128,
        blank=True,
        default="",
        db_comment="认证服务商请求号或开发 Mock 随机请求号；不包含证件明文",
    )
    result_code = models.CharField(
        max_length=64,
        blank=True,
        default="",
        db_comment="认证结果码或 Mock 结果码",
    )
    submitted_at = models.DateTimeField(null=True, blank=True, db_comment="认证提交时间")
    verified_at = models.DateTimeField(null=True, blank=True, db_comment="认证完成或失败时间")
    created_at = models.DateTimeField(auto_now_add=True, db_comment="认证记录创建时间")
    updated_at = models.DateTimeField(auto_now=True, db_comment="认证记录最近更新时间")

    class Meta:
        db_table = "identity_verifications"
        db_table_comment = "实名和人脸认证状态记录表"
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.UniqueConstraint(
                fields=["user", "verification_type"],
                name="uniq_identity_user_type",
            )
        ]
