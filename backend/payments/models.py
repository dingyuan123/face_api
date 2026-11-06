from __future__ import annotations

import uuid
from typing import ClassVar

from django.conf import settings
from django.db import models


class Payment(models.Model):
    """订单支付单，当前支持内部钱包余额渠道。"""

    class Method(models.TextChoices):
        BALANCE = "BALANCE", "钱包余额"

    class Status(models.TextChoices):
        PENDING = "PENDING", "待支付"
        SUCCESS = "SUCCESS", "支付成功"
        FAILED = "FAILED", "支付失败"
        CLOSED = "CLOSED", "已关闭"
        REFUNDED = "REFUNDED", "已退款"

    id = models.BigAutoField(primary_key=True, db_comment="支付单自增主键")
    payment_no = models.UUIDField(
        default=uuid.uuid4,
        unique=True,
        editable=False,
        db_comment="对外支付单 UUID",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="payments",
        db_comment="付款用户",
    )
    order_no = models.CharField(max_length=64, db_comment="关联订单业务单号")
    payment_method = models.CharField(
        max_length=32,
        choices=Method.choices,
        default=Method.BALANCE,
        db_comment="支付方式；当前支持钱包余额",
    )
    payment_channel = models.CharField(
        max_length=32,
        default="INTERNAL",
        db_comment="支付渠道；当前为内部余额，未来可扩展微信或支付宝",
    )
    currency = models.CharField(max_length=3, default="CNY", db_comment="支付币种")
    amount_minor = models.BigIntegerField(db_comment="支付金额，单位为分")
    status = models.CharField(
        max_length=16,
        choices=Status.choices,
        default=Status.PENDING,
        db_comment="支付单状态",
    )
    channel_transaction_no = models.CharField(
        max_length=128,
        blank=True,
        default="",
        db_comment="支付渠道交易号；余额支付为空",
    )
    idempotency_key = models.CharField(max_length=128, db_comment="支付请求幂等键")
    request_fingerprint = models.CharField(max_length=64, db_comment="支付请求一致性摘要")
    version = models.PositiveIntegerField(default=1, db_comment="支付单乐观锁版本号")
    paid_at = models.DateTimeField(null=True, blank=True, db_comment="支付成功时间")
    created_at = models.DateTimeField(auto_now_add=True, db_comment="支付单创建时间")
    updated_at = models.DateTimeField(auto_now=True, db_comment="支付单最近更新时间")

    class Meta:
        db_table = "payments"
        db_table_comment = "订单支付单表"
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.UniqueConstraint(
                fields=["user", "idempotency_key"],
                name="uniq_payment_user_idempotency",
            ),
            models.UniqueConstraint(
                fields=["order_no", "status"],
                condition=models.Q(status="SUCCESS"),
                name="uniq_payment_successful_order",
            ),
            models.CheckConstraint(
                condition=models.Q(amount_minor__gt=0),
                name="check_payment_amount_positive",
            ),
        ]
        indexes: ClassVar[list[models.Index]] = [
            models.Index(fields=["user", "created_at"]),
            models.Index(fields=["order_no", "status"]),
        ]


class Refund(models.Model):
    """支付退款单，当前钱包余额原路退回。"""

    class Method(models.TextChoices):
        BALANCE = "BALANCE", "钱包余额"

    class Status(models.TextChoices):
        PENDING = "PENDING", "退款中"
        SUCCESS = "SUCCESS", "退款成功"
        FAILED = "FAILED", "退款失败"

    id = models.BigAutoField(primary_key=True, db_comment="退款单自增主键")
    refund_no = models.UUIDField(
        default=uuid.uuid4,
        unique=True,
        editable=False,
        db_comment="对外退款单 UUID",
    )
    payment = models.ForeignKey(
        Payment,
        on_delete=models.PROTECT,
        related_name="refunds",
        db_comment="关联支付单",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="refunds",
        db_comment="退款收款用户",
    )
    order_no = models.CharField(max_length=64, db_comment="关联订单业务单号")
    refund_method = models.CharField(
        max_length=32,
        choices=Method.choices,
        default=Method.BALANCE,
        db_comment="退款方式；余额支付原路退回钱包",
    )
    currency = models.CharField(max_length=3, default="CNY", db_comment="退款币种")
    refund_amount_minor = models.BigIntegerField(db_comment="退款金额，单位为分")
    status = models.CharField(
        max_length=16,
        choices=Status.choices,
        default=Status.SUCCESS,
        db_comment="退款单状态",
    )
    idempotency_key = models.CharField(max_length=128, db_comment="退款请求幂等键")
    created_at = models.DateTimeField(auto_now_add=True, db_comment="退款单创建时间")
    completed_at = models.DateTimeField(auto_now_add=True, db_comment="退款完成时间")

    class Meta:
        db_table = "refunds"
        db_table_comment = "支付退款单表"
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.UniqueConstraint(
                fields=["payment", "idempotency_key"],
                name="uniq_refund_payment_idempotency",
            ),
            models.CheckConstraint(
                condition=models.Q(refund_amount_minor__gt=0),
                name="check_refund_amount_positive",
            ),
        ]
