"""服务者数据看板的统计查询业务服务。"""

from __future__ import annotations

from datetime import datetime, time, timedelta
from typing import Any

from django.db.models import Count, Exists, OuterRef, Sum
from django.db.models.functions import TruncDate
from django.utils import timezone

from backend.catalog.services import format_price_amount
from backend.orders.models import Order
from backend.payouts.models import EarningAccount, EarningEntry
from backend.providers.models import ProviderAnalyticsEvent
from backend.reviews.models import Review


def _day_start(value: datetime) -> datetime:
    """返回当前时区当天零点。"""
    local_value = timezone.localtime(value)
    return timezone.make_aware(
        datetime.combine(local_value.date(), time.min),
        timezone.get_current_timezone(),
    )


def _period_metrics(
    *,
    provider_user,
    start_at: datetime,
    end_at: datetime,
) -> dict[str, Any]:
    """统计一个时间区间的服务者经营指标。"""
    orders = Order.objects.filter(provider_user=provider_user)
    events = ProviderAnalyticsEvent.objects.filter(
        provider_user=provider_user,
        occurred_at__gte=start_at,
        occurred_at__lt=end_at,
    )
    earnings = EarningEntry.objects.filter(
        user=provider_user,
        account__account_type=EarningAccount.AccountType.PROVIDER_INCOME,
        business_type="PROVIDER_ORDER_INCOME",
        created_at__gte=start_at,
        created_at__lt=end_at,
    )
    view_count = events.filter(event_type=ProviderAnalyticsEvent.EventType.PROFILE_VIEW).count()
    visitor_count = (
        events.filter(event_type=ProviderAnalyticsEvent.EventType.PROFILE_VIEW)
        .exclude(visitor_hash="")
        .values("visitor_hash")
        .distinct()
        .count()
    )
    created_order_count = orders.filter(
        created_at__gte=start_at,
        created_at__lt=end_at,
    ).count()
    completed_order_count = orders.filter(
        completed_at__gte=start_at,
        completed_at__lt=end_at,
    ).count()
    income_minor = earnings.aggregate(total=Sum("net_amount_minor"))["total"] or 0
    conversion_rate_bps = completed_order_count * 10000 // view_count if view_count else None
    return {
        "view_count": view_count,
        "visitor_count": visitor_count,
        "created_order_count": created_order_count,
        "completed_order_count": completed_order_count,
        "conversion_rate_bps": conversion_rate_bps,
        "income_minor": income_minor,
    }


def _comparison(current: dict[str, Any], previous: dict[str, Any]) -> dict[str, Any]:
    """计算当前周期相对上一周期的变化百分比。"""

    def delta_percent(current_value: int, previous_value: int) -> float | None:
        if previous_value == 0:
            return None
        return round((current_value - previous_value) * 100 / previous_value, 1)

    return {
        "view_count_delta_percent": delta_percent(current["view_count"], previous["view_count"]),
        "visitor_count_delta_percent": delta_percent(
            current["visitor_count"], previous["visitor_count"]
        ),
        "order_count_delta_percent": delta_percent(
            current["created_order_count"], previous["created_order_count"]
        ),
        "conversion_rate_delta_percent": (
            round(
                (current["conversion_rate_bps"] - previous["conversion_rate_bps"]) / 100,
                1,
            )
            if current["conversion_rate_bps"] is not None
            and previous["conversion_rate_bps"] is not None
            else None
        ),
        "income_delta_percent": delta_percent(current["income_minor"], previous["income_minor"]),
    }


def _funnel(provider_user, start_at: datetime, end_at: datetime) -> list[dict[str, Any]]:
    """按事件类型统计浏览到完成订单的转化漏斗。"""
    events = ProviderAnalyticsEvent.objects.filter(
        provider_user=provider_user,
        occurred_at__gte=start_at,
        occurred_at__lt=end_at,
    )
    labels = [
        (ProviderAnalyticsEvent.EventType.PROFILE_VIEW, "看到主页"),
        (ProviderAnalyticsEvent.EventType.SERVICE_VIEW, "查看服务"),
        (ProviderAnalyticsEvent.EventType.BOOKING_STARTED, "发起预约"),
        (ProviderAnalyticsEvent.EventType.PAYMENT_SUCCESS, "完成支付"),
        (ProviderAnalyticsEvent.EventType.ORDER_COMPLETED, "完成订单"),
    ]
    counts = {
        row["event_type"]: row["count"]
        for row in events.values("event_type").annotate(count=Count("id"))
    }
    return [
        {
            "event_type": event_type,
            "label": label,
            "count": counts.get(event_type, 0),
        }
        for event_type, label in labels
    ]


def _trend(provider_user, start_at: datetime, days: int) -> list[dict[str, Any]]:
    """生成按自然日的收入趋势，缺失日期补零。"""
    entries = (
        EarningEntry.objects.filter(
            user=provider_user,
            account__account_type=EarningAccount.AccountType.PROVIDER_INCOME,
            business_type="PROVIDER_ORDER_INCOME",
            created_at__gte=start_at,
            created_at__lt=timezone.now(),
        )
        .annotate(day=TruncDate("created_at"))
        .values("day")
        .annotate(
            income_minor=Sum("net_amount_minor"),
            order_count=Count("id"),
        )
    )
    values = {row["day"]: row for row in entries}
    result = []
    for offset in range(days):
        day = (timezone.localtime(start_at) + timedelta(days=offset)).date()
        row = values.get(day, {})
        income_minor = row.get("income_minor", 0) or 0
        result.append(
            {
                "date": day.isoformat(),
                "income_minor": income_minor,
                "income_display": format_price_amount(income_minor, "CNY"),
                "order_count": row.get("order_count", 0) or 0,
            }
        )
    return result


def provider_dashboard_payload(
    *,
    provider_user,
    range_name: str = "7d",
) -> dict[str, Any]:
    """返回服务者工作台和数据看板所需的汇总、趋势和漏斗数据。"""
    if range_name not in {"7d", "30d"}:
        range_name = "7d"
    days = 7 if range_name == "7d" else 30
    now = timezone.now()
    today_start = _day_start(now)
    current_start = today_start - timedelta(days=days - 1)
    previous_start = current_start - timedelta(days=days)
    previous_end = current_start
    current = _period_metrics(
        provider_user=provider_user,
        start_at=current_start,
        end_at=now,
    )
    previous = _period_metrics(
        provider_user=provider_user,
        start_at=previous_start,
        end_at=previous_end,
    )
    today = _period_metrics(
        provider_user=provider_user,
        start_at=today_start,
        end_at=now,
    )
    orders = Order.objects.filter(provider_user=provider_user)
    pending_review = (
        orders.filter(
            status=Order.Status.COMPLETED,
            review_expires_at__gt=now,
        )
        .annotate(
            has_review=Exists(
                Review.objects.filter(
                    order_no=OuterRef("order_no"),
                    user=OuterRef("user"),
                    status=Review.Status.VISIBLE,
                )
            )
        )
        .filter(has_review=False)
    )
    funnel = _funnel(provider_user, current_start, now)
    suggestions = []
    if current["view_count"] == 0:
        suggestions.append("浏览量数据尚未积累，前端请在访问主页和服务详情时携带匿名 visitor_id。")
    if pending_review.count():
        suggestions.append(
            f"有 {pending_review.count()} 个订单待用户评价，可在服务完成后适当引导用户评价。"
        )
    if current["conversion_rate_bps"] is not None and current["conversion_rate_bps"] < 500:
        suggestions.append("浏览到完成订单的转化率偏低，可优化服务介绍、价格和可约时段。")
    return {
        "range": {
            "name": range_name,
            "date_from": timezone.localtime(current_start).date().isoformat(),
            "date_to": timezone.localtime(now).date().isoformat(),
            "timezone": timezone.get_current_timezone_name(),
        },
        "today": {
            "income_minor": today["income_minor"],
            "income_display": format_price_amount(today["income_minor"], "CNY"),
            "created_order_count": today["created_order_count"],
            "pending_items": {
                "new_order_count": orders.filter(status=Order.Status.PENDING_ACCEPT).count(),
                "pending_confirm_count": orders.filter(status=Order.Status.PENDING_CONFIRM).count(),
                "pending_review_count": pending_review.count(),
            },
        },
        "overview": {
            **current,
            "income_display": format_price_amount(current["income_minor"], "CNY"),
            "tracking_available": current["view_count"] > 0 or current["visitor_count"] > 0,
        },
        "comparison": _comparison(current, previous),
        "income_trend": _trend(provider_user, current_start, days),
        "funnel": funnel,
        "suggestions": suggestions,
    }
