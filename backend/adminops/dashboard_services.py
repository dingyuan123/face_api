"""管理后台趋势和待处理事项查询。"""

from __future__ import annotations

from datetime import datetime, time, timedelta
from typing import Any

from django.db.models import Count, Sum
from django.db.models.functions import TruncDate
from django.utils import timezone

from backend.accounts.models import User
from backend.identity.models import IdentityVerification
from backend.orders.models import Order, OrderRefundRequest
from backend.payouts.models import EarningAccount, EarningEntry, Withdrawal
from backend.providers.models import ProviderApplication


def admin_dashboard_trends(*, range_name: str = "7d") -> dict[str, Any]:
    """返回管理后台每日新增用户、订单和收入趋势。"""
    days = 7 if range_name == "7d" else 30
    now = timezone.now()
    today = timezone.localtime(now).date()
    start = timezone.make_aware(
        datetime.combine(today - timedelta(days=days - 1), time.min),
        timezone.get_current_timezone(),
    )

    def counts(model, date_field: str) -> dict[Any, int]:
        return {
            row["day"]: row["count"]
            for row in model.objects.filter(**{f"{date_field}__gte": start})
            .annotate(day=TruncDate(date_field))
            .values("day")
            .annotate(count=Count("id"))
        }

    users = counts(User, "created_at")
    created_orders = counts(Order, "created_at")
    completed_orders = counts(Order, "completed_at")
    income = {
        row["day"]: row["total"] or 0
        for row in EarningEntry.objects.filter(
            account__account_type=EarningAccount.AccountType.PROVIDER_INCOME,
            created_at__gte=start,
        )
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
                "created_order_count": created_orders.get(day, 0),
                "completed_order_count": completed_orders.get(day, 0),
                "income_minor": income.get(day, 0),
            }
        )
    return {
        "range": {
            "name": "7d" if range_name == "7d" else "30d",
            "timezone": timezone.get_current_timezone_name(),
        },
        "items": items,
    }


def admin_dashboard_todos() -> dict[str, Any]:
    """返回管理后台待处理对象数量和安全预览。"""
    identity_items = list(
        IdentityVerification.objects.select_related("user")
        .filter(
            verification_type=IdentityVerification.Type.REAL_NAME,
            status=IdentityVerification.Status.PENDING,
        )
        .order_by("-submitted_at", "-id")[:20]
    )
    provider_items = list(
        ProviderApplication.objects.select_related("user")
        .filter(status=ProviderApplication.Status.PENDING)
        .order_by("-submitted_at", "-id")[:20]
    )
    refund_items = list(
        OrderRefundRequest.objects.select_related("order")
        .filter(status=OrderRefundRequest.Status.PENDING)
        .order_by("-created_at", "-id")[:20]
    )
    withdrawal_items = list(
        Withdrawal.objects.select_related("user")
        .filter(status=Withdrawal.Status.PENDING_REVIEW)
        .order_by("-created_at", "-id")[:20]
    )
    return {
        "pending_identity_count": len(identity_items),
        "pending_provider_application_count": len(provider_items),
        "pending_refund_count": len(refund_items),
        "pending_withdrawal_count": len(withdrawal_items),
        "pending_identity_items": [
            {
                "verification_no": str(item.verification_no),
                "user_public_id": str(item.user.public_id),
                "status": item.status,
                "submitted_at": item.submitted_at,
            }
            for item in identity_items
        ],
        "pending_provider_application_items": [
            {
                "application_no": item.application_no,
                "user_public_id": str(item.user.public_id),
                "status": item.status,
                "submitted_at": item.submitted_at,
            }
            for item in provider_items
        ],
        "pending_refund_items": [
            {
                "request_no": str(item.request_no),
                "order_no": str(item.order.order_no),
                "status": item.status,
                "created_at": item.created_at,
            }
            for item in refund_items
        ],
        "pending_withdrawal_items": [
            {
                "withdrawal_no": str(item.withdrawal_no),
                "user_public_id": str(item.user.public_id),
                "status": item.status,
                "created_at": item.created_at,
            }
            for item in withdrawal_items
        ],
    }
