"""订单会话、成员、消息和实时投递记录的数据模型。"""

from __future__ import annotations

import uuid
from typing import ClassVar

from django.conf import settings
from django.db import models


class Conversation(models.Model):
    """同一个预约用户与服务者共享一个长期会话，订单只作为会话来源。"""

    class Status(models.TextChoices):
        OPEN = "OPEN", "可发送"
        READ_ONLY = "READ_ONLY", "仅查看"
        CLOSED = "CLOSED", "已关闭"

    id = models.BigAutoField(primary_key=True, db_comment="订单会话自增主键")
    public_id = models.UUIDField(
        default=uuid.uuid4,
        unique=True,
        editable=False,
        db_comment="接口使用的会话 UUID，不暴露自增主键",
    )
    order = models.OneToOneField(
        "orders.Order",
        on_delete=models.PROTECT,
        related_name="conversation",
        db_comment="会话创建时的首个订单；历史兼容字段，不代表会话只属于该订单",
    )
    pair_key = models.CharField(
        max_length=80,
        null=True,
        blank=True,
        unique=True,
        db_comment="预约用户与服务者的稳定配对键；旧数据可能为空，由服务兼容回填",
    )
    status = models.CharField(
        max_length=16,
        choices=Status.choices,
        default=Status.OPEN,
        db_comment="会话发送状态：可发送、仅查看或已关闭",
    )
    close_reason = models.CharField(
        max_length=64,
        blank=True,
        default="",
        db_comment="会话关闭或只读原因，例如订单取消、退款或发送窗口结束",
    )
    closed_at = models.DateTimeField(
        null=True,
        blank=True,
        db_comment="会话进入关闭或只读状态的时间",
    )
    next_sequence = models.PositiveBigIntegerField(
        default=0,
        db_comment="下一条消息序号；由数据库事务加锁分配，保证会话内严格递增",
    )
    version = models.PositiveIntegerField(default=1, db_comment="会话乐观锁版本号")
    created_at = models.DateTimeField(auto_now_add=True, db_comment="订单会话创建时间")
    updated_at = models.DateTimeField(auto_now=True, db_comment="订单会话最近更新时间")

    class Meta:
        db_table = "messaging_conversations"
        db_table_comment = "订单双方实时聊天会话主表"
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.UniqueConstraint(fields=["order"], name="uniq_messaging_conversation_order"),
        ]
        indexes: ClassVar[list[models.Index]] = [
            models.Index(fields=["status", "updated_at"]),
        ]

    def __str__(self) -> str:
        return f"Conversation({self.public_id})"


class ConversationOrderLink(models.Model):
    """记录会话与历史订单的多对多来源关系，支持同一双方多个订单复用会话。"""

    id = models.BigAutoField(primary_key=True, db_comment="会话订单关联自增主键")
    conversation = models.ForeignKey(
        Conversation,
        on_delete=models.PROTECT,
        related_name="order_links",
        db_comment="订单关联的共享会话",
    )
    order = models.OneToOneField(
        "orders.Order",
        on_delete=models.PROTECT,
        related_name="conversation_link",
        db_comment="产生或恢复会话资格的订单；一个订单只关联一个共享会话",
    )
    created_at = models.DateTimeField(auto_now_add=True, db_comment="订单关联到共享会话的时间")

    class Meta:
        db_table = "messaging_conversation_order_links"
        db_table_comment = "共享会话与订单来源关联表"
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.UniqueConstraint(
                fields=["conversation", "order"],
                name="uniq_messaging_conversation_order_link",
            ),
        ]
        indexes: ClassVar[list[models.Index]] = [
            models.Index(fields=["conversation", "created_at"]),
        ]


class ConversationMember(models.Model):
    """共享会话成员、角色、已读位置和单用户隐藏状态。"""

    class Role(models.TextChoices):
        CUSTOMER = "CUSTOMER", "预约用户"
        PROVIDER = "PROVIDER", "服务者"
        SYSTEM = "SYSTEM", "系统"

    id = models.BigAutoField(primary_key=True, db_comment="会话成员自增主键")
    conversation = models.ForeignKey(
        Conversation,
        on_delete=models.CASCADE,
        related_name="members",
        db_comment="成员所属订单会话",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="conversation_memberships",
        db_comment="会话成员用户；保留成员关系用于聊天记录追溯",
    )
    role = models.CharField(
        max_length=16,
        choices=Role.choices,
        db_comment="成员在订单中的角色：预约用户、服务者或系统",
    )
    last_read_sequence = models.PositiveBigIntegerField(
        default=0,
        db_comment="成员已经读到的最大消息序号，用于计算未读数",
    )
    joined_at = models.DateTimeField(auto_now_add=True, db_comment="成员加入会话时间")
    last_read_at = models.DateTimeField(
        null=True,
        blank=True,
        db_comment="成员最近确认已读的时间",
    )
    hidden_at = models.DateTimeField(
        null=True,
        blank=True,
        db_comment="成员在客户端删除会话的时间；只影响该成员展示，不删除聊天记录",
    )

    class Meta:
        db_table = "messaging_conversation_members"
        db_table_comment = "订单聊天会话成员和已读位置表"
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.UniqueConstraint(
                fields=["conversation", "user"],
                name="uniq_messaging_conversation_user",
            ),
        ]
        indexes: ClassVar[list[models.Index]] = [
            models.Index(fields=["user", "last_read_sequence"]),
        ]


class Message(models.Model):
    """订单会话中的文本、图片或系统消息事实记录。"""

    class SenderRole(models.TextChoices):
        CUSTOMER = "CUSTOMER", "预约用户"
        PROVIDER = "PROVIDER", "服务者"
        SYSTEM = "SYSTEM", "系统"

    class MessageType(models.TextChoices):
        TEXT = "TEXT", "文本消息"
        IMAGE = "IMAGE", "图片消息"
        SYSTEM = "SYSTEM", "系统消息"

    id = models.BigAutoField(primary_key=True, db_comment="聊天消息自增主键")
    message_no = models.UUIDField(
        default=uuid.uuid4,
        unique=True,
        editable=False,
        db_comment="对外消息 UUID，断线补偿和客户端去重使用",
    )
    conversation = models.ForeignKey(
        Conversation,
        on_delete=models.PROTECT,
        related_name="messages",
        db_comment="消息所属订单会话；聊天记录按合规期限留存",
    )
    sender = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="sent_messages",
        db_comment="消息发送用户；系统消息为空",
    )
    sender_role = models.CharField(
        max_length=16,
        choices=SenderRole.choices,
        db_comment="发送时的订单角色快照，避免角色变化影响历史记录",
    )
    message_type = models.CharField(
        max_length=16,
        choices=MessageType.choices,
        db_comment="消息类型：文本、图片或系统消息",
    )
    content = models.TextField(
        blank=True,
        default="",
        db_comment="文本或系统消息正文；图片消息为空，消息正文不得写入应用日志",
    )
    media = models.ForeignKey(
        "media.MediaAsset",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="chat_messages",
        db_comment="图片消息关联媒体；仅允许发送者本人的聊天图片用途媒体",
    )
    client_message_id = models.CharField(
        max_length=64,
        null=True,
        blank=True,
        db_comment="客户端生成的消息幂等标识；同一会话同一发送者重复提交只生成一条消息",
    )
    request_fingerprint = models.CharField(
        max_length=64,
        blank=True,
        default="",
        db_comment="消息类型、正文和媒体摘要，用于识别同幂等标识的不同请求",
    )
    sequence = models.PositiveBigIntegerField(
        db_comment="会话内严格递增的消息序号，用于排序、游标补偿和已读位置",
    )
    revoked_at = models.DateTimeField(
        null=True,
        blank=True,
        db_comment="消息撤回时间；空值表示消息仍正常展示",
    )
    revoked_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="revoked_messages",
        db_comment="执行撤回的用户；仅保留审计用途",
    )
    created_at = models.DateTimeField(auto_now_add=True, db_comment="消息持久化创建时间")
    updated_at = models.DateTimeField(auto_now=True, db_comment="消息最近更新时间")

    class Meta:
        db_table = "messaging_messages"
        db_table_comment = "订单聊天消息事实表"
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.UniqueConstraint(
                fields=["conversation", "sequence"],
                name="uniq_messaging_message_sequence",
            ),
            models.UniqueConstraint(
                fields=["conversation", "sender", "client_message_id"],
                condition=models.Q(client_message_id__isnull=False),
                name="uniq_messaging_message_client_id",
            ),
            models.UniqueConstraint(
                fields=["conversation", "client_message_id"],
                condition=models.Q(
                    sender__isnull=True,
                    client_message_id__isnull=False,
                ),
                name="uniq_messaging_message_system_client_id",
            ),
        ]
        indexes: ClassVar[list[models.Index]] = [
            models.Index(fields=["conversation", "sequence"]),
            models.Index(fields=["conversation", "created_at"]),
        ]

    def __str__(self) -> str:
        return f"Message({self.message_no})"


class MessagingConnectionTicket(models.Model):
    """WebSocket 短时效一次性连接凭证，不保存访问令牌明文。"""

    id = models.BigAutoField(primary_key=True, db_comment="实时连接凭证自增主键")
    ticket_hash = models.CharField(
        max_length=64,
        unique=True,
        db_comment="连接凭证 SHA-256 摘要；原始随机凭证只返回给客户端一次",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="messaging_connection_tickets",
        db_comment="凭证绑定用户；连接后仍校验会话成员身份",
    )
    expires_at = models.DateTimeField(db_comment="连接凭证过期时间，UTC 时间")
    used_at = models.DateTimeField(
        null=True,
        blank=True,
        db_comment="连接凭证首次消费时间；非空表示不允许再次使用",
    )
    created_at = models.DateTimeField(auto_now_add=True, db_comment="连接凭证创建时间")

    class Meta:
        db_table = "messaging_connection_tickets"
        db_table_comment = "实时聊天 WebSocket 一次性连接凭证表"
        indexes: ClassVar[list[models.Index]] = [
            models.Index(fields=["user", "expires_at"]),
        ]


class MessageDelivery(models.Model):
    """消息实时投递 Outbox 记录，按事件和消费者幂等。"""

    class Status(models.TextChoices):
        PENDING = "PENDING", "待投递"
        DELIVERED = "DELIVERED", "已投递"
        FAILED = "FAILED", "投递失败"

    id = models.BigAutoField(primary_key=True, db_comment="消息投递记录自增主键")
    event_id = models.UUIDField(
        default=uuid.uuid4,
        db_comment="领域事件 UUID；与消费者名称联合实现重复消费幂等",
    )
    consumer_name = models.CharField(
        max_length=64,
        default="websocket.broadcast",
        db_comment="事件消费者名称，例如 WebSocket 广播或离线推送",
    )
    event_type = models.CharField(
        max_length=64,
        default="MESSAGE_CREATED",
        db_comment="领域事件类型，当前为消息创建事件",
    )
    message = models.ForeignKey(
        Message,
        on_delete=models.PROTECT,
        related_name="deliveries",
        db_comment="事件关联消息；投递记录不得替代消息事实",
    )
    conversation = models.ForeignKey(
        Conversation,
        on_delete=models.PROTECT,
        related_name="message_deliveries",
        db_comment="事件所属订单会话，用于生成实时广播组",
    )
    version = models.PositiveIntegerField(default=1, db_comment="事件版本号")
    occurred_at = models.DateTimeField(db_comment="领域事件发生时间")
    trace_id = models.CharField(max_length=64, db_comment="产生事件的请求追踪标识")
    status = models.CharField(
        max_length=16,
        choices=Status.choices,
        default=Status.PENDING,
        db_comment="实时投递状态：待投递、已投递或失败",
    )
    retry_count = models.PositiveSmallIntegerField(default=0, db_comment="实时投递重试次数")
    last_error = models.TextField(blank=True, default="", db_comment="最近一次投递错误摘要")
    delivered_at = models.DateTimeField(
        null=True,
        blank=True,
        db_comment="实时 Channel Layer 确认接收事件的时间",
    )
    created_at = models.DateTimeField(auto_now_add=True, db_comment="投递记录创建时间")
    updated_at = models.DateTimeField(auto_now=True, db_comment="投递记录最近更新时间")

    class Meta:
        db_table = "messaging_message_deliveries"
        db_table_comment = "聊天消息实时投递 Outbox 表"
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.UniqueConstraint(
                fields=["event_id", "consumer_name"],
                name="uniq_messaging_event_consumer",
            ),
        ]
        indexes: ClassVar[list[models.Index]] = [
            models.Index(fields=["status", "created_at"]),
        ]
