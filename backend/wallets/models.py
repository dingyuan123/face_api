from __future__ import annotations

import uuid
from typing import ClassVar

from django.conf import settings
from django.db import models


class WalletAccount(models.Model):
    """用户钱包余额账户。"""

    id = models.BigAutoField(primary_key=True, db_comment="钱包账户自增主键")
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="wallet_accounts",
        db_comment="钱包所属用户",
    )
    currency = models.CharField(max_length=3, default="CNY", db_comment="钱包币种代码")
    balance_amount_minor = models.BigIntegerField(
        default=0,
        db_comment="当前钱包余额，单位为币种最小单位，CNY 为分",
    )
    frozen_amount_minor = models.BigIntegerField(
        default=0,
        db_comment="冻结金额，单位为币种最小单位，当前支付策略暂不冻结",
    )
    version = models.PositiveIntegerField(default=1, db_comment="钱包乐观锁版本号")
    created_at = models.DateTimeField(auto_now_add=True, db_comment="钱包创建时间")
    updated_at = models.DateTimeField(auto_now=True, db_comment="钱包最近更新时间")

    class Meta:
        db_table = "wallet_accounts"
        db_table_comment = "用户钱包余额账户表"
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.UniqueConstraint(
                fields=["user", "currency"],
                name="uniq_wallet_user_currency",
            ),
            models.CheckConstraint(
                condition=models.Q(balance_amount_minor__gte=0),
                name="check_wallet_balance_non_negative",
            ),
            models.CheckConstraint(
                condition=models.Q(frozen_amount_minor__gte=0),
                name="check_wallet_frozen_non_negative",
            ),
        ]

    @property
    def available_amount_minor(self) -> int:
        """返回可用于支付的余额。"""

        return self.balance_amount_minor - self.frozen_amount_minor


class WalletTransaction(models.Model):
    """钱包不可变资金流水。"""

    class Direction(models.TextChoices):
        CREDIT = "CREDIT", "入账"
        DEBIT = "DEBIT", "出账"

    class TransactionType(models.TextChoices):
        TOPUP = "TOPUP", "测试充值"
        ORDER_PAYMENT = "ORDER_PAYMENT", "订单支付"
        ORDER_REFUND = "ORDER_REFUND", "订单退款"
        ADJUSTMENT = "ADJUSTMENT", "人工调整"

    id = models.BigAutoField(primary_key=True, db_comment="钱包流水自增主键")
    transaction_no = models.UUIDField(
        default=uuid.uuid4,
        unique=True,
        editable=False,
        db_comment="对外钱包流水 UUID",
    )
    account = models.ForeignKey(
        WalletAccount,
        on_delete=models.PROTECT,
        related_name="transactions",
        db_comment="资金变动的钱包账户",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="wallet_transactions",
        db_comment="钱包流水所属用户",
    )
    direction = models.CharField(
        max_length=8,
        choices=Direction.choices,
        db_comment="资金方向：入账或出账",
    )
    transaction_type = models.CharField(
        max_length=32,
        choices=TransactionType.choices,
        db_comment="钱包交易类型",
    )
    business_type = models.CharField(max_length=32, db_comment="关联业务类型")
    business_no = models.CharField(max_length=64, db_comment="关联充值、订单、支付或退款单号")
    currency = models.CharField(max_length=3, default="CNY", db_comment="钱包流水币种")
    amount_minor = models.BigIntegerField(db_comment="变动金额，必须大于 0，单位为分")
    balance_after_amount_minor = models.BigIntegerField(
        db_comment="变动后钱包余额，单位为分",
    )
    idempotency_key = models.CharField(max_length=128, db_comment="资金流水幂等键")
    request_fingerprint = models.CharField(max_length=64, db_comment="资金请求一致性摘要")
    trace_id = models.CharField(
        max_length=64, blank=True, default="", db_comment="资金请求追踪标识"
    )
    created_at = models.DateTimeField(auto_now_add=True, db_comment="钱包流水创建时间")

    class Meta:
        db_table = "wallet_transactions"
        db_table_comment = "钱包不可变资金流水表"
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.UniqueConstraint(
                fields=["account", "business_type", "business_no", "idempotency_key"],
                name="uniq_wallet_transaction_business_idempotency",
            ),
            models.CheckConstraint(
                condition=models.Q(amount_minor__gt=0),
                name="check_wallet_transaction_amount_positive",
            ),
        ]
        indexes: ClassVar[list[models.Index]] = [
            models.Index(fields=["user", "created_at"]),
            models.Index(fields=["business_type", "business_no"]),
        ]


class WalletTopUp(models.Model):
    """开发测试余额充值记录。"""

    class Status(models.TextChoices):
        SUCCESS = "SUCCESS", "成功"

    id = models.BigAutoField(primary_key=True, db_comment="测试充值自增主键")
    topup_no = models.UUIDField(
        default=uuid.uuid4,
        unique=True,
        editable=False,
        db_comment="对外测试充值单 UUID",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="wallet_topups",
        db_comment="获得测试余额的用户",
    )
    account = models.ForeignKey(
        WalletAccount,
        on_delete=models.PROTECT,
        related_name="topups",
        db_comment="入账钱包账户",
    )
    currency = models.CharField(max_length=3, default="CNY", db_comment="充值币种")
    amount_minor = models.BigIntegerField(db_comment="测试充值金额，单位为分")
    channel = models.CharField(max_length=32, default="DEV_MOCK", db_comment="测试充值渠道标识")
    status = models.CharField(
        max_length=16,
        choices=Status.choices,
        default=Status.SUCCESS,
        db_comment="测试充值状态",
    )
    idempotency_key = models.CharField(max_length=128, db_comment="测试充值幂等键")
    reason = models.CharField(max_length=200, blank=True, default="", db_comment="测试充值原因")
    created_by_user_id = models.BigIntegerField(db_comment="创建测试充值的管理员用户主键")
    created_at = models.DateTimeField(auto_now_add=True, db_comment="测试充值创建时间")
    completed_at = models.DateTimeField(auto_now_add=True, db_comment="测试充值完成时间")

    class Meta:
        db_table = "wallet_topups"
        db_table_comment = "开发测试余额充值记录表"
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.UniqueConstraint(
                fields=["user", "idempotency_key"],
                name="uniq_wallet_topup_user_idempotency",
            ),
            models.CheckConstraint(
                condition=models.Q(amount_minor__gt=0),
                name="check_wallet_topup_amount_positive",
            ),
        ]
