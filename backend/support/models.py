"""客服工单、工单消息和常见问题数据模型。"""

from __future__ import annotations

import uuid
from typing import ClassVar

from django.conf import settings
from django.db import models


class SupportTicket(models.Model):
    """用户咨询、投诉、纠纷和反馈工单。"""

    class Category(models.TextChoices):
        ORDER = "ORDER", "订单问题"
        REFUND = "REFUND", "退款问题"
        ACCOUNT = "ACCOUNT", "账号问题"
        CONTENT = "CONTENT", "内容问题"
        FEEDBACK = "FEEDBACK", "意见反馈"
        OTHER = "OTHER", "其他问题"

    class Status(models.TextChoices):
        OPEN = "OPEN", "待处理"
        PENDING = "PENDING", "等待用户补充"
        RESOLVED = "RESOLVED", "已解决"
        CLOSED = "CLOSED", "已关闭"

    class Priority(models.TextChoices):
        LOW = "LOW", "低"
        NORMAL = "NORMAL", "普通"
        HIGH = "HIGH", "高"
        URGENT = "URGENT", "紧急"

    id = models.BigAutoField(primary_key=True, db_comment="客服工单自增主键")
    ticket_no = models.UUIDField(
        default=uuid.uuid4,
        unique=True,
        editable=False,
        db_comment="对外客服工单 UUID",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="support_tickets",
        db_comment="提交工单用户",
    )
    category = models.CharField(
        max_length=32,
        choices=Category.choices,
        default=Category.OTHER,
        db_comment="工单分类",
    )
    subject = models.CharField(max_length=120, db_comment="工单主题")
    description = models.TextField(db_comment="问题描述")
    status = models.CharField(
        max_length=16,
        choices=Status.choices,
        default=Status.OPEN,
        db_comment="工单处理状态",
    )
    priority = models.CharField(
        max_length=16,
        choices=Priority.choices,
        default=Priority.NORMAL,
        db_comment="工单优先级",
    )
    related_order_no = models.CharField(
        max_length=64,
        blank=True,
        default="",
        db_comment="关联订单号，可为空",
    )
    assigned_agent_id = models.BigIntegerField(
        null=True,
        blank=True,
        db_comment="当前客服管理员用户主键",
    )
    resolution = models.CharField(max_length=500, blank=True, default="", db_comment="处理结论")
    version = models.PositiveIntegerField(default=1, db_comment="工单乐观锁版本号")
    created_at = models.DateTimeField(auto_now_add=True, db_comment="工单创建时间")
    updated_at = models.DateTimeField(auto_now=True, db_comment="工单最近更新时间")
    resolved_at = models.DateTimeField(null=True, blank=True, db_comment="工单解决时间")

    class Meta:
        db_table = "support_tickets"
        db_table_comment = "客服咨询、投诉和反馈工单表"
        indexes: ClassVar[list[models.Index]] = [
            models.Index(fields=["user", "created_at"]),
            models.Index(fields=["status", "priority", "created_at"]),
            models.Index(fields=["assigned_agent_id", "status"]),
        ]


class SupportMessage(models.Model):
    """客服工单消息记录。"""

    class SenderType(models.TextChoices):
        USER = "USER", "用户"
        AGENT = "AGENT", "客服"
        SYSTEM = "SYSTEM", "系统"

    id = models.BigAutoField(primary_key=True, db_comment="客服消息自增主键")
    ticket = models.ForeignKey(
        SupportTicket,
        on_delete=models.PROTECT,
        related_name="messages",
        db_comment="所属客服工单",
    )
    sender_type = models.CharField(
        max_length=16,
        choices=SenderType.choices,
        db_comment="消息发送者类型",
    )
    sender_id = models.BigIntegerField(null=True, blank=True, db_comment="发送者用户主键")
    content = models.TextField(db_comment="消息正文")
    sequence = models.PositiveIntegerField(db_comment="工单内递增消息序号")
    client_message_id = models.CharField(
        max_length=128,
        blank=True,
        default="",
        db_comment="客户端消息幂等标识",
    )
    created_at = models.DateTimeField(auto_now_add=True, db_comment="消息创建时间")

    class Meta:
        db_table = "support_messages"
        db_table_comment = "客服工单消息表"
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.UniqueConstraint(
                fields=["ticket", "sequence"],
                name="uniq_support_message_sequence",
            ),
            models.UniqueConstraint(
                fields=["ticket", "sender_id", "client_message_id"],
                condition=models.Q(client_message_id__isnull=False)
                & ~models.Q(client_message_id=""),
                name="uniq_support_message_client_id",
            ),
        ]


class SupportFAQ(models.Model):
    """平台常见问题配置。"""

    id = models.BigAutoField(primary_key=True, db_comment="常见问题自增主键")
    question = models.CharField(max_length=200, db_comment="常见问题标题")
    answer = models.TextField(db_comment="常见问题答案")
    category = models.CharField(max_length=50, default="GENERAL", db_comment="常见问题分类")
    sort_order = models.PositiveIntegerField(default=0, db_comment="展示排序值")
    is_active = models.BooleanField(default=True, db_comment="是否公开显示")
    version = models.PositiveIntegerField(default=1, db_comment="常见问题版本号")
    created_at = models.DateTimeField(auto_now_add=True, db_comment="常见问题创建时间")
    updated_at = models.DateTimeField(auto_now=True, db_comment="常见问题最近更新时间")

    class Meta:
        db_table = "support_faqs"
        db_table_comment = "客服常见问题配置表"
