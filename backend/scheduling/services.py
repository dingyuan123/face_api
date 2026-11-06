"""服务者预约时段创建、查询和释放业务服务。"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.conf import settings
from django.db import transaction
from django.http import HttpRequest
from django.utils import timezone

from backend.accounts.models import User
from backend.catalog.services import service_schedule_summary
from backend.common.errors import ERROR_MESSAGES, ErrorCode
from backend.common.exceptions import ApiError
from backend.providers.profile_services import get_provider_profile, require_provider_enabled
from backend.scheduling.models import (
    ProviderScheduleRevision,
    ProviderScheduleRule,
    ScheduleOverride,
    ScheduleSlot,
)


def _invalid(field: str, message: str) -> ApiError:
    return ApiError(
        ErrorCode.SCHEDULE_INVALID,
        ERROR_MESSAGES[ErrorCode.SCHEDULE_INVALID],
        status_code=400,
        details={field: message},
    )


def _timezone_name(value: str) -> str:
    timezone_name = value.strip()
    try:
        ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError as exc:
        raise _invalid("timezone", "timezone 不是有效的 IANA 时区") from exc
    return timezone_name


def _slot_payload(slot: ScheduleSlot, request: HttpRequest | None = None) -> dict[str, Any]:
    """返回服务者管理端时段摘要，包含订单锁定信息和并发版本。"""

    return {
        "slot_id": str(slot.public_id),
        "service_id": str(slot.service.public_id) if slot.service else None,
        "service": service_schedule_summary(slot.service) if slot.service else None,
        "start_at": slot.start_at,
        "end_at": slot.end_at,
        "status": slot.status,
        "status_text": _slot_status_text(slot.status),
        "last_booking_status": slot.last_booking_status,
        "locked_order_no": slot.locked_order_no or None,
        "version": slot.version,
    }


def _public_slot_payload(slot: ScheduleSlot) -> dict[str, Any]:
    """返回公开预约所需的最小时段信息，不包含订单和管理字段。"""

    return {
        "slot_id": str(slot.public_id),
        "service_id": str(slot.service.public_id) if slot.service else None,
        "service": service_schedule_summary(slot.service) if slot.service else None,
        "start_at": slot.start_at,
        "end_at": slot.end_at,
        "status": slot.status,
        "slot_version": slot.version,
    }


def _slot_mutation_payload(
    slot: ScheduleSlot,
    revision: ProviderScheduleRevision,
) -> dict[str, Any]:
    """返回时段变更结果和用于下一次批量操作的排期版本。"""

    return {**_slot_payload(slot), "schedule_version": revision.version}


def _local_date(value: datetime, timezone_name: str) -> date:
    return value.astimezone(ZoneInfo(timezone_name)).date()


def _local_datetime(value: date, local_time: time, timezone_name: str) -> datetime:
    return datetime.combine(value, local_time, tzinfo=ZoneInfo(timezone_name))


def _slot_status_text(status: str) -> str:
    return {
        ScheduleSlot.Status.OPEN: "可约",
        ScheduleSlot.Status.LOCKED: "已锁定",
        ScheduleSlot.Status.BOOKED: "已预约",
        ScheduleSlot.Status.CLOSED: "不可约",
    }[status]


def _revision_payload(revision: ProviderScheduleRevision | None) -> dict[str, Any]:
    return {"schedule_version": revision.version if revision else 1}


def _get_revision(provider_user: User, *, for_update: bool = False) -> ProviderScheduleRevision:
    queryset = ProviderScheduleRevision.objects.filter(provider_user=provider_user)
    if for_update:
        queryset = queryset.select_for_update()
    revision = queryset.first()
    if revision is None:
        revision = ProviderScheduleRevision.objects.create(provider_user=provider_user)
    return revision


def _increment_revision(user: User) -> ProviderScheduleRevision:
    """在调用方事务内递增排期版本。"""

    revision = _get_revision(user, for_update=True)
    revision.version += 1
    revision.save(update_fields=["version", "updated_at"])
    return revision


def create_schedule_rule(
    *,
    user: User,
    weekday: int,
    start_time: time,
    end_time: time,
    slot_minutes: int,
    timezone_name: str | None = None,
) -> dict[str, Any]:
    """创建服务者周排期规则，规则时段不得重叠。"""

    require_provider_enabled(user)
    get_provider_profile(user)
    if not 0 <= weekday <= 6:
        raise _invalid("weekday", "星期范围必须是 0 到 6")
    if end_time <= start_time:
        raise _invalid("end_time", "结束时间必须晚于开始时间")
    if slot_minutes != settings.SCHEDULE_SLOT_UNIT_MINUTES:
        raise _invalid(
            "slot_minutes",
            f"当前排期固定为 {settings.SCHEDULE_SLOT_UNIT_MINUTES} 分钟单元",
        )
    normalized_timezone = _timezone_name(timezone_name or settings.SCHEDULE_DEFAULT_TIMEZONE)
    with transaction.atomic():
        User.objects.select_for_update().get(pk=user.pk)
        overlap = ProviderScheduleRule.objects.filter(
            provider_user=user,
            weekday=weekday,
            start_time__lt=end_time,
            end_time__gt=start_time,
            is_active=True,
        ).exists()
        if overlap:
            raise _invalid("start_time", "同星期排期规则时间重叠")
        rule = ProviderScheduleRule.objects.create(
            provider_user=user,
            weekday=weekday,
            start_time=start_time,
            end_time=end_time,
            slot_minutes=slot_minutes,
            timezone=normalized_timezone,
        )
        revision = _increment_revision(user)
        return {
            "rule_id": rule.id,
            "weekday": rule.weekday,
            "start_time": rule.start_time,
            "end_time": rule.end_time,
            "timezone": rule.timezone,
            "slot_minutes": rule.slot_minutes,
            "is_active": rule.is_active,
            "version": rule.version,
            **_revision_payload(revision),
        }


def list_schedule_rules(user: User) -> list[dict[str, Any]]:
    """返回服务者周排期规则。"""

    require_provider_enabled(user)
    get_provider_profile(user)
    revision = _get_revision(user)
    return [
        {
            "rule_id": rule.id,
            "weekday": rule.weekday,
            "start_time": rule.start_time,
            "end_time": rule.end_time,
            "timezone": rule.timezone,
            "slot_minutes": rule.slot_minutes,
            "is_active": rule.is_active,
            "version": rule.version,
            "schedule_version": revision.version,
        }
        for rule in ProviderScheduleRule.objects.filter(provider_user=user).order_by(
            "weekday", "start_time", "id"
        )
    ]


def update_schedule_rule(
    *,
    user: User,
    rule_id: int,
    expected_version: int,
    payload: dict[str, Any],
) -> dict[str, Any]:
    """修改周排期规则；规则修改只影响后续生成，不重写已生成时段。"""

    require_provider_enabled(user)
    get_provider_profile(user)
    with transaction.atomic():
        User.objects.select_for_update().get(pk=user.pk)
        rule = (
            ProviderScheduleRule.objects.select_for_update()
            .filter(id=rule_id, provider_user=user)
            .first()
        )
        if rule is None:
            raise _invalid("rule_id", "排期规则不存在")
        if rule.version != expected_version:
            raise ApiError(
                ErrorCode.SCHEDULE_VERSION_CONFLICT,
                ERROR_MESSAGES[ErrorCode.SCHEDULE_VERSION_CONFLICT],
                status_code=409,
            )
        weekday = payload.get("weekday", rule.weekday)
        start_time = payload.get("start_time", rule.start_time)
        end_time = payload.get("end_time", rule.end_time)
        slot_minutes = payload.get("slot_minutes", rule.slot_minutes)
        timezone_name = _timezone_name(payload.get("timezone", rule.timezone))
        is_active = payload.get("is_active", rule.is_active)
        if not 0 <= weekday <= 6:
            raise _invalid("weekday", "星期范围必须是 0 到 6")
        if end_time <= start_time:
            raise _invalid("end_time", "结束时间必须晚于开始时间")
        if slot_minutes != settings.SCHEDULE_SLOT_UNIT_MINUTES:
            raise _invalid(
                "slot_minutes",
                f"当前排期固定为 {settings.SCHEDULE_SLOT_UNIT_MINUTES} 分钟单元",
            )
        overlap = (
            ProviderScheduleRule.objects.filter(
                provider_user=user,
                weekday=weekday,
                start_time__lt=end_time,
                end_time__gt=start_time,
                is_active=True,
            )
            .exclude(pk=rule.pk)
            .exists()
        )
        if is_active and overlap:
            raise _invalid("start_time", "同星期排期规则时间重叠")
        rule.weekday = weekday
        rule.start_time = start_time
        rule.end_time = end_time
        rule.slot_minutes = slot_minutes
        rule.timezone = timezone_name
        rule.is_active = is_active
        rule.version += 1
        rule.save(
            update_fields=[
                "weekday",
                "start_time",
                "end_time",
                "slot_minutes",
                "timezone",
                "is_active",
                "version",
                "updated_at",
            ]
        )
        revision = _increment_revision(user)
        return {
            "rule_id": rule.id,
            "weekday": rule.weekday,
            "start_time": rule.start_time,
            "end_time": rule.end_time,
            "timezone": rule.timezone,
            "slot_minutes": rule.slot_minutes,
            "is_active": rule.is_active,
            "version": rule.version,
            **_revision_payload(revision),
        }


def delete_schedule_rule(
    *,
    user: User,
    rule_id: int,
    expected_version: int,
) -> dict[str, Any]:
    """删除周排期规则，已锁定时段保持不变。"""

    with transaction.atomic():
        User.objects.select_for_update().get(pk=user.pk)
        rule = (
            ProviderScheduleRule.objects.select_for_update()
            .filter(
                id=rule_id,
                provider_user=user,
            )
            .first()
        )
        if rule is None:
            raise _invalid("rule_id", "排期规则不存在")
        if rule.version != expected_version:
            raise ApiError(
                ErrorCode.SCHEDULE_VERSION_CONFLICT,
                ERROR_MESSAGES[ErrorCode.SCHEDULE_VERSION_CONFLICT],
                status_code=409,
            )
        rule_id = rule.id
        rule.delete()
        revision = _increment_revision(user)
        return {
            "deleted": True,
            "rule_id": rule_id,
            **_revision_payload(revision),
        }


def _generate_slot_times(
    *,
    day: date,
    start_time: time,
    end_time: time,
    slot_minutes: int,
    timezone_name: str,
) -> list[tuple[datetime, datetime]]:
    start = _local_datetime(day, start_time, timezone_name)
    end = _local_datetime(day, end_time, timezone_name)
    if end <= start or slot_minutes <= 0:
        return []
    result = []
    cursor = start
    step = timedelta(minutes=slot_minutes)
    while cursor + step <= end:
        result.append((cursor, cursor + step))
        cursor += step
    return result


def materialize_schedule_slots(
    *,
    user: User,
    start_date: date,
    end_date: date,
) -> list[ScheduleSlot]:
    """生成每日默认小时单元，并按周规则开放服务者主动设置的时段。"""

    if end_date < start_date:
        raise _invalid("end_date", "结束日期不能早于开始日期")
    timezone_name = settings.SCHEDULE_DEFAULT_TIMEZONE
    unit_minutes = settings.SCHEDULE_SLOT_UNIT_MINUTES
    if unit_minutes <= 0 or 24 * 60 % unit_minutes != 0:
        raise _invalid("slot_minutes", "每日时段单元配置不正确")
    rules = list(
        ProviderScheduleRule.objects.filter(
            provider_user=user,
            is_active=True,
        )
    )
    overrides = {
        item.date: item
        for item in ScheduleOverride.objects.filter(
            provider_user=user,
            date__gte=start_date,
            date__lte=end_date,
        )
    }
    slots: list[ScheduleSlot] = []
    with transaction.atomic():
        User.objects.select_for_update().get(pk=user.pk)
        current = start_date
        while current <= end_date:
            override = overrides.get(current)
            day_start = _local_datetime(current, time.min, timezone_name) + timedelta(
                minutes=settings.SCHEDULE_DEFAULT_START_MINUTE
            )
            day_end = _local_datetime(current, time.min, timezone_name) + timedelta(
                minutes=settings.SCHEDULE_DEFAULT_END_MINUTE
            )
            default_cursor = day_start
            while default_cursor + timedelta(minutes=unit_minutes) <= day_end:
                default_end = default_cursor + timedelta(minutes=unit_minutes)
                ScheduleSlot.objects.get_or_create(
                    provider_user=user,
                    start_at=default_cursor,
                    end_at=default_end,
                    defaults={
                        "service": None,
                        "status": ScheduleSlot.Status.CLOSED,
                        "source_rule": None,
                        "source_override": None,
                    },
                )
                default_cursor = default_end
            windows: list[
                tuple[
                    time,
                    time,
                    int,
                    ProviderScheduleRule | None,
                    ScheduleOverride | None,
                    str,
                ]
            ] = []
            if override and override.override_type == ScheduleOverride.OverrideType.AVAILABLE:
                if override.start_time and override.end_time:
                    windows.append(
                        (
                            override.start_time,
                            override.end_time,
                            unit_minutes,
                            None,
                            override,
                            timezone_name,
                        )
                    )
            elif override and (
                override.override_type == ScheduleOverride.OverrideType.REST
                or (
                    override.override_type == ScheduleOverride.OverrideType.CLOSED
                    and not override.start_time
                    and not override.end_time
                )
            ):
                windows = []
            else:
                for rule in rules:
                    if rule.weekday != current.weekday():
                        continue
                    if rule.effective_from and current < rule.effective_from:
                        continue
                    if rule.effective_to and current > rule.effective_to:
                        continue
                    windows.append(
                        (
                            rule.start_time,
                            rule.end_time,
                            unit_minutes,
                            rule,
                            None,
                            rule.timezone,
                        )
                    )
            for (
                start_time,
                end_time,
                slot_minutes,
                rule,
                source_override,
                window_timezone,
            ) in windows:
                for start, end in _generate_slot_times(
                    day=current,
                    start_time=start_time,
                    end_time=end_time,
                    slot_minutes=slot_minutes,
                    timezone_name=window_timezone,
                ):
                    if (
                        override
                        and override.override_type == ScheduleOverride.OverrideType.CLOSED
                        and override.start_time
                        and override.end_time
                    ):
                        closed_start = _local_datetime(
                            current,
                            override.start_time,
                            timezone_name,
                        )
                        closed_end = _local_datetime(
                            current,
                            override.end_time,
                            timezone_name,
                        )
                        if start < closed_end and end > closed_start:
                            continue
                    slot, created = ScheduleSlot.objects.get_or_create(
                        provider_user=user,
                        start_at=start,
                        end_at=end,
                        defaults={
                            "service": None,
                            "status": ScheduleSlot.Status.OPEN,
                            "source_rule": rule,
                            "source_override": source_override,
                        },
                    )
                    if (
                        not created
                        and slot.status == ScheduleSlot.Status.CLOSED
                        and slot.last_booking_status == ScheduleSlot.LastBookingStatus.NONE
                    ):
                        slot.status = ScheduleSlot.Status.OPEN
                        slot.source_rule = rule
                        slot.source_override = source_override
                        slot.version += 1
                        slot.save(
                            update_fields=[
                                "status",
                                "source_rule",
                                "source_override",
                                "version",
                                "updated_at",
                            ]
                        )
                    slots.append(slot)
            current += timedelta(days=1)
    range_start = _local_datetime(start_date, time.min, timezone_name)
    range_end = _local_datetime(end_date + timedelta(days=1), time.min, timezone_name)
    return list(
        ScheduleSlot.objects.filter(
            provider_user=user,
            deleted_at__isnull=True,
            start_at__gte=range_start,
            start_at__lt=range_end,
        ).order_by("start_at", "id")
    )


def _calendar_range(
    *,
    view: str,
    anchor_date: date | None,
    date_from: date | None,
    date_to: date | None,
    timezone_name: str,
) -> tuple[str, date, date]:
    """计算月历、周历或自定义查询的本地日期范围。"""

    normalized_view = view.upper()
    if date_from and date_to:
        if date_to < date_from:
            raise _invalid("date_to", "结束日期不能早于开始日期")
        if date_to - date_from > timedelta(days=366):
            raise _invalid("date_to", "自定义日期范围不能超过 366 天")
        return "CUSTOM", date_from, date_to
    if normalized_view not in {"MONTH", "WEEK"}:
        raise _invalid("view", "view 必须是 MONTH、WEEK 或 CUSTOM")
    local_today = timezone.now().astimezone(ZoneInfo(timezone_name)).date()
    anchor = anchor_date or local_today
    if normalized_view == "WEEK":
        week_start = anchor - timedelta(days=anchor.weekday())
        return "WEEK", week_start, week_start + timedelta(days=6)
    month_start = anchor.replace(day=1)
    next_month = (month_start + timedelta(days=32)).replace(day=1)
    return "MONTH", month_start, next_month - timedelta(days=1)


def _day_payload(
    *,
    day: date,
    slots: list[ScheduleSlot],
    override: ScheduleOverride | None,
    timezone_name: str,
) -> dict[str, Any]:
    """返回一天的排期状态、统计和完整时段。"""

    available = sum(1 for item in slots if item.status == ScheduleSlot.Status.OPEN)
    booked = sum(
        1
        for item in slots
        if item.status in {ScheduleSlot.Status.LOCKED, ScheduleSlot.Status.BOOKED}
    )
    closed = sum(1 for item in slots if item.status == ScheduleSlot.Status.CLOSED)
    is_rest = bool(override and override.override_type == ScheduleOverride.OverrideType.REST)
    if is_rest:
        status = "REST"
    elif available and (booked or closed):
        status = "PARTIAL"
    elif available:
        status = "AVAILABLE"
    elif booked:
        status = "BOOKED"
    else:
        status = "CLOSED"
    local_today = timezone.now().astimezone(ZoneInfo(timezone_name)).date()
    return {
        "date": day,
        "weekday": day.weekday(),
        "is_today": day == local_today,
        "is_rest": is_rest,
        "status": status,
        "available_count": available,
        "booked_count": booked,
        "closed_count": closed,
        "slots": [_slot_payload(item) for item in slots],
    }


def get_schedule_calendar(
    *,
    user: User,
    view: str = "MONTH",
    anchor_date: date | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    timezone_name: str | None = None,
) -> dict[str, Any]:
    """生成月历、周历或自定义范围的日期、时段和排期汇总。"""

    require_provider_enabled(user)
    get_provider_profile(user)
    normalized_timezone = _timezone_name(timezone_name or settings.SCHEDULE_DEFAULT_TIMEZONE)
    normalized_view, start_date, end_date = _calendar_range(
        view=view,
        anchor_date=anchor_date,
        date_from=date_from,
        date_to=date_to,
        timezone_name=normalized_timezone,
    )
    materialize_schedule_slots(user=user, start_date=start_date, end_date=end_date)
    timezone_obj = ZoneInfo(normalized_timezone)
    start = datetime.combine(start_date, time.min, tzinfo=timezone_obj)
    end = datetime.combine(end_date + timedelta(days=1), time.min, tzinfo=timezone_obj)
    slots = list(
        ScheduleSlot.objects.select_related("service")
        .filter(
            provider_user=user,
            deleted_at__isnull=True,
            start_at__gte=start,
            start_at__lt=end,
        )
        .order_by("start_at", "id")
    )
    overrides = {
        item.date: item
        for item in ScheduleOverride.objects.filter(
            provider_user=user,
            date__gte=start_date,
            date__lte=end_date,
        )
    }
    grouped: dict[date, list[ScheduleSlot]] = {}
    for slot in slots:
        grouped.setdefault(
            _local_date(slot.start_at, normalized_timezone),
            [],
        ).append(slot)
    days = []
    current = start_date
    while current <= end_date:
        days.append(
            _day_payload(
                day=current,
                slots=grouped.get(current, []),
                override=overrides.get(current),
                timezone_name=normalized_timezone,
            )
        )
        current += timedelta(days=1)
    revision = _get_revision(user)
    return {
        "schedule_version": revision.version,
        "view": normalized_view,
        "timezone": normalized_timezone,
        "date_from": start_date,
        "date_to": end_date,
        "days": days,
        "summary": {
            "available_count": sum(day["available_count"] for day in days),
            "booked_count": sum(day["booked_count"] for day in days),
            "rest_day_count": sum(1 for day in days if day["is_rest"]),
        },
    }


def get_schedule_day(
    *,
    user: User,
    day: date,
    timezone_name: str | None = None,
) -> dict[str, Any]:
    """返回某一天的明确日期状态和动态时段列表。"""

    calendar = get_schedule_calendar(
        user=user,
        view="CUSTOM",
        date_from=day,
        date_to=day,
        timezone_name=timezone_name,
    )
    return {
        **calendar["days"][0],
        "schedule_version": calendar["schedule_version"],
        "timezone": calendar["timezone"],
    }


def set_slot_status(
    *,
    user: User,
    slot_id: str,
    status: str,
    expected_version: int,
) -> dict[str, Any]:
    """切换单个未预约时段的可约/不可约状态。"""

    if status not in {ScheduleSlot.Status.OPEN, ScheduleSlot.Status.CLOSED}:
        raise _invalid("status", "时段状态只能是 OPEN 或 CLOSED")
    with transaction.atomic():
        User.objects.select_for_update().get(pk=user.pk)
        slot = (
            ScheduleSlot.objects.select_for_update()
            .filter(
                public_id=slot_id,
                provider_user=user,
                deleted_at__isnull=True,
            )
            .first()
        )
        if slot is None:
            raise _invalid("slot_id", "预约时段不存在")
        if slot.status in {
            ScheduleSlot.Status.LOCKED,
            ScheduleSlot.Status.BOOKED,
        }:
            raise _invalid("slot_id", "已预约时段不能修改")
        if slot.version != expected_version:
            raise ApiError(
                ErrorCode.SCHEDULE_VERSION_CONFLICT,
                ERROR_MESSAGES[ErrorCode.SCHEDULE_VERSION_CONFLICT],
                status_code=409,
            )
        slot.status = status
        slot.version += 1
        slot.save(update_fields=["status", "version", "updated_at"])
        return _slot_mutation_payload(slot, _increment_revision(user))


def bulk_update_schedule(
    *,
    user: User,
    date_from: date,
    date_to: date,
    scope: str,
    action: str,
    start_time: time | None = None,
    end_time: time | None = None,
    expected_revision: int,
) -> dict[str, Any]:
    """批量设置工作日、周末或全部日期的可约/休息状态。"""

    if date_to < date_from:
        raise _invalid("date_to", "结束日期不能早于开始日期")
    if date_to - date_from > timedelta(days=366):
        raise _invalid("date_to", "批量日期范围不能超过 366 天")
    if scope not in {"WEEKDAY", "WEEKEND", "ALL"}:
        raise _invalid("scope", "批量范围不正确")
    if action not in {"AVAILABLE", "REST"}:
        raise _invalid("action", "批量动作不正确")
    if (start_time is None) != (end_time is None):
        raise _invalid("start_time", "开始时间和结束时间必须同时提供")
    if start_time and end_time and end_time <= start_time:
        raise _invalid("end_time", "结束时间必须晚于开始时间")
    timezone_name = settings.SCHEDULE_DEFAULT_TIMEZONE
    with transaction.atomic():
        User.objects.select_for_update().get(pk=user.pk)
        revision = _get_revision(user, for_update=True)
        if revision.version != expected_revision:
            raise ApiError(
                ErrorCode.SCHEDULE_VERSION_CONFLICT,
                ERROR_MESSAGES[ErrorCode.SCHEDULE_VERSION_CONFLICT],
                status_code=409,
            )
        opened_count = 0
        closed_count = 0
        skipped_locked_count = 0
        skipped_booked_count = 0
        warnings = []
        current = date_from
        while current <= date_to:
            include = (
                scope == "ALL"
                or (scope == "WEEKDAY" and current.weekday() < 5)
                or (scope == "WEEKEND" and current.weekday() >= 5)
            )
            if include:
                range_start = _local_datetime(
                    current,
                    start_time or time.min,
                    timezone_name,
                )
                range_end = (
                    _local_datetime(current, end_time, timezone_name)
                    if end_time
                    else _local_datetime(current + timedelta(days=1), time.min, timezone_name)
                )
                if action == "REST":
                    ScheduleOverride.objects.update_or_create(
                        provider_user=user,
                        date=current,
                        defaults={
                            "override_type": (
                                ScheduleOverride.OverrideType.CLOSED
                                if start_time and end_time
                                else ScheduleOverride.OverrideType.REST
                            ),
                            "start_time": start_time,
                            "end_time": end_time,
                        },
                    )
                    slots = ScheduleSlot.objects.filter(
                        provider_user=user,
                        deleted_at__isnull=True,
                        status=ScheduleSlot.Status.OPEN,
                        start_at__lt=range_end,
                        end_at__gt=range_start,
                    )
                    for slot in slots:
                        slot.status = ScheduleSlot.Status.CLOSED
                        slot.version += 1
                        slot.save(update_fields=["status", "version", "updated_at"])
                        closed_count += 1
                    protected_slots = list(
                        ScheduleSlot.objects.filter(
                            provider_user=user,
                            deleted_at__isnull=True,
                            status__in=[
                                ScheduleSlot.Status.LOCKED,
                                ScheduleSlot.Status.BOOKED,
                            ],
                            start_at__lt=range_end,
                            end_at__gt=range_start,
                        )
                    )
                else:
                    ScheduleOverride.objects.filter(
                        provider_user=user,
                        date=current,
                    ).delete()
                    if start_time and end_time:
                        ScheduleOverride.objects.create(
                            provider_user=user,
                            date=current,
                            override_type=ScheduleOverride.OverrideType.AVAILABLE,
                            start_time=start_time,
                            end_time=end_time,
                        )
                    materialize_schedule_slots(
                        user=user,
                        start_date=current,
                        end_date=current,
                    )
                    slots = ScheduleSlot.objects.filter(
                        provider_user=user,
                        deleted_at__isnull=True,
                        status=ScheduleSlot.Status.CLOSED,
                        start_at__lt=range_end,
                        end_at__gt=range_start,
                    )
                    for slot in slots:
                        slot.status = ScheduleSlot.Status.OPEN
                        slot.version += 1
                        slot.save(update_fields=["status", "version", "updated_at"])
                        opened_count += 1
                    protected_slots = list(
                        ScheduleSlot.objects.filter(
                            provider_user=user,
                            deleted_at__isnull=True,
                            status__in=[
                                ScheduleSlot.Status.LOCKED,
                                ScheduleSlot.Status.BOOKED,
                            ],
                            start_at__lt=range_end,
                            end_at__gt=range_start,
                        )
                    )
                for slot in protected_slots:
                    is_locked = slot.status == ScheduleSlot.Status.LOCKED
                    if is_locked:
                        skipped_locked_count += 1
                    else:
                        skipped_booked_count += 1
                    warnings.append(
                        {
                            "code": "SLOT_LOCKED" if is_locked else "SLOT_BOOKED",
                            "message": "待支付锁定时段未修改"
                            if is_locked
                            else "已支付预约时段未修改",
                            "date": current,
                            "slot_id": str(slot.public_id),
                        }
                    )
            current += timedelta(days=1)
        revision = _increment_revision(user)
        return {
            "schedule_version": revision.version,
            "updated_count": opened_count + closed_count,
            "opened_count": opened_count,
            "closed_count": closed_count,
            "deleted_count": 0,
            "skipped_locked_count": skipped_locked_count,
            "skipped_booked_count": skipped_booked_count,
            "failed_count": 0,
            "warnings": warnings,
            "errors": [],
        }


def create_schedule_slot(
    *,
    user: User,
    service_id: str | None,
    start_at,
    end_at,
) -> dict[str, Any]:
    """创建服务者通用或指定服务时段，并在用户锁内阻止时间重叠。"""

    require_provider_enabled(user)
    get_provider_profile(user)
    if service_id:
        raise _invalid("service_id", "当前排期不绑定服务，请创建服务者通用时段")
    if end_at <= start_at:
        raise _invalid("end_at", "结束时间必须晚于开始时间")
    unit_delta = timedelta(minutes=settings.SCHEDULE_SLOT_UNIT_MINUTES)
    if end_at - start_at != unit_delta:
        raise _invalid(
            "end_at",
            f"预约时段必须是 {settings.SCHEDULE_SLOT_UNIT_MINUTES} 分钟单元",
        )
    local_start = start_at.astimezone(ZoneInfo(settings.SCHEDULE_DEFAULT_TIMEZONE))
    if local_start.minute or local_start.second or local_start.microsecond:
        raise _invalid("start_at", "预约时段必须从整点开始")
    with transaction.atomic():
        User.objects.select_for_update().get(pk=user.pk)
        overlap = ScheduleSlot.objects.filter(
            provider_user=user,
            deleted_at__isnull=True,
            start_at__lt=end_at,
            end_at__gt=start_at,
        ).exists()
        if overlap:
            raise _invalid("start_at", "该时间段与其他预约时段重叠")
        slot = ScheduleSlot.objects.create(
            provider_user=user,
            service=None,
            start_at=start_at,
            end_at=end_at,
        )
        return _slot_mutation_payload(slot, _increment_revision(user))


def list_schedule_slots(
    *,
    user: User,
    service_id: str | None = None,
    request: HttpRequest | None = None,
) -> list[dict[str, Any]]:
    """返回服务者自己的预约时段。"""

    require_provider_enabled(user)
    get_provider_profile(user)
    queryset = ScheduleSlot.objects.select_related("service", "service__category").filter(
        provider_user=user,
        deleted_at__isnull=True,
    )
    if service_id:
        queryset = queryset.filter(service__public_id=service_id)
    return [_slot_payload(item, request) for item in queryset.order_by("start_at", "id")]


def delete_schedule_slot(
    *,
    user: User,
    slot_id: str,
    expected_version: int,
) -> dict[str, Any]:
    """逻辑删除未被订单锁定的预约时段。"""

    with transaction.atomic():
        User.objects.select_for_update().get(pk=user.pk)
        slot = (
            ScheduleSlot.objects.select_for_update()
            .filter(
                public_id=slot_id,
                provider_user=user,
                deleted_at__isnull=True,
            )
            .first()
        )
        if slot is None:
            raise _invalid("slot_id", "预约时段不存在")
        if slot.status != ScheduleSlot.Status.OPEN:
            raise _invalid("slot_id", "只有可预约时段可以删除")
        if slot.version != expected_version:
            raise ApiError(
                ErrorCode.SCHEDULE_VERSION_CONFLICT,
                ERROR_MESSAGES[ErrorCode.SCHEDULE_VERSION_CONFLICT],
                status_code=409,
            )
        slot.deleted_at = timezone.now()
        slot.status = ScheduleSlot.Status.CLOSED
        slot.version += 1
        slot.save(update_fields=["deleted_at", "status", "version", "updated_at"])
        revision = _increment_revision(user)
        return {
            "slot_id": str(slot.public_id),
            "deleted": True,
            "schedule_version": revision.version,
        }


def list_available_slots(
    *,
    provider_public_id: str,
    service_id: str | None = None,
    query_date: date | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    timezone_name: str | None = None,
) -> list[dict[str, Any]]:
    """返回公开服务者可预约时段；service_id 当前保留但不参与过滤。"""

    user = User.objects.filter(
        public_id=provider_public_id,
        provider_enabled=True,
        provider_status=User.ProviderStatus.APPROVED,
    ).first()
    if user is None:
        raise _invalid("provider_public_id", "服务者不存在或不可预约")
    normalized_timezone = _timezone_name(timezone_name or settings.SCHEDULE_DEFAULT_TIMEZONE)
    if query_date:
        date_from = query_date
        date_to = query_date
    elif date_from is None and date_to is None:
        local_today = timezone.now().astimezone(ZoneInfo(normalized_timezone)).date()
        date_from = local_today
        date_to = local_today
    queryset = ScheduleSlot.objects.select_related("service").filter(
        provider_user=user,
        status=ScheduleSlot.Status.OPEN,
        deleted_at__isnull=True,
    )
    if date_from:
        start_at = _local_datetime(date_from, time.min, normalized_timezone)
        queryset = queryset.filter(end_at__gt=start_at)
    if date_to:
        end_at = _local_datetime(date_to + timedelta(days=1), time.min, normalized_timezone)
        queryset = queryset.filter(start_at__lt=end_at)
    return [_public_slot_payload(item) for item in queryset.order_by("start_at", "id")]
