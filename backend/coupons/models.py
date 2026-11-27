"""优惠券模板、用户券实例、订单核销记录和状态审计数据模型。"""

from __future__ import annotations

import uuid
from typing import ClassVar

from django.conf import settings
from django.db import models


class CouponTemplate(models.Model):
    """平台优惠券模板，保存金额、门槛、范围、有效期和发放限额。"""

    class DiscountType(models.TextChoices):
        FIXED_AMOUNT = "FIXED_AMOUNT", "固定金额"

    class ScopeType(models.TextChoices):
        ALL = "ALL", "全部服务"
        CITY = "CITY", "指定城市"
        SERVICE_CATEGORY = "SERVICE_CATEGORY", "指定服务类目"
        SERVICE = "SERVICE", "指定服务"
        PROVIDER = "PROVIDER", "指定服务者"

    class ValidityType(models.TextChoices):
        FIXED_PERIOD = "FIXED_PERIOD", "固定日期"
        ISSUE_RELATIVE = "ISSUE_RELATIVE", "领取后生效"

    class Status(models.TextChoices):
        DRAFT = "DRAFT", "草稿"
        ACTIVE = "ACTIVE", "启用"
        PAUSED = "PAUSED", "暂停发放"
        ENDED = "ENDED", "已结束"

    id = models.BigAutoField(primary_key=True, db_comment="优惠券模板自增主键")
    template_no = models.UUIDField(
        default=uuid.uuid4,
        unique=True,
        editable=False,
        db_comment="对外优惠券模板 UUID",
    )
    code = models.CharField(max_length=64, unique=True, db_comment="优惠券模板稳定代码")
    name = models.CharField(max_length=100, db_comment="优惠券展示名称")
    description = models.CharField(
        max_length=500,
        blank=True,
        default="",
        db_comment="优惠券使用说明；不保存未确认的虚构规则",
    )
    discount_type = models.CharField(
        max_length=32,
        choices=DiscountType.choices,
        default=DiscountType.FIXED_AMOUNT,
        db_comment="优惠类型；当前仅实现固定金额优惠",
    )
    currency = models.CharField(max_length=3, default="CNY", db_comment="优惠金额币种代码")
    discount_amount_minor = models.PositiveBigIntegerField(
        db_comment="固定优惠金额，单位为币种最小单位，CNY 为分",
    )
    min_spend_amount_minor = models.PositiveBigIntegerField(
        default=0,
        db_comment="使用优惠券的订单原价最低门槛，单位为分；0 表示无门槛",
    )
    scope_type = models.CharField(
        max_length=32,
        choices=ScopeType.choices,
        default=ScopeType.ALL,
        db_comment="优惠适用范围类型",
    )
    scope_value = models.CharField(
        max_length=100,
        blank=True,
        default="",
        db_comment="适用城市、服务类目、服务或服务者的稳定代码；范围为全部服务时为空",
    )
    validity_type = models.CharField(
        max_length=32,
        choices=ValidityType.choices,
        default=ValidityType.FIXED_PERIOD,
        db_comment="有效期计算方式：固定日期或领取后按天数生效",
    )
    valid_from = models.DateTimeField(
        null=True,
        blank=True,
        db_comment="固定有效期开始时间；领取后生效类型为空",
    )
    valid_to = models.DateTimeField(
        null=True,
        blank=True,
        db_comment="固定有效期截止时间；领取后生效类型为空",
    )
    validity_days = models.PositiveIntegerField(
        null=True,
        blank=True,
        db_comment="领取后有效天数；固定日期类型为空",
    )
    total_issue_limit = models.PositiveBigIntegerField(
        null=True,
        blank=True,
        db_comment="模板累计发放上限；空值表示不限量",
    )
    per_user_issue_limit = models.PositiveIntegerField(
        default=1,
        db_comment="同一用户累计领取该模板券实例上限；0 表示不限制",
    )
    issued_count = models.PositiveBigIntegerField(
        default=0,
        db_comment="模板累计成功发放数量，用于发放总量审计和并发限额",
    )
    status = models.CharField(
        max_length=32,
        choices=Status.choices,
        default=Status.DRAFT,
        db_comment="优惠券模板状态",
    )
    version = models.PositiveIntegerField(default=1, db_comment="优惠券模板乐观锁版本号")
    created_by = models.BigIntegerField(
        null=True,
        blank=True,
        db_comment="创建模板的管理员用户主键",
    )
    updated_by = models.BigIntegerField(
        null=True,
        blank=True,
        db_comment="最近修改模板的管理员用户主键",
    )
    created_at = models.DateTimeField(auto_now_add=True, db_comment="优惠券模板创建时间")
    updated_at = models.DateTimeField(auto_now=True, db_comment="优惠券模板最近更新时间")

    class Meta:
        db_table = "coupon_templates"
        db_table_comment = "优惠券模板、使用条件和发放限额表"
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.CheckConstraint(
                condition=models.Q(discount_amount_minor__gt=0),
                name="check_coupon_template_discount_positive",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(
                        validity_type="FIXED_PERIOD",
                        valid_from__isnull=False,
                        valid_to__isnull=False,
                        validity_days__isnull=True,
                    )
                    | models.Q(
                        validity_type="ISSUE_RELATIVE",
                        valid_from__isnull=True,
                        valid_to__isnull=True,
                        validity_days__gt=0,
                    )
                ),
                name="check_coupon_template_validity_config",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(scope_type="ALL", scope_value="")
                    | ~models.Q(scope_type="ALL") & ~models.Q(scope_value="")
                ),
                name="check_coupon_template_scope_value",
            ),
        ]
        indexes: ClassVar[list[models.Index]] = [
            models.Index(fields=["status", "valid_to"]),
        ]


class CouponInstance(models.Model):
    """发放给具体用户的优惠券实例，保存领取时模板规则快照。"""

    class Status(models.TextChoices):
        AVAILABLE = "AVAILABLE", "可使用"
        RESERVED = "RESERVED", "下单锁定"
        USED = "USED", "已使用"
        EXPIRED = "EXPIRED", "已过期"
        REVOKED = "REVOKED", "已撤销"

    class SourceType(models.TextChoices):
        USER_CLAIM = "USER_CLAIM", "用户领取"
        ADMIN_ISSUE = "ADMIN_ISSUE", "管理员发放"
        MEMBERSHIP = "MEMBERSHIP", "会员权益"
        CAMPAIGN = "CAMPAIGN", "营销活动"

    id = models.BigAutoField(primary_key=True, db_comment="用户优惠券实例自增主键")
    coupon_no = models.UUIDField(
        default=uuid.uuid4,
        unique=True,
        editable=False,
        db_comment="对外用户优惠券 UUID",
    )
    template = models.ForeignKey(
        CouponTemplate,
        on_delete=models.PROTECT,
        related_name="instances",
        db_comment="优惠券模板；历史实例保留模板引用和规则快照",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="coupon_instances",
        db_comment="持有优惠券的用户",
    )
    status = models.CharField(
        max_length=32,
        choices=Status.choices,
        default=Status.AVAILABLE,
        db_comment="用户优惠券状态",
    )
    valid_from = models.DateTimeField(db_comment="该券实例可用开始时间")
    valid_to = models.DateTimeField(db_comment="该券实例可用截止时间")
    source_type = models.CharField(
        max_length=32,
        choices=SourceType.choices,
        db_comment="优惠券发放来源",
    )
    source_no = models.CharField(
        max_length=64,
        blank=True,
        default="",
        db_comment="发放来源业务单号或幂等键；用于会员权益和活动重复发放幂等",
    )
    template_snapshot = models.JSONField(
        default=dict,
        db_comment="领取时名称、金额、门槛、范围和币种快照",
    )
    issued_at = models.DateTimeField(auto_now_add=True, db_comment="优惠券发放时间")
    used_at = models.DateTimeField(null=True, blank=True, db_comment="优惠券首次核销时间")
    revoked_at = models.DateTimeField(null=True, blank=True, db_comment="优惠券撤销时间")
    version = models.PositiveIntegerField(default=1, db_comment="优惠券实例乐观锁版本号")
    created_at = models.DateTimeField(auto_now_add=True, db_comment="优惠券实例创建时间")
    updated_at = models.DateTimeField(auto_now=True, db_comment="优惠券实例最近更新时间")

    class Meta:
        db_table = "coupon_instances"
        db_table_comment = "用户优惠券实例、有效期和来源快照表"
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.UniqueConstraint(
                fields=["user", "template", "source_type", "source_no"],
                condition=~models.Q(source_no=""),
                name="uniq_coupon_instance_source",
            ),
        ]
        indexes: ClassVar[list[models.Index]] = [
            models.Index(fields=["user", "status", "valid_to"]),
            models.Index(fields=["template", "status", "created_at"]),
        ]


class CouponRedemption(models.Model):
    """优惠券与预约订单的锁定和核销事实，保存完整金额快照。"""

    class Status(models.TextChoices):
        RESERVED = "RESERVED", "下单已锁定"
        USED = "USED", "支付已核销"
        RELEASED = "RELEASED", "已释放"
        CANCELED = "CANCELED", "已取消"

    id = models.BigAutoField(primary_key=True, db_comment="优惠券核销记录自增主键")
    redemption_no = models.UUIDField(
        default=uuid.uuid4,
        unique=True,
        editable=False,
        db_comment="对外优惠券核销记录 UUID",
    )
    coupon = models.ForeignKey(
        CouponInstance,
        on_delete=models.PROTECT,
        related_name="redemptions",
        db_comment="被使用的用户优惠券实例",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="coupon_redemptions",
        db_comment="使用优惠券的订单用户",
    )
    order_no = models.CharField(max_length=64, db_comment="关联预约订单业务 UUID")
    status = models.CharField(
        max_length=32,
        choices=Status.choices,
        default=Status.RESERVED,
        db_comment="优惠券核销状态",
    )
    currency = models.CharField(max_length=3, db_comment="订单和优惠金额币种代码")
    original_amount_minor = models.BigIntegerField(db_comment="使用优惠券前订单原价，单位为分")
    discount_amount_minor = models.BigIntegerField(db_comment="本次优惠金额，单位为分")
    payable_amount_minor = models.BigIntegerField(db_comment="优惠后订单应付金额，单位为分")
    template_snapshot = models.JSONField(
        default=dict,
        db_comment="核销时优惠券模板规则和券实例快照",
    )
    idempotency_key = models.CharField(max_length=128, db_comment="核销或释放请求幂等键")
    request_fingerprint = models.CharField(
        max_length=64,
        db_comment="订单、优惠券和金额一致性摘要",
    )
    reserved_at = models.DateTimeField(auto_now_add=True, db_comment="订单创建锁定优惠券时间")
    used_at = models.DateTimeField(null=True, blank=True, db_comment="订单支付成功核销时间")
    released_at = models.DateTimeField(null=True, blank=True, db_comment="订单取消或失败释放时间")
    created_at = models.DateTimeField(auto_now_add=True, db_comment="核销记录创建时间")
    updated_at = models.DateTimeField(auto_now=True, db_comment="核销记录最近更新时间")

    class Meta:
        db_table = "coupon_redemptions"
        db_table_comment = "优惠券订单锁定、核销、释放和金额快照表"
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.UniqueConstraint(
                fields=["coupon"],
                condition=models.Q(status__in=["RESERVED", "USED"]),
                name="uniq_coupon_redemption_active_coupon",
            ),
            models.UniqueConstraint(
                fields=["order_no"],
                condition=models.Q(status__in=["RESERVED", "USED"]),
                name="uniq_coupon_redemption_active_order",
            ),
            models.CheckConstraint(
                condition=models.Q(discount_amount_minor__gte=0),
                name="check_coupon_redemption_discount_non_negative",
            ),
            models.CheckConstraint(
                condition=models.Q(original_amount_minor__gte=0)
                & models.Q(payable_amount_minor__gte=0),
                name="check_coupon_redemption_amount_non_negative",
            ),
        ]
        indexes: ClassVar[list[models.Index]] = [
            models.Index(fields=["user", "status", "created_at"]),
            models.Index(fields=["order_no", "status"]),
        ]


class CouponStatusLog(models.Model):
    """优惠券领取、锁定、使用、释放、过期和撤销的追加式状态日志。"""

    class EventType(models.TextChoices):
        ISSUED = "ISSUED", "发放"
        CLAIMED = "CLAIMED", "领取"
        RESERVED = "RESERVED", "下单锁定"
        USED = "USED", "支付核销"
        RELEASED = "RELEASED", "订单释放"
        EXPIRED = "EXPIRED", "过期"
        REVOKED = "REVOKED", "管理员撤销"
        ORDER_REFUNDED = "ORDER_REFUNDED", "关联订单退款"

    id = models.BigAutoField(primary_key=True, db_comment="优惠券状态日志自增主键")
    coupon = models.ForeignKey(
        CouponInstance,
        on_delete=models.PROTECT,
        related_name="status_logs",
        db_comment="状态变化的用户优惠券实例",
    )
    redemption = models.ForeignKey(
        CouponRedemption,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="status_logs",
        db_comment="关联订单核销记录；纯过期或发放日志为空",
    )
    event_type = models.CharField(
        max_length=32,
        choices=EventType.choices,
        db_comment="优惠券状态事件类型",
    )
    from_status = models.CharField(
        max_length=32,
        blank=True,
        default="",
        db_comment="事件前优惠券状态",
    )
    to_status = models.CharField(max_length=32, db_comment="事件后优惠券状态")
    reason = models.CharField(max_length=500, blank=True, default="", db_comment="状态变化原因")
    operator_user_id = models.BigIntegerField(
        null=True,
        blank=True,
        db_comment="执行管理员或用户主键；系统任务为空",
    )
    idempotency_key = models.CharField(
        max_length=128,
        blank=True,
        default="",
        db_comment="状态事件幂等键",
    )
    trace_id = models.CharField(
        max_length=64,
        blank=True,
        default="",
        db_comment="请求追踪标识",
    )
    occurred_at = models.DateTimeField(auto_now_add=True, db_comment="状态事件发生时间")

    class Meta:
        db_table = "coupon_status_logs"
        db_table_comment = "优惠券状态变化追加式审计表"
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.UniqueConstraint(
                fields=["coupon", "event_type", "idempotency_key"],
                condition=~models.Q(idempotency_key=""),
                name="uniq_coupon_status_event_idempotency",
            ),
        ]
        indexes: ClassVar[list[models.Index]] = [
            models.Index(fields=["coupon", "occurred_at"]),
        ]
