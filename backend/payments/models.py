from __future__ import annotations

import uuid
from typing import ClassVar

from django.conf import settings
from django.db import models


class Payment(models.Model):
    """订单、会员购买等业务支付单，支持钱包余额、微信 App 支付和支付宝 App 支付。"""

    class Method(models.TextChoices):
        BALANCE = "BALANCE", "钱包余额"
        WECHAT_APP = "WECHAT_APP", "微信 App 支付"
        ALIPAY_APP = "ALIPAY_APP", "支付宝 App 支付"

    class BusinessType(models.TextChoices):
        ORDER = "ORDER", "预约订单"
        MEMBERSHIP_PURCHASE = "MEMBERSHIP_PURCHASE", "会员购买"

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
    order_no = models.CharField(
        max_length=64,
        db_comment="兼容字段：订单号或会员购买单号；新代码以 business_type 和 business_no 为准",
    )
    business_type = models.CharField(
        max_length=32,
        choices=BusinessType.choices,
        default=BusinessType.ORDER,
        db_comment="支付关联业务类型：预约订单或会员购买",
    )
    business_no = models.CharField(
        max_length=64,
        blank=True,
        default="",
        db_comment="支付关联业务单号；订单为 order_no，会员购买为 purchase_no",
    )
    payment_method = models.CharField(
        max_length=32,
        choices=Method.choices,
        default=Method.BALANCE,
        db_comment="支付方式：钱包余额、微信 App 支付或支付宝 App 支付",
    )
    payment_channel = models.CharField(
        max_length=32,
        default="INTERNAL",
        db_comment="支付渠道：内部余额、微信支付或支付宝",
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
        db_comment="微信交易号或支付宝交易号；余额支付为空，成功后全局可追溯",
    )
    channel_reference = models.CharField(
        max_length=128,
        blank=True,
        default="",
        db_comment="支付渠道预支付标识或内部调用引用；不保存渠道密钥",
    )
    client_payload = models.JSONField(
        default=dict,
        blank=True,
        db_comment="返回给原生支付 SDK 的一次性支付参数；不保存商户私钥或 API 密钥",
    )
    channel_status = models.CharField(
        max_length=32,
        blank=True,
        default="",
        db_comment="支付渠道原始业务状态，仅用于诊断和对账，不替代平台支付状态",
    )
    failure_reason = models.CharField(
        max_length=500,
        blank=True,
        default="",
        db_comment="支付创建或回调失败原因；不保存完整第三方响应或敏感凭据",
    )
    idempotency_key = models.CharField(max_length=128, db_comment="支付请求幂等键")
    request_fingerprint = models.CharField(max_length=64, db_comment="支付请求一致性摘要")
    version = models.PositiveIntegerField(default=1, db_comment="支付单乐观锁版本号")
    paid_at = models.DateTimeField(null=True, blank=True, db_comment="支付成功时间")
    expires_at = models.DateTimeField(
        null=True,
        blank=True,
        db_comment="第三方预支付参数失效时间；余额支付为空",
    )
    created_at = models.DateTimeField(auto_now_add=True, db_comment="支付单创建时间")
    updated_at = models.DateTimeField(auto_now=True, db_comment="支付单最近更新时间")

    class Meta:
        db_table = "payments"
        db_table_comment = "预约订单和会员购买业务支付单表"
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
            models.UniqueConstraint(
                fields=["business_type", "business_no", "status"],
                condition=models.Q(status="SUCCESS") & ~models.Q(business_no=""),
                name="uniq_payment_successful_business",
            ),
            models.UniqueConstraint(
                fields=["payment_channel", "channel_transaction_no"],
                condition=~models.Q(channel_transaction_no=""),
                name="uniq_payment_channel_transaction",
            ),
            models.CheckConstraint(
                condition=models.Q(amount_minor__gt=0),
                name="check_payment_amount_positive",
            ),
        ]
        indexes: ClassVar[list[models.Index]] = [
            models.Index(fields=["user", "created_at"]),
            models.Index(fields=["order_no", "status"]),
            models.Index(fields=["business_type", "business_no", "status"]),
        ]


class Refund(models.Model):
    """支付退款单，按原支付渠道退回钱包、微信支付或支付宝。"""

    class Method(models.TextChoices):
        BALANCE = "BALANCE", "钱包余额"
        WECHAT_APP = "WECHAT_APP", "微信 App 支付"
        ALIPAY_APP = "ALIPAY_APP", "支付宝 App 支付"

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
    order_no = models.CharField(max_length=64, db_comment="关联预约订单业务单号")
    refund_method = models.CharField(
        max_length=32,
        choices=Method.choices,
        default=Method.BALANCE,
        db_comment="退款方式，必须与支付单原支付渠道一致",
    )
    currency = models.CharField(max_length=3, default="CNY", db_comment="退款币种")
    refund_amount_minor = models.BigIntegerField(db_comment="退款金额，单位为分")
    status = models.CharField(
        max_length=16,
        choices=Status.choices,
        default=Status.PENDING,
        db_comment="退款单状态",
    )
    channel_refund_no = models.CharField(
        max_length=128,
        blank=True,
        default="",
        db_comment="微信退款单号或支付宝退款流水号；余额退款为空",
    )
    channel_status = models.CharField(
        max_length=32,
        blank=True,
        default="",
        db_comment="退款渠道原始业务状态，仅用于诊断和对账",
    )
    failure_reason = models.CharField(
        max_length=500,
        blank=True,
        default="",
        db_comment="退款失败或渠道拒绝原因；不保存完整敏感响应",
    )
    idempotency_key = models.CharField(max_length=128, db_comment="退款请求幂等键")
    created_at = models.DateTimeField(auto_now_add=True, db_comment="退款单创建时间")
    completed_at = models.DateTimeField(
        null=True,
        blank=True,
        db_comment="退款成功确认时间；处理中或失败时为空",
    )

    class Meta:
        db_table = "refunds"
        db_table_comment = "支付退款单表"
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.UniqueConstraint(
                fields=["payment", "idempotency_key"],
                name="uniq_refund_payment_idempotency",
            ),
            models.UniqueConstraint(
                fields=["payment", "channel_refund_no"],
                condition=~models.Q(channel_refund_no=""),
                name="uniq_refund_payment_channel_refund",
            ),
            models.CheckConstraint(
                condition=models.Q(refund_amount_minor__gt=0),
                name="check_refund_amount_positive",
            ),
        ]
