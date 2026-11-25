"""管理后台财务流水、佣金统计和 CSV 导出查询。"""

from __future__ import annotations

import csv
import io
from datetime import datetime, time, timedelta
from typing import Any

from django.db.models import Sum
from django.db.models.functions import TruncDate
from django.utils import timezone

from backend.common.display import enum_label
from backend.orders.models import Order
from backend.payments.models import Payment, Refund
from backend.payouts.models import EarningAccount, EarningEntry, EarningTransaction, Withdrawal
from backend.wallets.models import WalletTransaction


def _range_start(range_name: str) -> datetime:
    days = 7 if range_name == "7d" else 30
    today = timezone.localtime(timezone.now()).date()
    return timezone.make_aware(
        datetime.combine(today - timedelta(days=days - 1), time.min),
        timezone.get_current_timezone(),
    )


def _date_filters(start_at: datetime | None, end_at: datetime | None) -> dict[str, datetime]:
    filters = {}
    if start_at:
        filters["created_at__gte"] = start_at
    if end_at:
        filters["created_at__lt"] = end_at
    return filters


def finance_overview() -> dict[str, Any]:
    """返回平台支付、退款、佣金、收入和提现汇总。"""
    paid = (
        Payment.objects.filter(status=Payment.Status.SUCCESS).aggregate(total=Sum("amount_minor"))[
            "total"
        ]
        or 0
    )
    refunded = (
        Refund.objects.filter(status=Refund.Status.SUCCESS).aggregate(
            total=Sum("refund_amount_minor")
        )["total"]
        or 0
    )
    commission = (
        Order.objects.filter(
            paid_amount_minor__gt=0,
        ).aggregate(total=Sum("platform_commission_amount_minor"))["total"]
        or 0
    )
    provider_income = (
        EarningEntry.objects.filter(
            account__account_type=EarningAccount.AccountType.PROVIDER_INCOME,
            status=EarningEntry.Status.AVAILABLE,
        ).aggregate(total=Sum("net_amount_minor"))["total"]
        or 0
    )
    withdrawn = (
        Withdrawal.objects.filter(status=Withdrawal.Status.SUCCESS).aggregate(
            total=Sum("payout_amount_minor")
        )["total"]
        or 0
    )
    return {
        "paid_amount_minor": paid,
        "refunded_amount_minor": refunded,
        "platform_commission_amount_minor": commission,
        "provider_income_amount_minor": provider_income,
        "withdrawn_amount_minor": withdrawn,
        "currency": "CNY",
        "as_of": timezone.now(),
    }


def _wallet_rows(queryset) -> list[dict[str, Any]]:
    return [
        {
            "source_type": "WALLET",
            "transaction_no": str(item.transaction_no),
            "user_public_id": str(item.user.public_id),
            "direction": item.direction,
            "direction_text": enum_label(
                WalletTransaction.Direction,
                item.direction,
            ),
            "transaction_type": item.transaction_type,
            "transaction_type_text": enum_label(
                WalletTransaction.TransactionType,
                item.transaction_type,
            ),
            "business_type": item.business_type,
            "business_no": item.business_no,
            "currency": item.currency,
            "amount_minor": item.amount_minor,
            "balance_after_amount_minor": item.balance_after_amount_minor,
            "created_at": item.created_at,
        }
        for item in queryset
    ]


def _earning_rows(queryset) -> list[dict[str, Any]]:
    return [
        {
            "source_type": "EARNING",
            "transaction_no": str(item.transaction_no),
            "user_public_id": str(item.user.public_id),
            "direction": item.direction,
            "direction_text": enum_label(
                EarningTransaction.Direction,
                item.direction,
            ),
            "transaction_type": item.transaction_type,
            "transaction_type_text": enum_label(
                EarningTransaction.TransactionType,
                item.transaction_type,
            ),
            "business_type": item.business_type,
            "business_no": item.business_no,
            "currency": item.currency,
            "amount_minor": item.amount_minor,
            "balance_after_amount_minor": item.available_after_amount_minor,
            "created_at": item.created_at,
        }
        for item in queryset
    ]


def list_finance_transactions(
    *,
    source_type: str = "",
    user_public_id: str = "",
    start_at: datetime | None = None,
    end_at: datetime | None = None,
    page: int = 1,
    page_size: int = 20,
) -> dict[str, Any]:
    """合并钱包和收益流水并按创建时间倒序分页。"""
    wallet = WalletTransaction.objects.select_related("user")
    earning = EarningTransaction.objects.select_related("user")
    if user_public_id:
        wallet = wallet.filter(user__public_id=user_public_id)
        earning = earning.filter(user__public_id=user_public_id)
    wallet = wallet.filter(**_date_filters(start_at, end_at))
    earning = earning.filter(**_date_filters(start_at, end_at))
    rows = []
    if source_type in {"", "WALLET"}:
        rows.extend(_wallet_rows(wallet))
    if source_type in {"", "EARNING"}:
        rows.extend(_earning_rows(earning))
    rows.sort(key=lambda item: item["created_at"], reverse=True)
    total = len(rows)
    start = (page - 1) * page_size
    return {
        "items": rows[start : start + page_size],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


def export_finance_transactions(
    *,
    source_type: str = "",
    user_public_id: str = "",
    start_at: datetime | None = None,
    end_at: datetime | None = None,
) -> str:
    """生成财务流水 CSV 文本，不导出收款账户或密钥。"""
    result = list_finance_transactions(
        source_type=source_type,
        user_public_id=user_public_id,
        start_at=start_at,
        end_at=end_at,
        page=1,
        page_size=100000,
    )
    output = io.StringIO()
    writer = csv.DictWriter(
        output,
        fieldnames=[
            "source_type",
            "transaction_no",
            "user_public_id",
            "direction",
            "direction_text",
            "transaction_type",
            "transaction_type_text",
            "business_type",
            "business_no",
            "currency",
            "amount_minor",
            "balance_after_amount_minor",
            "created_at",
        ],
    )
    writer.writeheader()
    for row in result["items"]:
        writer.writerow({**row, "created_at": row["created_at"].isoformat()})
    return output.getvalue()


def commission_overview() -> dict[str, Any]:
    """返回平台服务者佣金汇总。"""
    now = timezone.localtime(timezone.now())
    today_start = timezone.make_aware(
        datetime.combine(now.date(), time.min),
        timezone.get_current_timezone(),
    )
    month_start = timezone.make_aware(
        datetime.combine(now.date().replace(day=1), time.min),
        timezone.get_current_timezone(),
    )

    def total(start_at: datetime | None = None) -> int:
        queryset = Order.objects.filter(platform_commission_amount_minor__gt=0)
        if start_at:
            queryset = queryset.filter(paid_at__gte=start_at)
        return queryset.aggregate(total=Sum("platform_commission_amount_minor"))["total"] or 0

    return {
        "commission_type": "PROVIDER_COMMISSION",
        "today_minor": total(today_start),
        "month_minor": total(month_start),
        "total_minor": total(),
        "settled_minor": EarningEntry.objects.filter(
            account__account_type=EarningAccount.AccountType.PROVIDER_INCOME,
            status=EarningEntry.Status.AVAILABLE,
        ).aggregate(total=Sum("platform_fee_amount_minor"))["total"]
        or 0,
        "pending_minor": EarningEntry.objects.filter(
            account__account_type=EarningAccount.AccountType.PROVIDER_INCOME,
            status=EarningEntry.Status.PENDING_SETTLEMENT,
        ).aggregate(total=Sum("platform_fee_amount_minor"))["total"]
        or 0,
        "currency": "CNY",
        "as_of": timezone.now(),
    }


def commission_trends(*, range_name: str = "7d") -> dict[str, Any]:
    """返回按支付日期统计的服务者佣金趋势。"""
    start = _range_start(range_name)
    days = 7 if range_name == "7d" else 30
    rows = {
        row["day"]: row["total"] or 0
        for row in Order.objects.filter(
            paid_at__gte=start,
            platform_commission_amount_minor__gt=0,
        )
        .annotate(day=TruncDate("paid_at"))
        .values("day")
        .annotate(total=Sum("platform_commission_amount_minor"))
    }
    items = []
    for offset in range(days):
        day = (timezone.localtime(start) + timedelta(days=offset)).date()
        items.append({"date": day.isoformat(), "commission_minor": rows.get(day, 0)})
    return {
        "range": {
            "name": "7d" if range_name == "7d" else "30d",
            "timezone": timezone.get_current_timezone_name(),
        },
        "items": items,
    }


def commission_details(
    *,
    provider_public_id: str = "",
    start_at: datetime | None = None,
    end_at: datetime | None = None,
    page: int = 1,
    page_size: int = 20,
) -> dict[str, Any]:
    """返回订单佣金明细。"""
    queryset = Order.objects.select_related("provider_user").filter(
        platform_commission_amount_minor__gt=0
    )
    if provider_public_id:
        queryset = queryset.filter(provider_user__public_id=provider_public_id)
    if start_at:
        queryset = queryset.filter(paid_at__gte=start_at)
    if end_at:
        queryset = queryset.filter(paid_at__lt=end_at)
    total = queryset.count()
    items = queryset.order_by("-paid_at", "-id")[(page - 1) * page_size : page * page_size]
    return {
        "items": [
            {
                "order_no": str(item.order_no),
                "provider_public_id": str(item.provider_user.public_id),
                "order_amount_minor": item.paid_amount_minor,
                "commission_rate_bps": (
                    item.platform_commission_amount_minor * 10000 // item.paid_amount_minor
                    if item.paid_amount_minor
                    else None
                ),
                "commission_amount_minor": item.platform_commission_amount_minor,
                "settlement_status": "SETTLED" if item.completed_at else "PENDING",
                "created_at": item.created_at,
            }
            for item in items
        ],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


def finance_reconciliation() -> dict[str, Any]:
    """返回支付、退款和佣金的内部账务核对结果。"""
    balance_payments = (
        Payment.objects.filter(
            status=Payment.Status.SUCCESS,
            payment_method=Payment.Method.BALANCE,
        ).aggregate(total=Sum("amount_minor"))["total"]
        or 0
    )
    wallet_payments = (
        WalletTransaction.objects.filter(
            transaction_type=WalletTransaction.TransactionType.ORDER_PAYMENT,
            direction=WalletTransaction.Direction.DEBIT,
        ).aggregate(total=Sum("amount_minor"))["total"]
        or 0
    )
    balance_refunds = (
        Refund.objects.filter(
            status=Refund.Status.SUCCESS,
            refund_method=Refund.Method.BALANCE,
        ).aggregate(total=Sum("refund_amount_minor"))["total"]
        or 0
    )
    wallet_refunds = (
        WalletTransaction.objects.filter(
            transaction_type=WalletTransaction.TransactionType.ORDER_REFUND,
            direction=WalletTransaction.Direction.CREDIT,
        ).aggregate(total=Sum("amount_minor"))["total"]
        or 0
    )
    order_commission = (
        Order.objects.filter(paid_amount_minor__gt=0).aggregate(
            total=Sum("platform_commission_amount_minor")
        )["total"]
        or 0
    )
    earning_commission = (
        EarningEntry.objects.filter(
            account__account_type=EarningAccount.AccountType.PROVIDER_INCOME,
        ).aggregate(total=Sum("platform_fee_amount_minor"))["total"]
        or 0
    )

    def item(name: str, left: int, right: int) -> dict[str, Any]:
        return {
            "name": name,
            "left_amount_minor": left,
            "right_amount_minor": right,
            "difference_amount_minor": left - right,
            "status": "MATCH" if left == right else "MISMATCH",
        }

    return {
        "items": [
            item("BALANCE_PAYMENT", balance_payments, wallet_payments),
            item("BALANCE_REFUND", balance_refunds, wallet_refunds),
            item("PROVIDER_COMMISSION", order_commission, earning_commission),
        ],
        "as_of": timezone.now(),
    }
