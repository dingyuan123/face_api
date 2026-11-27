"""会员套餐版本、购买单、有效期账户、权益发放和状态审计数据模型。"""

from __future__ import annotations

import uuid
from typing import ClassVar

from django.conf import settings
from django.db import models


class MembershipPlan(models.Model):
    """会员套餐主配置，价格和权益修改生成不可变版本。"""

    class Status(models.TextChoices):
        DRAFT = "DRAFT", "草稿"
        ACTIVE = "ACTIVE", "已上架"
        PAUSED = "PAUSED", "已暂停"
        ENDED = "ENDED", "已结束"

    id = models.BigAutoField(primary_key=True, db_comment="会员套餐自增主键")
    plan_no = models.UUIDField(
        default=uuid.uuid4,
        unique=True,
        editable=False,
        db_comment="对外会员套餐 UUID",
    )
    code = models.CharField(max_length=32, unique=True, db_comment="会员套餐稳定代码")
    name = models.CharField(max_length=100, db_comment="会员套餐展示名称")
    description = models.CharField(
        max_length=500,
        blank=True,
        default="",
        db_comment="会员套餐展示说明",
    )
    duration_days = models.PositiveIntegerField(db_comment="套餐有效天数")
    currency = models.CharField(max_length=3, default="CNY", db_comment="套餐价格币种代码")
    price_amount_minor = models.PositiveBigIntegerField(
        db_comment="套餐购买价格，单位为币种最小单位，CNY 为分",
    )
    benefits = models.JSONField(
        default=list,
        db_comment="会员权益配置列表，保存权益代码和可验证发放参数",
    )
    status = models.CharField(
        max_length=32,
        choices=Status.choices,
        default=Status.DRAFT,
        db_comment="会员套餐状态",
    )
    sort_order = models.PositiveIntegerField(default=0, db_comment="套餐展示排序值")
    version = models.PositiveIntegerField(default=1, db_comment="会员套餐当前版本号")
    created_by = models.BigIntegerField(
        null=True,
        blank=True,
        db_comment="创建套餐的管理员用户主键",
    )
    updated_by = models.BigIntegerField(
        null=True,
        blank=True,
        db_comment="最近修改套餐的管理员用户主键",
    )
    created_at = models.DateTimeField(auto_now_add=True, db_comment="会员套餐创建时间")
    updated_at = models.DateTimeField(auto_now=True, db_comment="会员套餐最近更新时间")

    class Meta:
        db_table = "membership_plans"
        db_table_comment = "会员套餐主配置和当前版本表"
        ordering: ClassVar[list[str]] = ["sort_order", "id"]
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.CheckConstraint(
                condition=models.Q(duration_days__gt=0),
                name="check_membership_plan_duration_positive",
            ),
            models.CheckConstraint(
                condition=models.Q(price_amount_minor__gt=0),
                name="check_membership_plan_price_positive",
            ),
        ]


class MembershipPlanVersion(models.Model):
    """会员套餐不可变版本快照，历史购买引用原价格、时长和权益。"""

    id = models.BigAutoField(primary_key=True, db_comment="会员套餐版本自增主键")
    plan = models.ForeignKey(
        MembershipPlan,
        on_delete=models.PROTECT,
        related_name="versions",
        db_comment="会员套餐主配置",
    )
    version_no = models.PositiveIntegerField(db_comment="套餐版本号，从 1 开始")
    name = models.CharField(max_length=100, db_comment="版本生效时套餐展示名称")
    description = models.CharField(
        max_length=500,
        blank=True,
        default="",
        db_comment="版本生效时套餐展示说明",
    )
    duration_days = models.PositiveIntegerField(db_comment="版本套餐有效天数")
    currency = models.CharField(max_length=3, db_comment="版本价格币种代码")
    price_amount_minor = models.PositiveBigIntegerField(
        db_comment="版本购买价格，单位为分",
    )
    benefits = models.JSONField(default=list, db_comment="版本会员权益配置快照")
    effective_at = models.DateTimeField(db_comment="版本开始用于新购买的时间")
    created_at = models.DateTimeField(auto_now_add=True, db_comment="套餐版本创建时间")

    class Meta:
        db_table = "membership_plan_versions"
        db_table_comment = "会员套餐价格、时长和权益不可变版本表"
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.UniqueConstraint(
                fields=["plan", "version_no"],
                name="uniq_membership_plan_version",
            ),
            models.CheckConstraint(
                condition=models.Q(duration_days__gt=0),
                name="check_membership_plan_version_duration_positive",
            ),
            models.CheckConstraint(
                condition=models.Q(price_amount_minor__gt=0),
                name="check_membership_plan_version_price_positive",
            ),
        ]


class MembershipAccount(models.Model):
    """用户会员账户单例，用于并发续费顺延和当前到期时间的事务锁。"""

    id = models.BigAutoField(primary_key=True, db_comment="用户会员账户自增主键")
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="membership_account",
        db_comment="会员账户所属用户",
    )
    active_until_at = models.DateTimeField(
        null=True,
        blank=True,
        db_comment="当前已购买会员有效期截止时间；空值表示当前不是会员",
    )
    current_period_no = models.UUIDField(
        null=True,
        blank=True,
        db_comment="决定当前有效期的会员周期 UUID；空值表示当前不是会员",
    )
    version = models.PositiveIntegerField(default=1, db_comment="会员账户乐观锁版本号")
    created_at = models.DateTimeField(auto_now_add=True, db_comment="会员账户创建时间")
    updated_at = models.DateTimeField(auto_now=True, db_comment="会员账户最近更新时间")

    class Meta:
        db_table = "membership_accounts"
        db_table_comment = "用户会员当前有效期和续费并发锁账户表"


class MembershipPurchase(models.Model):
    """会员购买单，保存套餐版本快照、支付金额和幂等请求。"""

    class Status(models.TextChoices):
        CREATED = "CREATED", "已创建"
        PENDING_PAYMENT = "PENDING_PAYMENT", "待支付"
        PAID = "PAID", "支付成功"
        FAILED = "FAILED", "支付失败"
        CANCELED = "CANCELED", "已取消"

    id = models.BigAutoField(primary_key=True, db_comment="会员购买单自增主键")
    purchase_no = models.UUIDField(
        default=uuid.uuid4,
        unique=True,
        editable=False,
        db_comment="对外会员购买单 UUID",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="membership_purchases",
        db_comment="购买会员的用户",
    )
    plan = models.ForeignKey(
        MembershipPlan,
        on_delete=models.PROTECT,
        related_name="purchases",
        db_comment="会员套餐主配置",
    )
    plan_version = models.ForeignKey(
        MembershipPlanVersion,
        on_delete=models.PROTECT,
        related_name="purchases",
        db_comment="购买时锁定的套餐不可变版本",
    )
    plan_snapshot = models.JSONField(
        default=dict,
        db_comment="购买时套餐名称、价格、时长和权益快照",
    )
    status = models.CharField(
        max_length=32,
        choices=Status.choices,
        default=Status.CREATED,
        db_comment="会员购买单状态",
    )
    currency = models.CharField(max_length=3, db_comment="购买币种代码")
    amount_minor = models.BigIntegerField(db_comment="购买应付金额，单位为分")
    payment_no = models.CharField(
        max_length=64,
        blank=True,
        default="",
        db_comment="关联支付单 UUID；支付创建后回填",
    )
    idempotency_key = models.CharField(max_length=128, db_comment="购买请求幂等键")
    request_fingerprint = models.CharField(
        max_length=64,
        db_comment="用户、套餐版本、金额和支付方式一致性摘要",
    )
    version = models.PositiveIntegerField(default=1, db_comment="会员购买单乐观锁版本号")
    paid_at = models.DateTimeField(null=True, blank=True, db_comment="会员购买支付成功时间")
    created_at = models.DateTimeField(auto_now_add=True, db_comment="会员购买单创建时间")
    updated_at = models.DateTimeField(auto_now=True, db_comment="会员购买单最近更新时间")

    class Meta:
        db_table = "membership_purchases"
        db_table_comment = "会员购买、套餐快照和支付幂等记录表"
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.UniqueConstraint(
                fields=["user", "idempotency_key"],
                name="uniq_membership_purchase_user_idempotency",
            ),
            models.UniqueConstraint(
                fields=["payment_no"],
                condition=~models.Q(payment_no=""),
                name="uniq_membership_purchase_payment",
            ),
            models.CheckConstraint(
                condition=models.Q(amount_minor__gt=0),
                name="check_membership_purchase_amount_positive",
            ),
        ]
        indexes: ClassVar[list[models.Index]] = [
            models.Index(fields=["user", "status", "created_at"]),
        ]


class MembershipPeriod(models.Model):
    """会员不可变有效期周期，购买成功后生成并按续费规则顺延。"""

    class Status(models.TextChoices):
        ACTIVE = "ACTIVE", "生效中"
        EXPIRED = "EXPIRED", "已到期"
        REVOKED = "REVOKED", "已撤销"

    id = models.BigAutoField(primary_key=True, db_comment="会员有效期周期自增主键")
    period_no = models.UUIDField(
        default=uuid.uuid4,
        unique=True,
        editable=False,
        db_comment="对外会员有效期周期 UUID",
    )
    purchase = models.OneToOneField(
        MembershipPurchase,
        on_delete=models.PROTECT,
        related_name="period",
        db_comment="产生该有效期周期的会员购买单",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="membership_periods",
        db_comment="会员有效期所属用户",
    )
    plan = models.ForeignKey(
        MembershipPlan,
        on_delete=models.PROTECT,
        related_name="periods",
        db_comment="会员套餐主配置",
    )
    plan_version = models.ForeignKey(
        MembershipPlanVersion,
        on_delete=models.PROTECT,
        related_name="periods",
        db_comment="有效期对应的套餐不可变版本",
    )
    plan_snapshot = models.JSONField(default=dict, db_comment="有效期生效时套餐快照")
    status = models.CharField(
        max_length=32,
        choices=Status.choices,
        default=Status.ACTIVE,
        db_comment="会员有效期周期状态",
    )
    starts_at = models.DateTimeField(db_comment="会员有效期开始时间")
    ends_at = models.DateTimeField(db_comment="会员有效期截止时间")
    activated_at = models.DateTimeField(auto_now_add=True, db_comment="会员有效期首次生效时间")
    expired_at = models.DateTimeField(
        null=True,
        blank=True,
        db_comment="会员有效期实际标记过期时间",
    )
    idempotency_key = models.CharField(max_length=128, db_comment="有效期生成幂等键")
    request_fingerprint = models.CharField(
        max_length=64,
        db_comment="购买单、套餐版本和有效期一致性摘要",
    )
    version = models.PositiveIntegerField(default=1, db_comment="会员有效期乐观锁版本号")
    created_at = models.DateTimeField(auto_now_add=True, db_comment="会员有效期创建时间")
    updated_at = models.DateTimeField(auto_now=True, db_comment="会员有效期最近更新时间")

    class Meta:
        db_table = "membership_periods"
        db_table_comment = "会员购买生效、续费顺延和到期状态表"
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.CheckConstraint(
                condition=models.Q(ends_at__gt=models.F("starts_at")),
                name="check_membership_period_end_after_start",
            ),
        ]
        indexes: ClassVar[list[models.Index]] = [
            models.Index(fields=["user", "status", "ends_at"]),
        ]


class MembershipBenefitGrant(models.Model):
    """会员权益发放记录，包括专属权益标记和会员优惠券来源。"""

    class Status(models.TextChoices):
        ACTIVE = "ACTIVE", "已发放"
        USED = "USED", "已使用"
        SKIPPED = "SKIPPED", "暂未发放"
        REVOKED = "REVOKED", "已撤销"

    id = models.BigAutoField(primary_key=True, db_comment="会员权益发放自增主键")
    grant_no = models.UUIDField(
        default=uuid.uuid4,
        unique=True,
        editable=False,
        db_comment="对外会员权益发放 UUID",
    )
    period = models.ForeignKey(
        MembershipPeriod,
        on_delete=models.PROTECT,
        related_name="benefit_grants",
        db_comment="权益所属会员有效期周期",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="membership_benefit_grants",
        db_comment="获得会员权益的用户",
    )
    benefit_code = models.CharField(max_length=64, db_comment="会员权益稳定代码")
    status = models.CharField(
        max_length=32,
        choices=Status.choices,
        default=Status.ACTIVE,
        db_comment="会员权益发放状态",
    )
    payload = models.JSONField(
        default=dict,
        db_comment="权益参数快照；优惠券权益保存券实例编号但不保存券码秘密",
    )
    idempotency_key = models.CharField(max_length=128, db_comment="权益发放幂等键")
    created_at = models.DateTimeField(auto_now_add=True, db_comment="会员权益发放时间")
    updated_at = models.DateTimeField(auto_now=True, db_comment="会员权益最近更新时间")

    class Meta:
        db_table = "membership_benefit_grants"
        db_table_comment = "会员专属权益和会员优惠券发放记录表"
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.UniqueConstraint(
                fields=["period", "benefit_code", "idempotency_key"],
                name="uniq_membership_benefit_grant_idempotency",
            ),
        ]
        indexes: ClassVar[list[models.Index]] = [
            models.Index(fields=["user", "benefit_code", "status"]),
        ]


class MembershipStatusLog(models.Model):
    """会员购买和有效期状态变化追加式审计表。"""

    class EventType(models.TextChoices):
        PURCHASE_CREATED = "PURCHASE_CREATED", "创建购买"
        PAYMENT_PENDING = "PAYMENT_PENDING", "等待支付"
        PAYMENT_SUCCESS = "PAYMENT_SUCCESS", "支付成功"
        PAYMENT_FAILED = "PAYMENT_FAILED", "支付失败"
        PERIOD_ACTIVATED = "PERIOD_ACTIVATED", "会员生效"
        PERIOD_EXTENDED = "PERIOD_EXTENDED", "会员续费顺延"
        PERIOD_EXPIRED = "PERIOD_EXPIRED", "会员到期"

    id = models.BigAutoField(primary_key=True, db_comment="会员状态日志自增主键")
    purchase = models.ForeignKey(
        MembershipPurchase,
        on_delete=models.PROTECT,
        related_name="status_logs",
        db_comment="关联会员购买单",
    )
    period = models.ForeignKey(
        MembershipPeriod,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="status_logs",
        db_comment="关联会员有效期周期；购买创建和支付日志可为空",
    )
    event_type = models.CharField(
        max_length=32,
        choices=EventType.choices,
        db_comment="会员状态事件类型",
    )
    from_status = models.CharField(
        max_length=32,
        blank=True,
        default="",
        db_comment="事件前购买或有效期状态",
    )
    to_status = models.CharField(max_length=32, db_comment="事件后购买或有效期状态")
    reason = models.CharField(max_length=500, blank=True, default="", db_comment="状态变化原因")
    actor_user_id = models.BigIntegerField(
        null=True,
        blank=True,
        db_comment="执行状态变化的用户或管理员主键",
    )
    idempotency_key = models.CharField(max_length=128, db_comment="状态事件幂等键")
    trace_id = models.CharField(
        max_length=64,
        blank=True,
        default="",
        db_comment="请求追踪标识",
    )
    occurred_at = models.DateTimeField(auto_now_add=True, db_comment="会员状态事件发生时间")

    class Meta:
        db_table = "membership_status_logs"
        db_table_comment = "会员购买、支付和有效期状态审计表"
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.UniqueConstraint(
                fields=["purchase", "event_type", "idempotency_key"],
                name="uniq_membership_status_event_idempotency",
            ),
        ]
        indexes: ClassVar[list[models.Index]] = [
            models.Index(fields=["purchase", "occurred_at"]),
        ]
