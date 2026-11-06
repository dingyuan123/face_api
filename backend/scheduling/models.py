from __future__ import annotations

import uuid
from typing import ClassVar

from django.conf import settings
from django.db import models


class ScheduleSlot(models.Model):
    """服务者可预约时段。"""

    class Status(models.TextChoices):
        OPEN = "OPEN", "可预约"
        LOCKED = "LOCKED", "待支付锁定"
        BOOKED = "BOOKED", "已预约"
        CLOSED = "CLOSED", "已关闭"

    class LastBookingStatus(models.TextChoices):
        NONE = "NONE", "无预约记录"
        LOCKED = "LOCKED", "最近预约已锁定"
        BOOKED = "BOOKED", "最近预约已支付"
        CANCELLED = "CANCELLED", "最近预约已取消"
        COMPLETED = "COMPLETED", "最近预约已完成"

    id = models.BigAutoField(primary_key=True, db_comment="预约时段自增主键")
    public_id = models.UUIDField(
        default=uuid.uuid4,
        unique=True,
        editable=False,
        db_comment="对外预约时段 UUID",
    )
    provider_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="schedule_slots",
        db_comment="服务者用户",
    )
    service = models.ForeignKey(
        "catalog.ProviderService",
        on_delete=models.PROTECT,
        related_name="schedule_slots",
        null=True,
        blank=True,
        db_comment="可选服务范围；为空表示服务者通用可预约时段",
    )
    start_at = models.DateTimeField(db_comment="预约开始时间，UTC 时间")
    end_at = models.DateTimeField(db_comment="预约结束时间，UTC 时间")
    status = models.CharField(
        max_length=16,
        choices=Status.choices,
        default=Status.OPEN,
        db_comment="时段当前状态：可预约、锁定、已预约或已关闭",
    )
    locked_order_no = models.CharField(
        max_length=64,
        blank=True,
        default="",
        db_comment="锁定该时段的订单业务单号",
    )
    last_booking_status = models.CharField(
        max_length=16,
        choices=LastBookingStatus.choices,
        default=LastBookingStatus.NONE,
        db_comment="最近一次预约状态；取消后保留取消记录并重新开放时段",
    )
    source_rule = models.ForeignKey(
        "ProviderScheduleRule",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="slots",
        db_comment="生成该时段的周排期规则，可为空",
    )
    source_override = models.ForeignKey(
        "ScheduleOverride",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="slots",
        db_comment="覆盖该时段的日期规则，可为空",
    )
    version = models.PositiveIntegerField(default=1, db_comment="时段乐观锁版本号")
    created_at = models.DateTimeField(auto_now_add=True, db_comment="时段创建时间")
    updated_at = models.DateTimeField(auto_now=True, db_comment="时段最近更新时间")
    deleted_at = models.DateTimeField(null=True, blank=True, db_comment="时段逻辑删除时间")

    class Meta:
        db_table = "schedule_slots"
        db_table_comment = "服务者可预约时段表"
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.UniqueConstraint(
                fields=["provider_user", "start_at", "end_at"],
                name="uniq_schedule_provider_start_end",
            ),
            models.CheckConstraint(
                condition=models.Q(end_at__gt=models.F("start_at")),
                name="check_schedule_slot_time_range",
            ),
        ]
        indexes: ClassVar[list[models.Index]] = [
            models.Index(fields=["provider_user", "start_at", "end_at"]),
            models.Index(fields=["service", "status", "start_at"]),
        ]


class ProviderScheduleRule(models.Model):
    """服务者默认周排期规则。"""

    id = models.BigAutoField(primary_key=True, db_comment="周排期规则自增主键")
    provider_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="schedule_rules",
        db_comment="服务者用户",
    )
    weekday = models.PositiveSmallIntegerField(db_comment="星期几，0 表示周一，6 表示周日")
    start_time = models.TimeField(db_comment="每日可约开始时间，本地时区")
    end_time = models.TimeField(db_comment="每日可约结束时间，本地时区")
    timezone = models.CharField(max_length=64, default="Asia/Shanghai", db_comment="规则使用的时区")
    slot_minutes = models.PositiveSmallIntegerField(default=60, db_comment="生成时段长度，单位分钟")
    is_active = models.BooleanField(default=True, db_comment="规则是否启用")
    effective_from = models.DateField(
        null=True, blank=True, db_comment="规则开始日期，为空表示立即生效"
    )
    effective_to = models.DateField(
        null=True, blank=True, db_comment="规则结束日期，为空表示长期有效"
    )
    version = models.PositiveIntegerField(default=1, db_comment="规则乐观锁版本号")
    created_at = models.DateTimeField(auto_now_add=True, db_comment="规则创建时间")
    updated_at = models.DateTimeField(auto_now=True, db_comment="规则最近更新时间")

    class Meta:
        db_table = "provider_schedule_rules"
        db_table_comment = "服务者默认周排期规则表"
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.UniqueConstraint(
                fields=["provider_user", "weekday", "start_time", "end_time"],
                name="uniq_schedule_rule_provider_weekday_time",
            ),
            models.CheckConstraint(
                condition=models.Q(end_time__gt=models.F("start_time")),
                name="check_schedule_rule_time_range",
            ),
            models.CheckConstraint(
                condition=models.Q(weekday__gte=0, weekday__lte=6),
                name="check_schedule_rule_weekday",
            ),
        ]


class ScheduleOverride(models.Model):
    """服务者日期级别的休息、关闭或临时开放覆盖规则。"""

    class OverrideType(models.TextChoices):
        AVAILABLE = "AVAILABLE", "临时开放"
        REST = "REST", "休息日"
        CLOSED = "CLOSED", "不可约"

    id = models.BigAutoField(primary_key=True, db_comment="日期覆盖规则自增主键")
    provider_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="schedule_overrides",
        db_comment="服务者用户",
    )
    date = models.DateField(db_comment="覆盖日期，服务者本地日期")
    override_type = models.CharField(
        max_length=16,
        choices=OverrideType.choices,
        db_comment="覆盖类型：临时开放、休息日或不可约",
    )
    start_time = models.TimeField(null=True, blank=True, db_comment="临时开放开始时间")
    end_time = models.TimeField(null=True, blank=True, db_comment="临时开放结束时间")
    reason = models.CharField(max_length=200, blank=True, default="", db_comment="覆盖原因")
    version = models.PositiveIntegerField(default=1, db_comment="覆盖规则版本号")
    created_at = models.DateTimeField(auto_now_add=True, db_comment="覆盖规则创建时间")
    updated_at = models.DateTimeField(auto_now=True, db_comment="覆盖规则最近更新时间")

    class Meta:
        db_table = "schedule_overrides"
        db_table_comment = "服务者日期排期覆盖规则表"
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.UniqueConstraint(
                fields=["provider_user", "date"],
                name="uniq_schedule_override_provider_date",
            ),
        ]


class ProviderScheduleRevision(models.Model):
    """服务者排期版本记录。"""

    id = models.BigAutoField(primary_key=True, db_comment="排期版本自增主键")
    provider_user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="schedule_revision",
        db_comment="服务者用户",
    )
    version = models.PositiveIntegerField(default=1, db_comment="排期版本号")
    updated_at = models.DateTimeField(auto_now=True, db_comment="排期版本最近更新时间")

    class Meta:
        db_table = "provider_schedule_revisions"
        db_table_comment = "服务者排期版本表"
