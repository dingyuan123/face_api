from __future__ import annotations

import uuid
from typing import ClassVar

from django.conf import settings
from django.db import models


class Order(models.Model):
    """用户预约订单主表。"""

    class Status(models.TextChoices):
        PENDING_PAYMENT = "PENDING_PAYMENT", "待支付"
        PENDING_ACCEPT = "PENDING_ACCEPT", "待接单"
        PENDING_SERVICE = "PENDING_SERVICE", "待履约"
        IN_SERVICE = "IN_SERVICE", "履约中"
        PENDING_CONFIRM = "PENDING_CONFIRM", "待确认"
        COMPLETED = "COMPLETED", "已完成"
        CANCELED = "CANCELED", "已取消"
        REFUNDED = "REFUNDED", "已退款"

    id = models.BigAutoField(primary_key=True, db_comment="订单自增主键")
    order_no = models.UUIDField(
        default=uuid.uuid4,
        unique=True,
        editable=False,
        db_comment="对外订单业务 UUID",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="orders",
        db_comment="下单用户",
    )
    provider_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="provider_orders",
        db_comment="服务者用户",
    )
    service = models.ForeignKey(
        "catalog.ProviderService",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="orders",
        db_comment="订单服务引用；服务删除后保留价格和服务快照",
    )
    schedule_slot = models.ForeignKey(
        "scheduling.ScheduleSlot",
        on_delete=models.PROTECT,
        related_name="orders",
        db_comment="预约时段",
    )
    service_snapshot = models.JSONField(default=dict, db_comment="下单时服务价格和资料快照")
    provider_snapshot = models.JSONField(default=dict, db_comment="下单时服务者资料快照")
    slot_snapshot = models.JSONField(default=dict, db_comment="下单时预约时间快照")
    currency = models.CharField(max_length=3, default="CNY", db_comment="订单币种")
    original_price_amount_minor = models.BigIntegerField(db_comment="服务原价，单位为分")
    discount_amount_minor = models.BigIntegerField(default=0, db_comment="订单折扣金额，单位为分")
    platform_fee_amount_minor = models.BigIntegerField(default=0, db_comment="平台服务费，单位为分")
    payable_amount_minor = models.BigIntegerField(db_comment="订单应付金额，单位为分")
    paid_amount_minor = models.BigIntegerField(default=0, db_comment="订单已支付金额，单位为分")
    refunded_amount_minor = models.BigIntegerField(default=0, db_comment="订单已退款金额，单位为分")
    status = models.CharField(
        max_length=32,
        choices=Status.choices,
        default=Status.PENDING_PAYMENT,
        db_comment="订单状态",
    )
    note = models.CharField(max_length=500, blank=True, default="", db_comment="用户预约备注")
    reject_reason = models.CharField(
        max_length=500, blank=True, default="", db_comment="服务者拒绝原因"
    )
    version = models.PositiveIntegerField(default=1, db_comment="订单乐观锁版本号")
    idempotency_key = models.CharField(
        max_length=128, null=True, blank=True, db_comment="下单请求幂等键"
    )
    request_fingerprint = models.CharField(max_length=64, db_comment="下单请求一致性摘要")
    created_at = models.DateTimeField(auto_now_add=True, db_comment="订单创建时间")
    updated_at = models.DateTimeField(auto_now=True, db_comment="订单最近更新时间")
    paid_at = models.DateTimeField(null=True, blank=True, db_comment="订单支付成功时间")
    completed_at = models.DateTimeField(null=True, blank=True, db_comment="订单完成时间")
    review_expires_at = models.DateTimeField(
        null=True,
        blank=True,
        db_comment="用户评价截止时间，订单完成后 7 天",
    )

    class Meta:
        db_table = "orders"
        db_table_comment = "用户预约订单主表"
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.UniqueConstraint(
                fields=["user", "idempotency_key"],
                name="uniq_order_user_idempotency",
            ),
            models.UniqueConstraint(
                fields=["schedule_slot"],
                condition=~models.Q(
                    status__in=[
                        "CANCELED",
                        "REFUNDED",
                    ]
                ),
                name="uniq_order_active_schedule_slot",
            ),
        ]
        indexes: ClassVar[list[models.Index]] = [
            models.Index(fields=["user", "status", "created_at"]),
            models.Index(fields=["provider_user", "status", "created_at"]),
        ]


class OrderScheduleSlot(models.Model):
    """订单实际锁定的连续小时时段关联表。"""

    id = models.BigAutoField(primary_key=True, db_comment="订单时段关联自增主键")
    order = models.ForeignKey(
        Order,
        on_delete=models.CASCADE,
        related_name="order_schedule_slots",
        db_comment="预约订单",
    )
    schedule_slot = models.ForeignKey(
        "scheduling.ScheduleSlot",
        on_delete=models.PROTECT,
        related_name="order_schedule_slots",
        db_comment="订单锁定的预约小时单元",
    )
    position = models.PositiveSmallIntegerField(db_comment="连续小时单元顺序，0 表示预约开始时段")
    created_at = models.DateTimeField(
        auto_now_add=True,
        db_comment="订单时段关联创建时间",
    )

    class Meta:
        db_table = "order_schedule_slots"
        db_table_comment = "订单与连续预约小时单元关联表"
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.UniqueConstraint(
                fields=["order", "schedule_slot"],
                name="uniq_order_schedule_slot",
            ),
            models.UniqueConstraint(
                fields=["order", "position"],
                name="uniq_order_schedule_slot_position",
            ),
        ]
        indexes: ClassVar[list[models.Index]] = [
            models.Index(fields=["schedule_slot", "order"]),
        ]


class OrderRefundRequest(models.Model):
    """用户退款申请和后台审核结果。"""

    class Status(models.TextChoices):
        PENDING = "PENDING", "待审核"
        REJECTED = "REJECTED", "审核拒绝"
        REFUNDED = "REFUNDED", "已退款"
        FAILED = "FAILED", "退款失败"
        CANCELED = "CANCELED", "用户撤销"

    id = models.BigAutoField(primary_key=True, db_comment="退款申请自增主键")
    request_no = models.UUIDField(
        default=uuid.uuid4,
        unique=True,
        editable=False,
        db_comment="对外退款申请业务 UUID",
    )
    order = models.ForeignKey(
        Order,
        on_delete=models.PROTECT,
        related_name="refund_requests",
        db_comment="申请退款的订单",
    )
    payment = models.ForeignKey(
        "payments.Payment",
        on_delete=models.PROTECT,
        related_name="order_refund_requests",
        db_comment="申请退款的已成功支付单",
    )
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="submitted_refund_requests",
        db_comment="提交退款申请的用户",
    )
    reason = models.CharField(max_length=500, db_comment="用户退款申请原因")
    status = models.CharField(
        max_length=16,
        choices=Status.choices,
        default=Status.PENDING,
        db_comment="退款申请状态：待审核、拒绝、已退款、失败或用户撤销",
    )
    currency = models.CharField(max_length=3, default="CNY", db_comment="退款币种")
    refund_amount_minor = models.PositiveBigIntegerField(
        db_comment="申请退款金额，单位为币种最小单位，CNY 为分"
    )
    reviewed_by_user_id = models.BigIntegerField(
        null=True,
        blank=True,
        db_comment="执行后台审核的管理员用户主键",
    )
    review_note = models.CharField(
        max_length=500,
        blank=True,
        default="",
        db_comment="后台同意或拒绝说明",
    )
    reviewed_at = models.DateTimeField(
        null=True,
        blank=True,
        db_comment="后台审核完成时间",
    )
    payment_refund = models.ForeignKey(
        "payments.Refund",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="order_refund_requests",
        db_comment="退款成功后的支付退款记录",
    )
    failure_reason = models.CharField(
        max_length=500,
        blank=True,
        default="",
        db_comment="退款执行失败原因",
    )
    version = models.PositiveIntegerField(default=1, db_comment="退款申请乐观锁版本号")
    idempotency_key = models.CharField(
        max_length=128,
        null=True,
        blank=True,
        db_comment="退款申请幂等键，按用户隔离重复提交",
    )
    request_fingerprint = models.CharField(
        max_length=64,
        db_comment="退款申请订单、原因和版本一致性摘要",
    )
    created_at = models.DateTimeField(auto_now_add=True, db_comment="退款申请创建时间")
    updated_at = models.DateTimeField(auto_now=True, db_comment="退款申请最近更新时间")

    class Meta:
        db_table = "order_refund_requests"
        db_table_comment = "用户订单退款申请和后台审核表"
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.UniqueConstraint(
                fields=["requested_by", "idempotency_key"],
                name="uniq_order_refund_request_user_idempotency",
            ),
            models.UniqueConstraint(
                fields=["order"],
                condition=models.Q(status="PENDING"),
                name="uniq_order_refund_request_active",
            ),
            models.CheckConstraint(
                condition=models.Q(refund_amount_minor__gt=0),
                name="check_order_refund_request_amount_positive",
            ),
        ]
        indexes: ClassVar[list[models.Index]] = [
            models.Index(fields=["status", "created_at"]),
            models.Index(fields=["order", "status", "created_at"]),
        ]


class OrderStatusLog(models.Model):
    """订单状态变更追加事件。"""

    class EventType(models.TextChoices):
        CREATED = "CREATED", "创建"
        PAID = "PAID", "支付"
        ACCEPTED = "ACCEPTED", "接单"
        REJECTED = "REJECTED", "拒绝"
        STARTED = "STARTED", "开始履约"
        COMPLETED_BY_PROVIDER = "COMPLETED_BY_PROVIDER", "服务者完成"
        CONFIRMED = "CONFIRMED", "用户确认完成"
        CANCELED = "CANCELED", "取消"
        REFUNDED = "REFUNDED", "退款"

    id = models.BigAutoField(primary_key=True, db_comment="订单事件自增主键")
    order = models.ForeignKey(
        Order,
        on_delete=models.CASCADE,
        related_name="status_logs",
        db_comment="事件所属订单",
    )
    event_type = models.CharField(
        max_length=32,
        choices=EventType.choices,
        db_comment="订单事件类型",
    )
    from_status = models.CharField(
        max_length=32, blank=True, default="", db_comment="事件前订单状态"
    )
    to_status = models.CharField(max_length=32, db_comment="事件后订单状态")
    actor_user_id = models.BigIntegerField(null=True, blank=True, db_comment="执行事件的用户主键")
    reason = models.CharField(max_length=500, blank=True, default="", db_comment="事件原因")
    trace_id = models.CharField(
        max_length=64, blank=True, default="", db_comment="事件请求追踪标识"
    )
    created_at = models.DateTimeField(auto_now_add=True, db_comment="订单事件创建时间")

    class Meta:
        db_table = "order_status_logs"
        db_table_comment = "订单状态变更事件表"
        ordering: ClassVar[list[str]] = ["created_at", "id"]
