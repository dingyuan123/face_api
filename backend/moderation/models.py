"""内容举报、敏感词和匹配审计数据模型。"""

from __future__ import annotations

import uuid
from typing import ClassVar

from django.conf import settings
from django.db import models


class ContentReport(models.Model):
    """用户提交的内容或用户举报。"""

    class TargetType(models.TextChoices):
        MOMENT = "MOMENT", "动态"
        NEWS = "NEWS", "资讯"
        USER = "USER", "用户"
        SERVICE = "SERVICE", "服务"

    class Status(models.TextChoices):
        PENDING = "PENDING", "待处理"
        RESOLVED = "RESOLVED", "已处理"
        REJECTED = "REJECTED", "已驳回"

    id = models.BigAutoField(primary_key=True, db_comment="内容举报自增主键")
    report_no = models.UUIDField(
        default=uuid.uuid4,
        unique=True,
        editable=False,
        db_comment="对外举报业务 UUID",
    )
    reporter = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="submitted_content_reports",
        db_comment="举报提交用户",
    )
    target_type = models.CharField(
        max_length=32,
        choices=TargetType.choices,
        db_comment="被举报对象类型",
    )
    target_id = models.CharField(max_length=128, db_comment="被举报对象业务标识")
    reason = models.CharField(max_length=500, db_comment="举报原因")
    evidence_urls = models.JSONField(
        default=list,
        blank=True,
        db_comment="举报证据地址数组；不保存无关敏感信息",
    )
    status = models.CharField(
        max_length=16,
        choices=Status.choices,
        default=Status.PENDING,
        db_comment="举报处理状态",
    )
    resolution = models.CharField(max_length=500, blank=True, default="", db_comment="处理结论")
    handled_by = models.BigIntegerField(
        null=True,
        blank=True,
        db_comment="处理举报的管理员用户主键",
    )
    handled_at = models.DateTimeField(null=True, blank=True, db_comment="举报处理时间")
    version = models.PositiveIntegerField(default=1, db_comment="举报乐观锁版本号")
    created_at = models.DateTimeField(auto_now_add=True, db_comment="举报创建时间")
    updated_at = models.DateTimeField(auto_now=True, db_comment="举报最近更新时间")

    class Meta:
        db_table = "content_reports"
        db_table_comment = "内容和用户举报处理表"
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.UniqueConstraint(
                fields=["reporter", "target_type", "target_id"],
                name="uniq_content_report_target",
            ),
            models.CheckConstraint(
                condition=models.Q(version__gte=1),
                name="check_content_report_version_positive",
            ),
        ]
        indexes: ClassVar[list[models.Index]] = [
            models.Index(fields=["status", "created_at"]),
            models.Index(fields=["target_type", "target_id"]),
        ]


class SensitiveWord(models.Model):
    """敏感词和处理动作配置。"""

    class Action(models.TextChoices):
        BLOCK = "BLOCK", "拦截"
        REVIEW = "REVIEW", "转人工审核"

    class Status(models.TextChoices):
        ACTIVE = "ACTIVE", "启用"
        DISABLED = "DISABLED", "停用"

    id = models.BigAutoField(primary_key=True, db_comment="敏感词自增主键")
    word = models.CharField(max_length=100, unique=True, db_comment="敏感词文本")
    category = models.CharField(max_length=50, default="DEFAULT", db_comment="敏感词分类")
    action = models.CharField(
        max_length=16,
        choices=Action.choices,
        default=Action.REVIEW,
        db_comment="命中后的处理动作",
    )
    status = models.CharField(
        max_length=16,
        choices=Status.choices,
        default=Status.ACTIVE,
        db_comment="敏感词启用状态",
    )
    version = models.PositiveIntegerField(default=1, db_comment="敏感词乐观锁版本号")
    created_at = models.DateTimeField(auto_now_add=True, db_comment="敏感词创建时间")
    updated_at = models.DateTimeField(auto_now=True, db_comment="敏感词最近更新时间")

    class Meta:
        db_table = "sensitive_words"
        db_table_comment = "内容敏感词配置表"


class SensitiveWordMatchLog(models.Model):
    """敏感词命中审计记录。"""

    id = models.BigAutoField(primary_key=True, db_comment="敏感词命中自增主键")
    word = models.CharField(max_length=100, db_comment="命中敏感词")
    target_type = models.CharField(max_length=32, db_comment="命中对象类型")
    target_id = models.CharField(max_length=128, db_comment="命中对象业务标识")
    action = models.CharField(max_length=16, db_comment="命中后处理动作")
    created_at = models.DateTimeField(auto_now_add=True, db_comment="命中记录时间")

    class Meta:
        db_table = "sensitive_word_match_logs"
        db_table_comment = "敏感词命中审计表"
