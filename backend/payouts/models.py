"""收款方式、收入账本和提现单据的数据模型。"""

from __future__ import annotations

import uuid
from typing import ClassVar

from django.conf import settings
from django.db import models


class PayoutMethod(models.Model):
    """普通用户和服务者共用的收款方式绑定。"""

    class MethodType(models.TextChoices):
        BANK_CARD = "BANK_CARD", "银行卡"
        ALIPAY = "ALIPAY", "支付宝"
        WECHAT_PAY = "WECHAT_PAY", "微信支付"

    class Status(models.TextChoices):
        ACTIVE = "ACTIVE", "启用"
        INACTIVE = "INACTIVE", "已停用"

    class VerificationStatus(models.TextChoices):
        VERIFIED = "VERIFIED", "模拟验证通过"
        FAILED = "FAILED", "验证失败"

    class BindingMode(models.TextChoices):
        MANUAL = "MANUAL", "手动录入"
        OAUTH = "OAUTH", "渠道授权"

    id = models.BigAutoField(primary_key=True, db_comment="收款方式自增主键")
    public_id = models.UUIDField(
        default=uuid.uuid4,
        unique=True,
        editable=False,
        db_comment="对外收款方式 UUID",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="payout_methods",
        db_comment="收款方式所属用户，普通用户和服务者共用",
    )
    method_type = models.CharField(
        max_length=32,
        choices=MethodType.choices,
        db_comment="收款方式类型：银行卡、支付宝或微信支付",
    )
    binding_mode = models.CharField(
        max_length=16,
        choices=BindingMode.choices,
        default=BindingMode.MANUAL,
        db_comment="绑定方式；当前为手动录入，后续支持渠道授权",
    )
    status = models.CharField(
        max_length=16,
        choices=Status.choices,
        default=Status.ACTIVE,
        db_comment="收款方式状态，停用后保留历史提现快照",
    )
    verification_status = models.CharField(
        max_length=16,
        choices=VerificationStatus.choices,
        default=VerificationStatus.VERIFIED,
        db_comment="收款账户验证状态；当前测试阶段使用模拟验证",
    )
    is_default = models.BooleanField(default=False, db_comment="是否为当前默认收款方式")
    account_name_encrypted = models.TextField(db_comment="账户姓名 Fernet 密文，不保存明文")
    account_name_masked = models.CharField(max_length=64, db_comment="账户姓名脱敏展示值")
    account_number_encrypted = models.TextField(
        db_comment="银行卡号、支付宝账号或微信账号 Fernet 密文，不保存明文",
    )
    account_number_masked = models.CharField(
        max_length=128,
        db_comment="收款账号脱敏展示值，接口只返回该字段",
    )
    institution_name = models.CharField(
        max_length=100,
        blank=True,
        default="",
        db_comment="银行或支付渠道展示名称",
    )
    account_fingerprint = models.CharField(
        max_length=64,
        db_comment="收款账号 HMAC 指纹，用于防止重复绑定且不保存明文摘要",
    )
    display_text = models.CharField(max_length=160, db_comment="前端安全展示文案")
    version = models.PositiveIntegerField(default=1, db_comment="收款方式乐观锁版本号")
    idempotency_key = models.CharField(
        max_length=128,
        null=True,
        blank=True,
        db_comment="创建收款方式幂等键，按用户隔离",
    )
    request_fingerprint = models.CharField(
        max_length=64,
        db_comment="收款方式创建请求一致性摘要",
    )
    created_at = models.DateTimeField(auto_now_add=True, db_comment="收款方式创建时间")
    updated_at = models.DateTimeField(auto_now=True, db_comment="收款方式最近更新时间")
    deactivated_at = models.DateTimeField(
        null=True,
        blank=True,
        db_comment="收款方式停用时间，空值表示仍可使用",
    )

    class Meta:
        db_table = "payout_methods"
        db_table_comment = "普通用户和服务者共用收款方式绑定表"
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.UniqueConstraint(
                fields=["user", "idempotency_key"],
                name="uniq_payout_method_user_idempotency",
            ),
            models.UniqueConstraint(
                fields=["user", "method_type", "account_fingerprint"],
                name="uniq_payout_method_user_account",
            ),
            models.UniqueConstraint(
                fields=["user"],
                condition=models.Q(status="ACTIVE", is_default=True),
                name="uniq_payout_method_active_default",
            ),
        ]
        indexes: ClassVar[list[models.Index]] = [
            models.Index(fields=["user", "status", "created_at"]),
        ]


class PayoutMethodEvent(models.Model):
    """收款方式绑定、设为默认和停用的审计事件。"""

    class EventType(models.TextChoices):
        CREATED = "CREATED", "创建绑定"
        SET_DEFAULT = "SET_DEFAULT", "设为默认"
        DEACTIVATED = "DEACTIVATED", "停用"

    id = models.BigAutoField(primary_key=True, db_comment="收款方式事件自增主键")
    payout_method = models.ForeignKey(
        PayoutMethod,
        on_delete=models.CASCADE,
        related_name="events",
        db_comment="事件关联收款方式",
    )
    event_type = models.CharField(
        max_length=32,
        choices=EventType.choices,
        db_comment="收款方式事件类型",
    )
    actor_user_id = models.BigIntegerField(db_comment="执行事件的用户主键")
    reason = models.CharField(max_length=200, blank=True, default="", db_comment="事件原因")
    trace_id = models.CharField(
        max_length=64,
        blank=True,
        default="",
        db_comment="事件请求追踪标识",
    )
    created_at = models.DateTimeField(auto_now_add=True, db_comment="事件创建时间")

    class Meta:
        db_table = "payout_method_events"
        db_table_comment = "收款方式绑定和启停审计事件表"
        ordering: ClassVar[list[str]] = ["created_at", "id"]


class EarningAccount(models.Model):
    """服务者收入或普通用户推广收益账户。"""

    class AccountType(models.TextChoices):
        PROVIDER_INCOME = "PROVIDER_INCOME", "服务者收入"
        REFERRAL_REWARD = "REFERRAL_REWARD", "推广收益"

    id = models.BigAutoField(primary_key=True, db_comment="收益账户自增主键")
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="earning_accounts",
        db_comment="收益账户所属用户",
    )
    account_type = models.CharField(
        max_length=32,
        choices=AccountType.choices,
        db_comment="收益账户类型：服务者收入或推广收益",
    )
    currency = models.CharField(max_length=3, default="CNY", db_comment="收益账户币种")
    available_amount_minor = models.BigIntegerField(
        default=0,
        db_comment="可提现金额，单位为币种最小单位，CNY 为分",
    )
    frozen_amount_minor = models.BigIntegerField(
        default=0,
        db_comment="提现申请冻结金额，单位为币种最小单位，CNY 为分",
    )
    total_income_amount_minor = models.BigIntegerField(
        default=0,
        db_comment="累计已结算收入金额，单位为币种最小单位，CNY 为分",
    )
    total_withdrawn_amount_minor = models.BigIntegerField(
        default=0,
        db_comment="累计提现成功金额，单位为币种最小单位，CNY 为分",
    )
    version = models.PositiveIntegerField(default=1, db_comment="收益账户乐观锁版本号")
    created_at = models.DateTimeField(auto_now_add=True, db_comment="收益账户创建时间")
    updated_at = models.DateTimeField(auto_now=True, db_comment="收益账户最近更新时间")

    class Meta:
        db_table = "earning_accounts"
        db_table_comment = "服务者收入和普通用户推广收益账户表"
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.UniqueConstraint(
                fields=["user", "account_type", "currency"],
                name="uniq_earning_account_user_type_currency",
            ),
            models.CheckConstraint(
                condition=models.Q(available_amount_minor__gte=0),
                name="check_earning_account_available_non_negative",
            ),
            models.CheckConstraint(
                condition=models.Q(frozen_amount_minor__gte=0),
                name="check_earning_account_frozen_non_negative",
            ),
            models.CheckConstraint(
                condition=models.Q(total_income_amount_minor__gte=0),
                name="check_earning_account_income_non_negative",
            ),
            models.CheckConstraint(
                condition=models.Q(total_withdrawn_amount_minor__gte=0),
                name="check_earning_account_withdrawn_non_negative",
            ),
        ]


class EarningEntry(models.Model):
    """单笔待结算或已结算收益业务记录。"""

    class Status(models.TextChoices):
        PENDING_SETTLEMENT = "PENDING_SETTLEMENT", "待结算"
        AVAILABLE = "AVAILABLE", "已结算"
        CANCELED = "CANCELED", "已取消"

    id = models.BigAutoField(primary_key=True, db_comment="收益业务记录自增主键")
    earning_no = models.UUIDField(
        default=uuid.uuid4,
        unique=True,
        editable=False,
        db_comment="对外收益业务 UUID",
    )
    account = models.ForeignKey(
        EarningAccount,
        on_delete=models.PROTECT,
        related_name="entries",
        db_comment="收益入账账户",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="earning_entries",
        db_comment="收益所属用户",
    )
    business_type = models.CharField(max_length=32, db_comment="收益来源业务类型")
    business_no = models.CharField(max_length=64, db_comment="收益来源订单或奖励业务单号")
    currency = models.CharField(max_length=3, default="CNY", db_comment="收益币种")
    gross_amount_minor = models.BigIntegerField(
        db_comment="收益计算前业务金额，单位为币种最小单位，CNY 为分",
    )
    platform_fee_amount_minor = models.BigIntegerField(
        default=0,
        db_comment="平台佣金或服务费，单位为币种最小单位，CNY 为分",
    )
    net_amount_minor = models.BigIntegerField(
        db_comment="实际入账收益金额，单位为币种最小单位，CNY 为分",
    )
    status = models.CharField(
        max_length=32,
        choices=Status.choices,
        default=Status.PENDING_SETTLEMENT,
        db_comment="收益结算状态",
    )
    available_at = models.DateTimeField(db_comment="最早可结算时间")
    settled_at = models.DateTimeField(null=True, blank=True, db_comment="实际结算入账时间")
    rule_snapshot = models.JSONField(default=dict, db_comment="收益计算规则和订单金额快照")
    idempotency_key = models.CharField(max_length=128, db_comment="收益记录幂等键")
    request_fingerprint = models.CharField(
        max_length=64,
        db_comment="收益计算请求一致性摘要",
    )
    created_at = models.DateTimeField(auto_now_add=True, db_comment="收益记录创建时间")
    updated_at = models.DateTimeField(auto_now=True, db_comment="收益记录最近更新时间")

    class Meta:
        db_table = "earning_entries"
        db_table_comment = "服务者收入和推广收益业务记录表"
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.UniqueConstraint(
                fields=["account", "business_type", "business_no", "idempotency_key"],
                name="uniq_earning_entry_business_idempotency",
            ),
            models.UniqueConstraint(
                fields=["account", "business_type", "business_no"],
                name="uniq_earning_entry_account_business",
            ),
            models.CheckConstraint(
                condition=models.Q(gross_amount_minor__gte=0),
                name="check_earning_entry_gross_non_negative",
            ),
            models.CheckConstraint(
                condition=models.Q(platform_fee_amount_minor__gte=0),
                name="check_earning_entry_fee_non_negative",
            ),
            models.CheckConstraint(
                condition=models.Q(net_amount_minor__gte=0),
                name="check_earning_entry_net_non_negative",
            ),
        ]
        indexes: ClassVar[list[models.Index]] = [
            models.Index(fields=["status", "available_at"]),
            models.Index(fields=["user", "created_at"]),
        ]


class EarningTransaction(models.Model):
    """收益账户不可变资金流水。"""

    class Direction(models.TextChoices):
        CREDIT = "CREDIT", "入账"
        DEBIT = "DEBIT", "出账"
        HOLD = "HOLD", "冻结"
        RELEASE = "RELEASE", "解冻"

    class TransactionType(models.TextChoices):
        INCOME = "INCOME", "收益结算"
        WITHDRAWAL_HOLD = "WITHDRAWAL_HOLD", "提现冻结"
        WITHDRAWAL_RELEASE = "WITHDRAWAL_RELEASE", "提现解冻"
        WITHDRAWAL_PAYOUT = "WITHDRAWAL_PAYOUT", "提现打款"
        ADJUSTMENT = "ADJUSTMENT", "人工调整"

    id = models.BigAutoField(primary_key=True, db_comment="收益流水自增主键")
    transaction_no = models.UUIDField(
        default=uuid.uuid4,
        unique=True,
        editable=False,
        db_comment="对外收益流水 UUID",
    )
    account = models.ForeignKey(
        EarningAccount,
        on_delete=models.PROTECT,
        related_name="transactions",
        db_comment="资金变动的收益账户",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="earning_transactions",
        db_comment="收益流水所属用户",
    )
    direction = models.CharField(
        max_length=8,
        choices=Direction.choices,
        db_comment="资金方向：入账、出账、冻结或解冻",
    )
    transaction_type = models.CharField(
        max_length=32,
        choices=TransactionType.choices,
        db_comment="收益流水业务类型",
    )
    business_type = models.CharField(max_length=32, db_comment="关联收益、提现或调整业务类型")
    business_no = models.CharField(max_length=64, db_comment="关联收益、提现或调整业务单号")
    currency = models.CharField(max_length=3, default="CNY", db_comment="收益流水币种")
    amount_minor = models.BigIntegerField(
        db_comment="变动金额，必须大于 0，单位为币种最小单位，CNY 为分",
    )
    available_after_amount_minor = models.BigIntegerField(
        db_comment="变动后可提现金额，单位为币种最小单位，CNY 为分",
    )
    frozen_after_amount_minor = models.BigIntegerField(
        db_comment="变动后冻结金额，单位为币种最小单位，CNY 为分",
    )
    total_income_after_amount_minor = models.BigIntegerField(
        db_comment="变动后累计收入金额，单位为币种最小单位，CNY 为分",
    )
    total_withdrawn_after_amount_minor = models.BigIntegerField(
        db_comment="变动后累计提现金额，单位为币种最小单位，CNY 为分",
    )
    idempotency_key = models.CharField(max_length=128, db_comment="收益流水幂等键")
    request_fingerprint = models.CharField(
        max_length=64,
        db_comment="收益资金请求一致性摘要",
    )
    trace_id = models.CharField(
        max_length=64,
        blank=True,
        default="",
        db_comment="收益资金请求追踪标识",
    )
    created_at = models.DateTimeField(auto_now_add=True, db_comment="收益流水创建时间")

    class Meta:
        db_table = "earning_transactions"
        db_table_comment = "收益账户不可变资金流水表"
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.UniqueConstraint(
                fields=["account", "business_type", "business_no", "idempotency_key"],
                name="uniq_earning_transaction_business_idempotency",
            ),
            models.CheckConstraint(
                condition=models.Q(amount_minor__gt=0),
                name="check_earning_transaction_amount_positive",
            ),
        ]
        indexes: ClassVar[list[models.Index]] = [
            models.Index(fields=["user", "created_at"]),
            models.Index(fields=["business_type", "business_no"]),
        ]


class Withdrawal(models.Model):
    """普通用户推广收益或服务者收入提现申请。"""

    class Status(models.TextChoices):
        PENDING_REVIEW = "PENDING_REVIEW", "待人工审核"
        PROCESSING = "PROCESSING", "打款处理中"
        SUCCESS = "SUCCESS", "提现成功"
        FAILED = "FAILED", "打款失败"
        REJECTED = "REJECTED", "审核拒绝"
        CANCELED = "CANCELED", "用户撤销"

    id = models.BigAutoField(primary_key=True, db_comment="提现单自增主键")
    withdrawal_no = models.UUIDField(
        default=uuid.uuid4,
        unique=True,
        editable=False,
        db_comment="对外提现业务 UUID",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="withdrawals",
        db_comment="提现申请用户",
    )
    account = models.ForeignKey(
        EarningAccount,
        on_delete=models.PROTECT,
        related_name="withdrawals",
        db_comment="提现扣减的收益账户",
    )
    payout_method = models.ForeignKey(
        PayoutMethod,
        on_delete=models.PROTECT,
        related_name="withdrawals",
        db_comment="提现使用的收款方式",
    )
    payout_method_snapshot_encrypted = models.TextField(
        db_comment="提现时收款账户密文快照，用于打款和审计，不写日志",
    )
    payout_method_display = models.CharField(
        max_length=160,
        db_comment="提现时收款账户脱敏展示快照",
    )
    currency = models.CharField(max_length=3, default="CNY", db_comment="提现币种")
    amount_minor = models.BigIntegerField(
        db_comment="申请提现总额，单位为币种最小单位，CNY 为分",
    )
    fee_amount_minor = models.BigIntegerField(
        default=0,
        db_comment="提现手续费，单位为币种最小单位，CNY 为分",
    )
    payout_amount_minor = models.BigIntegerField(
        db_comment="实际打款金额，单位为币种最小单位，CNY 为分",
    )
    status = models.CharField(
        max_length=32,
        choices=Status.choices,
        default=Status.PENDING_REVIEW,
        db_comment="提现状态",
    )
    reviewed_by_user_id = models.BigIntegerField(
        null=True,
        blank=True,
        db_comment="执行人工审核的管理员用户主键",
    )
    review_note = models.CharField(
        max_length=500,
        blank=True,
        default="",
        db_comment="人工审核或处理说明",
    )
    failure_reason = models.CharField(
        max_length=500,
        blank=True,
        default="",
        db_comment="打款失败原因",
    )
    channel_reference = models.CharField(
        max_length=128,
        blank=True,
        default="",
        db_comment="模拟或真实打款渠道流水号",
    )
    version = models.PositiveIntegerField(default=1, db_comment="提现单乐观锁版本号")
    idempotency_key = models.CharField(max_length=128, db_comment="提现申请幂等键")
    request_fingerprint = models.CharField(
        max_length=64,
        db_comment="提现申请账户、金额和收款方式一致性摘要",
    )
    created_at = models.DateTimeField(auto_now_add=True, db_comment="提现申请创建时间")
    updated_at = models.DateTimeField(auto_now=True, db_comment="提现单最近更新时间")
    reviewed_at = models.DateTimeField(null=True, blank=True, db_comment="人工审核完成时间")
    completed_at = models.DateTimeField(null=True, blank=True, db_comment="提现最终完成时间")

    class Meta:
        db_table = "withdrawals"
        db_table_comment = "服务者收入和普通用户推广收益提现单表"
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.UniqueConstraint(
                fields=["user", "idempotency_key"],
                name="uniq_withdrawal_user_idempotency",
            ),
            models.CheckConstraint(
                condition=models.Q(amount_minor__gt=0),
                name="check_withdrawal_amount_positive",
            ),
            models.CheckConstraint(
                condition=models.Q(fee_amount_minor__gte=0),
                name="check_withdrawal_fee_non_negative",
            ),
            models.CheckConstraint(
                condition=models.Q(payout_amount_minor__gt=0),
                name="check_withdrawal_payout_amount_positive",
            ),
        ]
        indexes: ClassVar[list[models.Index]] = [
            models.Index(fields=["user", "status", "created_at"]),
            models.Index(fields=["status", "created_at"]),
            models.Index(fields=["account", "created_at"]),
        ]


class WithdrawalStatusLog(models.Model):
    """提现状态变化和人工操作审计事件。"""

    class Action(models.TextChoices):
        CREATED = "CREATED", "提交申请"
        APPROVE = "APPROVE", "审核通过并打款"
        REJECT = "REJECT", "审核拒绝"
        CANCEL = "CANCEL", "用户撤销"
        RETRY = "RETRY", "重新打款"
        PAYOUT_SUCCEEDED = "PAYOUT_SUCCEEDED", "打款成功"
        PAYOUT_FAILED = "PAYOUT_FAILED", "打款失败"

    id = models.BigAutoField(primary_key=True, db_comment="提现事件自增主键")
    withdrawal = models.ForeignKey(
        Withdrawal,
        on_delete=models.CASCADE,
        related_name="status_logs",
        db_comment="事件所属提现单",
    )
    action = models.CharField(max_length=32, choices=Action.choices, db_comment="提现操作类型")
    from_status = models.CharField(
        max_length=32,
        blank=True,
        default="",
        db_comment="操作前提现状态",
    )
    to_status = models.CharField(max_length=32, db_comment="操作后提现状态")
    actor_user_id = models.BigIntegerField(
        null=True,
        blank=True,
        db_comment="执行操作的用户或管理员主键",
    )
    reason = models.CharField(max_length=500, blank=True, default="", db_comment="操作原因")
    idempotency_key = models.CharField(max_length=128, db_comment="提现操作幂等键")
    request_fingerprint = models.CharField(
        max_length=64,
        db_comment="提现操作请求一致性摘要",
    )
    trace_id = models.CharField(
        max_length=64,
        blank=True,
        default="",
        db_comment="提现操作请求追踪标识",
    )
    created_at = models.DateTimeField(auto_now_add=True, db_comment="提现事件创建时间")

    class Meta:
        db_table = "withdrawal_status_logs"
        db_table_comment = "提现状态变化和人工审核审计事件表"
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.UniqueConstraint(
                fields=["withdrawal", "action", "idempotency_key"],
                name="uniq_withdrawal_action_idempotency",
            ),
        ]
        ordering: ClassVar[list[str]] = ["created_at", "id"]
