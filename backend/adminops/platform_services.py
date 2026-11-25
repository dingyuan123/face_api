"""管理后台平台分析和系统配置业务服务。"""

from __future__ import annotations

from datetime import datetime, time, timedelta
from typing import Any

from django.conf import settings
from django.db import transaction
from django.db.models import Count, Sum
from django.db.models.functions import TruncDate
from django.utils import timezone

from backend.accounts.models import User
from backend.adminops.auth import write_admin_operation
from backend.adminops.models import Announcement, SystemSetting
from backend.catalog.models import ProviderService
from backend.common.display import enum_label
from backend.common.errors import ERROR_MESSAGES, ErrorCode
from backend.common.exceptions import ApiError
from backend.content.models import Moment
from backend.content.news_models import NewsArticle
from backend.orders.models import Order
from backend.payments.models import Payment
from backend.payouts.models import EarningAccount, EarningEntry


def _invalid(field: str, message: str) -> ApiError:
    return ApiError(
        ErrorCode.VALIDATION_ERROR,
        message,
        status_code=400,
        details={field: message},
    )


def _period_start(range_name: str) -> datetime:
    days = 7 if range_name == "7d" else 30
    today = timezone.localtime(timezone.now()).date()
    return timezone.make_aware(
        datetime.combine(today - timedelta(days=days - 1), time.min),
        timezone.get_current_timezone(),
    )


def platform_analytics_overview() -> dict[str, Any]:
    """返回平台用户、服务者、订单、内容和收入概览。"""
    income = (
        EarningEntry.objects.filter(
            account__account_type=EarningAccount.AccountType.PROVIDER_INCOME,
            status=EarningEntry.Status.AVAILABLE,
        ).aggregate(total=Sum("net_amount_minor"))["total"]
        or 0
    )
    return {
        "user_count": User.objects.count(),
        "provider_count": User.objects.filter(provider_enabled=True).count(),
        "service_count": ProviderService.objects.filter(deleted_at__isnull=True).count(),
        "order_count": Order.objects.count(),
        "completed_order_count": Order.objects.filter(status=Order.Status.COMPLETED).count(),
        "moment_count": Moment.objects.filter(deleted_at__isnull=True).count(),
        "news_count": NewsArticle.objects.filter(deleted_at__isnull=True).count(),
        "income_minor": income,
        "currency": "CNY",
        "as_of": timezone.now(),
    }


def platform_analytics_trends(*, range_name: str = "7d") -> dict[str, Any]:
    """返回平台每日用户、订单和收入趋势。"""
    start = _period_start(range_name)
    days = 7 if range_name == "7d" else 30

    def grouped(model, date_field: str) -> dict[Any, int]:
        return {
            row["day"]: row["count"]
            for row in model.objects.filter(**{f"{date_field}__gte": start})
            .annotate(day=TruncDate(date_field))
            .values("day")
            .annotate(count=Count("id"))
        }

    users = grouped(User, "created_at")
    orders = grouped(Order, "created_at")
    completed = grouped(Order, "completed_at")
    income = {
        row["day"]: row["total"] or 0
        for row in EarningEntry.objects.filter(created_at__gte=start)
        .annotate(day=TruncDate("created_at"))
        .values("day")
        .annotate(total=Sum("net_amount_minor"))
    }
    items = []
    for offset in range(days):
        day = (timezone.localtime(start) + timedelta(days=offset)).date()
        items.append(
            {
                "date": day.isoformat(),
                "new_user_count": users.get(day, 0),
                "created_order_count": orders.get(day, 0),
                "completed_order_count": completed.get(day, 0),
                "income_minor": income.get(day, 0),
            }
        )
    return {
        "range": {
            "name": "7d" if range_name == "7d" else "30d",
            "granularity": "day",
            "timezone": timezone.get_current_timezone_name(),
        },
        "items": items,
    }


def platform_analytics_breakdown(*, dimension: str = "city") -> dict[str, Any]:
    """按城市、类目、服务者或支付渠道返回订单分组。"""
    normalized_dimension = {
        "service_category": "category",
    }.get(dimension, dimension)
    if normalized_dimension not in {"city", "category", "provider", "channel"}:
        raise _invalid("dimension", "分析维度不存在")
    items: dict[str, dict[str, int]] = {}
    if normalized_dimension == "channel":
        rows = (
            Payment.objects.filter(status=Payment.Status.SUCCESS)
            .values("payment_method")
            .annotate(count=Count("id"), amount_minor=Sum("amount_minor"))
        )
        for row in rows:
            items[row["payment_method"]] = {
                "count": row["count"],
                "amount_minor": row["amount_minor"] or 0,
            }
    else:
        for order in Order.objects.select_related("provider_user", "service"):
            if normalized_dimension == "city":
                key = order.meeting_location_city or "未填写"
            elif normalized_dimension == "category":
                key = (order.service_snapshot or {}).get("category_code") or "未分类"
            else:
                key = str(order.provider_user.public_id)
            entry = items.setdefault(key, {"count": 0, "amount_minor": 0})
            entry["count"] += 1
            entry["amount_minor"] += order.paid_amount_minor
    return {
        "dimension": dimension,
        "items": [{"key": key, **values} for key, values in sorted(items.items())],
    }


SETTING_TYPES = {
    "PUBLIC_SHARE_BASE_URL": str,
    "PROVIDER_PLATFORM_COMMISSION_RATE_BPS": int,
    "REFERRAL_REWARD_RATE_BPS": int,
    "REFERRAL_REWARD_DELAY_DAYS": int,
    "REVIEW_WINDOW_DAYS": int,
    "HOME_FEED_GUEST_LIMIT": int,
    "HOME_FEED_AUTHENTICATED_LIMIT": int,
    "MOMENT_REVIEW_MODE": str,
}


def get_basic_settings() -> dict[str, Any]:
    """返回可维护的基础系统配置和版本。"""
    result = {}
    for key in SETTING_TYPES:
        record = SystemSetting.objects.filter(key=key).first()
        value = record.value if record else getattr(settings, key)
        result[key] = {
            "value": value,
            "version": record.version if record else 0,
            "description": record.description if record else "",
        }
    return {"settings": result, "requires_restart": True}


def update_basic_settings(
    *,
    operator,
    values: dict[str, Any],
    expected_versions: dict[str, int],
) -> dict[str, Any]:
    """保存基础系统配置，配置在服务重启后生效。"""
    if not values:
        raise _invalid("settings", "至少修改一个配置项")
    with transaction.atomic():
        for key, value in values.items():
            if key not in SETTING_TYPES:
                raise _invalid(f"settings.{key}", "配置项不允许修改")
            try:
                normalized = SETTING_TYPES[key](value)
            except (TypeError, ValueError) as exc:
                raise _invalid(f"settings.{key}", "配置值类型不正确") from exc
            record = SystemSetting.objects.select_for_update().filter(key=key).first()
            expected = int(expected_versions.get(key, 0))
            if record is None and expected != 0:
                raise ApiError(
                    ErrorCode.ADMIN_VERSION_CONFLICT,
                    ERROR_MESSAGES[ErrorCode.ADMIN_VERSION_CONFLICT],
                    status_code=409,
                )
            if record is not None and record.version != expected:
                raise ApiError(
                    ErrorCode.ADMIN_VERSION_CONFLICT,
                    ERROR_MESSAGES[ErrorCode.ADMIN_VERSION_CONFLICT],
                    status_code=409,
                )
            before = {"key": key, "value": record.value if record else getattr(settings, key)}
            if record is None:
                record = SystemSetting.objects.create(
                    key=key,
                    value=normalized,
                    description=f"管理员维护的 {key} 配置",
                    updated_by=operator.id,
                )
            else:
                record.value = normalized
                record.description = f"管理员维护的 {key} 配置"
                record.updated_by = operator.id
                record.version += 1
                record.save()
            write_admin_operation(
                operator=operator,
                action="SYSTEM_SETTING_UPDATE",
                target_type="SYSTEM_SETTING",
                target_id=key,
                before_state=before,
                after_state={"key": key, "value": record.value, "version": record.version},
            )
    return get_basic_settings()


def announcement_payload(item: Announcement) -> dict[str, Any]:
    return {
        "announcement_no": str(item.announcement_no),
        "title": item.title,
        "content": item.content,
        "status": item.status,
        "status_text": enum_label(Announcement.Status, item.status),
        "starts_at": item.starts_at,
        "ends_at": item.ends_at,
        "version": item.version,
        "created_at": item.created_at,
        "updated_at": item.updated_at,
    }


def list_announcements(*, status: str = "", page: int = 1, page_size: int = 20) -> dict[str, Any]:
    queryset = Announcement.objects.all()
    if status:
        queryset = queryset.filter(status=status)
    total = queryset.count()
    items = queryset.order_by("-updated_at", "-id")[(page - 1) * page_size : page * page_size]
    return {
        "items": [announcement_payload(item) for item in items],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


def create_announcement(*, operator, payload: dict[str, Any]) -> dict[str, Any]:
    item = Announcement.objects.create(
        title=payload["title"],
        content=payload["content"],
        status=payload.get("status", Announcement.Status.DRAFT),
        starts_at=payload.get("starts_at"),
        ends_at=payload.get("ends_at"),
        created_by=operator.id,
    )
    write_admin_operation(
        operator=operator,
        action="ANNOUNCEMENT_CREATE",
        target_type="ANNOUNCEMENT",
        target_id=str(item.announcement_no),
        after_state=announcement_payload(item),
    )
    return announcement_payload(item)


def update_announcement(
    *, operator, announcement_no: str, payload: dict[str, Any]
) -> dict[str, Any]:
    with transaction.atomic():
        item = (
            Announcement.objects.select_for_update().filter(announcement_no=announcement_no).first()
        )
        if item is None:
            raise ApiError(
                ErrorCode.NOT_FOUND,
                ERROR_MESSAGES[ErrorCode.NOT_FOUND],
                status_code=404,
            )
        if item.version != payload["expected_version"]:
            raise ApiError(
                ErrorCode.ADMIN_VERSION_CONFLICT,
                ERROR_MESSAGES[ErrorCode.ADMIN_VERSION_CONFLICT],
                status_code=409,
            )
        before = announcement_payload(item)
        for field in ("title", "content", "status", "starts_at", "ends_at"):
            if field in payload:
                setattr(item, field, payload[field])
        item.version += 1
        item.save()
        result = announcement_payload(item)
        write_admin_operation(
            operator=operator,
            action="ANNOUNCEMENT_UPDATE",
            target_type="ANNOUNCEMENT",
            target_id=str(item.announcement_no),
            before_state=before,
            after_state=result,
        )
        return result


def list_city_settings() -> list[dict[str, Any]]:
    """返回城市配置。"""
    from backend.profiles.models import ProfileCityOption

    return [
        {
            "code": item.code,
            "name": item.name,
            "sort_order": item.sort_order,
            "is_active": item.is_active,
            "version": item.version,
        }
        for item in ProfileCityOption.objects.order_by("sort_order", "id")
    ]


def create_city_setting(*, operator, payload: dict[str, Any]) -> dict[str, Any]:
    """创建城市配置。"""
    from backend.profiles.models import ProfileCityOption

    code = str(payload.get("code", "")).strip()
    name = str(payload.get("name", "")).strip()
    if not code or not name:
        raise _invalid("code", "城市代码和名称不能为空")
    item = ProfileCityOption.objects.create(
        code=code,
        name=name,
        sort_order=int(payload.get("sort_order", 0)),
        is_active=bool(payload.get("is_active", True)),
    )
    write_admin_operation(
        operator=operator,
        action="CITY_CREATE",
        target_type="CITY",
        target_id=code,
        after_state={"code": code, "name": name, "version": item.version},
    )
    return {
        "code": item.code,
        "name": item.name,
        "sort_order": item.sort_order,
        "is_active": item.is_active,
        "version": item.version,
    }


def update_city_setting(*, operator, code: str, payload: dict[str, Any]) -> dict[str, Any]:
    """修改或停用城市配置。"""
    from backend.profiles.models import ProfileCityOption

    with transaction.atomic():
        item = ProfileCityOption.objects.select_for_update().filter(code=code).first()
        if item is None:
            raise ApiError(
                ErrorCode.NOT_FOUND,
                ERROR_MESSAGES[ErrorCode.NOT_FOUND],
                status_code=404,
            )
        if item.version != payload["expected_version"]:
            raise ApiError(
                ErrorCode.ADMIN_VERSION_CONFLICT,
                ERROR_MESSAGES[ErrorCode.ADMIN_VERSION_CONFLICT],
                status_code=409,
            )
        before = {"code": item.code, "name": item.name, "version": item.version}
        for field in ("name", "sort_order", "is_active"):
            if field in payload:
                setattr(item, field, payload[field])
        item.version += 1
        item.save()
        write_admin_operation(
            operator=operator,
            action="CITY_UPDATE",
            target_type="CITY",
            target_id=code,
            before_state=before,
            after_state={"code": item.code, "name": item.name, "version": item.version},
        )
        return {
            "code": item.code,
            "name": item.name,
            "sort_order": item.sort_order,
            "is_active": item.is_active,
            "version": item.version,
        }


def list_service_category_settings() -> list[dict[str, Any]]:
    """返回服务类目配置。"""
    from backend.catalog.models import ServiceCategory

    return [
        {
            "code": item.code,
            "name": item.name,
            "sort_order": item.sort_order,
            "is_active": item.is_active,
            "version": item.version,
        }
        for item in ServiceCategory.objects.order_by("sort_order", "id")
    ]


def create_service_category_setting(*, operator, payload: dict[str, Any]) -> dict[str, Any]:
    """创建服务类目配置。"""
    from backend.catalog.models import ServiceCategory

    code = str(payload.get("code", "")).strip()
    name = str(payload.get("name", "")).strip()
    if not code or not name:
        raise _invalid("code", "服务类目代码和名称不能为空")
    item = ServiceCategory.objects.create(
        code=code,
        name=name,
        sort_order=int(payload.get("sort_order", 0)),
        is_active=bool(payload.get("is_active", True)),
    )
    write_admin_operation(
        operator=operator,
        action="SERVICE_CATEGORY_CREATE",
        target_type="SERVICE_CATEGORY",
        target_id=code,
        after_state={"code": code, "name": name, "version": item.version},
    )
    return {
        "code": item.code,
        "name": item.name,
        "sort_order": item.sort_order,
        "is_active": item.is_active,
        "version": item.version,
    }


def update_service_category_setting(
    *,
    operator,
    code: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    """修改或停用服务类目配置。"""
    from backend.catalog.models import ServiceCategory

    with transaction.atomic():
        item = ServiceCategory.objects.select_for_update().filter(code=code).first()
        if item is None:
            raise ApiError(
                ErrorCode.NOT_FOUND,
                ERROR_MESSAGES[ErrorCode.NOT_FOUND],
                status_code=404,
            )
        if item.version != payload["expected_version"]:
            raise ApiError(
                ErrorCode.ADMIN_VERSION_CONFLICT,
                ERROR_MESSAGES[ErrorCode.ADMIN_VERSION_CONFLICT],
                status_code=409,
            )
        before = {"code": item.code, "name": item.name, "version": item.version}
        for field in ("name", "sort_order", "is_active"):
            if field in payload:
                setattr(item, field, payload[field])
        item.version += 1
        item.save()
        write_admin_operation(
            operator=operator,
            action="SERVICE_CATEGORY_UPDATE",
            target_type="SERVICE_CATEGORY",
            target_id=code,
            before_state=before,
            after_state={"code": item.code, "name": item.name, "version": item.version},
        )
        return {
            "code": item.code,
            "name": item.name,
            "sort_order": item.sort_order,
            "is_active": item.is_active,
            "version": item.version,
        }


def get_commission_rules() -> dict[str, Any]:
    """返回平台服务者佣金和推广奖励默认比例。"""
    settings_data = get_basic_settings()["settings"]
    return {
        "provider_commission_rate_bps": settings_data["PROVIDER_PLATFORM_COMMISSION_RATE_BPS"][
            "value"
        ],
        "referral_reward_rate_bps": settings_data["REFERRAL_REWARD_RATE_BPS"]["value"],
        "versions": {
            "PROVIDER_PLATFORM_COMMISSION_RATE_BPS": settings_data[
                "PROVIDER_PLATFORM_COMMISSION_RATE_BPS"
            ]["version"],
            "REFERRAL_REWARD_RATE_BPS": settings_data["REFERRAL_REWARD_RATE_BPS"]["version"],
        },
        "requires_restart": True,
    }


def update_commission_rules(
    *,
    operator,
    payload: dict[str, Any],
) -> dict[str, Any]:
    """更新佣金和推广奖励默认比例，历史订单仍使用原快照。"""
    mapped_values = {
        "PROVIDER_PLATFORM_COMMISSION_RATE_BPS": payload.get("provider_commission_rate_bps"),
        "REFERRAL_REWARD_RATE_BPS": payload.get("referral_reward_rate_bps"),
    }
    values = {key: value for key, value in mapped_values.items() if value is not None}
    update_basic_settings(
        operator=operator,
        values=values,
        expected_versions=payload.get("expected_versions", {}),
    )
    return get_commission_rules()
