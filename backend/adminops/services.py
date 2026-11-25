"""管理后台总览、用户、服务者、审计和角色权限业务服务。"""

from __future__ import annotations

from typing import Any

from django.db import IntegrityError, transaction
from django.db.models import (
    Count,
    F,
    Max,
    OuterRef,
    Q,
    Subquery,
    Sum,
)
from django.http import HttpRequest
from django.utils import timezone

from backend.accounts.models import AuthToken, User
from backend.adminops.auth import write_admin_operation
from backend.adminops.display import (
    audit_action_label,
    audit_target_type_label,
)
from backend.adminops.models import (
    AdminAuthToken,
    AdminPermission,
    AdminRole,
    AdminRoleMember,
    AdminRolePermission,
)
from backend.common.display import enum_label
from backend.common.errors import ERROR_MESSAGES, ErrorCode
from backend.common.exceptions import ApiError
from backend.identity.models import IdentityVerification
from backend.media.services import get_media_payloads
from backend.orders.models import Order, OrderRefundRequest
from backend.orders.services import cancel_order, order_payload
from backend.payouts.models import (
    EarningAccount,
    EarningEntry,
    EarningTransaction,
    Withdrawal,
)
from backend.payouts.services import (
    approve_withdrawal,
    list_withdrawals,
    payout_method_payload,
    reject_withdrawal,
    retry_withdrawal,
    withdrawal_payload,
)
from backend.providers.models import ProviderApplication, ProviderProfile
from backend.reviews.models import Review
from backend.reviews.services import review_payload
from backend.support.models import SupportTicket
from backend.support.services import ticket_payload
from backend.wallets.models import WalletTransaction


def _invalid(field: str, message: str) -> ApiError:
    return ApiError(
        ErrorCode.VALIDATION_ERROR,
        message,
        status_code=400,
        details={field: message},
    )


def admin_dashboard_payload() -> dict[str, Any]:
    """返回平台管理总览指标。"""
    return {
        "user_count": User.objects.count(),
        "provider_count": User.objects.filter(
            provider_enabled=True,
            provider_status=User.ProviderStatus.APPROVED,
        ).count(),
        "order_count": Order.objects.count(),
        "pending_identity_count": IdentityVerification.objects.filter(
            verification_type=IdentityVerification.Type.REAL_NAME,
            status=IdentityVerification.Status.PENDING,
        ).count(),
        "pending_provider_application_count": ProviderApplication.objects.filter(
            status=ProviderApplication.Status.PENDING
        ).count(),
        "pending_refund_count": OrderRefundRequest.objects.filter(
            status=OrderRefundRequest.Status.PENDING
        ).count(),
        "pending_withdrawal_count": Withdrawal.objects.filter(
            status=Withdrawal.Status.PENDING_REVIEW
        ).count(),
        "total_income_minor": EarningEntry.objects.filter(
            account__account_type=EarningAccount.AccountType.PROVIDER_INCOME,
            status=EarningEntry.Status.AVAILABLE,
        ).aggregate(total=Sum("net_amount_minor"))["total"]
        or 0,
    }


def _user_avatar_payload(user: User, request: HttpRequest | None = None) -> dict[str, Any] | None:
    """返回用户头像临时展示信息，不暴露原文件路径。"""
    profile = getattr(user, "profile", None)
    provider_profile = getattr(user, "provider_profile", None)
    media_id = getattr(profile, "avatar_media_id", None) or getattr(
        provider_profile, "avatar_media_id", None
    )
    if not media_id:
        return None
    payloads = get_media_payloads([str(media_id)], request)
    return payloads[0] if payloads else None


def _amount_summary(amount_minor: int) -> dict[str, Any]:
    """按平台统一金额结构返回人民币分和展示值。"""
    return {
        "currency": "CNY",
        "amount_minor": int(amount_minor or 0),
        "amount_display": f"{(amount_minor or 0) / 100:.2f}",
    }


def _finance_account_payload(
    *,
    account_type: str,
    currency: str,
    balance_amount_minor: int,
    frozen_amount_minor: int,
    total_income_amount_minor: int,
    total_withdrawn_amount_minor: int,
    credited_amount_minor: int = 0,
    debited_amount_minor: int = 0,
) -> dict[str, Any]:
    """返回只读资金账户摘要。"""
    return {
        "account_type": account_type,
        "currency": currency,
        "available": _amount_summary(balance_amount_minor),
        "frozen": _amount_summary(frozen_amount_minor),
        "total_income": _amount_summary(total_income_amount_minor),
        "total_withdrawn": _amount_summary(total_withdrawn_amount_minor),
        "credited": _amount_summary(credited_amount_minor),
        "debited": _amount_summary(debited_amount_minor),
    }


def admin_user_payload(user: User, request: HttpRequest | None = None) -> dict[str, Any]:
    """返回管理员用户列表安全摘要和常用经营概览。"""
    profile = getattr(user, "profile", None)
    provider_profile = getattr(user, "provider_profile", None)
    order_total = getattr(user, "customer_order_total", None)
    order_completed = getattr(user, "customer_order_completed", None)
    order_paid = getattr(user, "customer_order_paid_amount_minor", None)
    provider_order_total = getattr(user, "provider_order_total", None)
    provider_order_completed = getattr(user, "provider_order_completed", None)
    provider_order_paid = getattr(user, "provider_order_paid_amount_minor", None)
    if order_total is None:
        order_summary = user.orders.aggregate(
            total=Count("id"),
            completed=Count("id", filter=Q(status=Order.Status.COMPLETED)),
            total_paid_minor=Sum("paid_amount_minor"),
        )
        order_total = order_summary["total"] or 0
        order_completed = order_summary["completed"] or 0
        order_paid = order_summary["total_paid_minor"] or 0
    if provider_order_total is None:
        provider_order_summary = user.provider_orders.aggregate(
            total=Count("id"),
            completed=Count("id", filter=Q(status=Order.Status.COMPLETED)),
            total_paid_minor=Sum("paid_amount_minor"),
        )
        provider_order_total = provider_order_summary["total"] or 0
        provider_order_completed = provider_order_summary["completed"] or 0
        provider_order_paid = provider_order_summary["total_paid_minor"] or 0
    return {
        "user_public_id": str(user.public_id),
        "nickname": (
            getattr(profile, "nickname", None) or getattr(provider_profile, "nickname", None)
        ),
        "avatar_media": _user_avatar_payload(user, request),
        "phone_masked": user.phone_masked,
        "status": user.status,
        "status_text": enum_label(User.Status, user.status),
        "is_staff": user.is_staff,
        "primary_role": user.primary_role,
        "primary_role_text": enum_label(User.InitialRole, user.primary_role),
        "initial_role_selected": user.initial_role_selected,
        "default_workspace": user.default_workspace,
        "default_workspace_text": enum_label(User.Workspace, user.default_workspace),
        "provider_status": user.provider_status,
        "provider_status_text": enum_label(User.ProviderStatus, user.provider_status),
        "provider_enabled": user.provider_enabled,
        "last_login_at": user.last_login_at,
        "order_count": order_total or 0,
        "completed_order_count": order_completed or 0,
        "provider_order_count": provider_order_total or 0,
        "provider_completed_order_count": provider_order_completed or 0,
        "total_paid_amount_minor": order_paid or 0,
        "provider_sales_amount_minor": provider_order_paid or 0,
        "version": user.version,
        "created_at": user.created_at,
        "updated_at": user.updated_at,
    }


def admin_user_detail_payload(user: User, request: HttpRequest | None = None) -> dict[str, Any]:
    """返回管理员用户详情、资金、业务、安全和客服概览。"""
    profile = getattr(user, "profile", None)
    provider_profile = getattr(user, "provider_profile", None)
    application = user.provider_applications.order_by("-submitted_at", "-id").first()
    identity = (
        user.identity_verifications.filter(verification_type=IdentityVerification.Type.REAL_NAME)
        .order_by("-updated_at", "-id")
        .first()
    )
    wallet = user.wallet_accounts.filter(currency="CNY").order_by("id").first()
    earning_accounts = {
        item.account_type: item
        for item in user.earning_accounts.filter(currency="CNY").order_by("id")
    }
    provider_earning = earning_accounts.get(EarningAccount.AccountType.PROVIDER_INCOME)
    referral_earning = earning_accounts.get(EarningAccount.AccountType.REFERRAL_REWARD)
    provider_rating = getattr(user, "rating_stat", None)
    earning_summary = user.earning_entries.aggregate(
        gross_total_minor=Sum("gross_amount_minor"),
        platform_fee_total_minor=Sum("platform_fee_amount_minor"),
        net_total_minor=Sum("net_amount_minor"),
        pending_settlement_minor=Sum(
            "net_amount_minor",
            filter=Q(status=EarningEntry.Status.PENDING_SETTLEMENT),
        ),
    )
    wallet_summary = user.wallet_transactions.aggregate(
        credit_amount_minor=Sum(
            "amount_minor", filter=Q(direction=WalletTransaction.Direction.CREDIT)
        ),
        debit_amount_minor=Sum(
            "amount_minor", filter=Q(direction=WalletTransaction.Direction.DEBIT)
        ),
    )
    order_summary = user.orders.aggregate(
        total=Count("id"),
        completed=Count("id", filter=Q(status=Order.Status.COMPLETED)),
        canceled=Count("id", filter=Q(status=Order.Status.CANCELED)),
        refunded=Count("id", filter=Q(status=Order.Status.REFUNDED)),
        paid_amount_minor=Sum("paid_amount_minor"),
        refunded_amount_minor=Sum("refunded_amount_minor"),
    )
    provider_order_summary = user.provider_orders.aggregate(
        total=Count("id"),
        completed=Count("id", filter=Q(status=Order.Status.COMPLETED)),
        canceled=Count("id", filter=Q(status=Order.Status.CANCELED)),
        paid_amount_minor=Sum("paid_amount_minor"),
    )
    interest_codes = []
    if profile:
        interest_codes = list(
            profile.interest_links.order_by("sort_order", "id").values_list("tag__code", flat=True)
        )
    profile_media_ids = []
    if profile and profile.avatar_media_id:
        profile_media_ids.append(str(profile.avatar_media_id))
    if provider_profile and provider_profile.avatar_media_id:
        profile_media_ids.append(str(provider_profile.avatar_media_id))
    profile_media = {
        item["media_id"]: item for item in get_media_payloads(profile_media_ids, request)
    }
    profile_avatar_id = (
        str(profile.avatar_media_id) if profile and profile.avatar_media_id else None
    )
    provider_avatar_id = (
        str(provider_profile.avatar_media_id)
        if provider_profile and provider_profile.avatar_media_id
        else None
    )
    provider_photo_ids = (
        list(
            provider_profile.photo_links.order_by("position", "id").values_list(
                "media_id", flat=True
            )
        )
        if provider_profile
        else []
    )
    return {
        "basic": admin_user_payload(user, request),
        "profile": {
            "nickname": getattr(profile, "nickname", None),
            "gender": getattr(profile, "gender", None),
            "age": getattr(profile, "age", None),
            "city_code": getattr(profile, "city_code", None),
            "signature": getattr(profile, "signature", ""),
            "interest_codes": interest_codes,
            "trust_level_code": getattr(profile, "trust_level_code", "UNSET"),
            "trust_level_name": getattr(profile, "trust_level_name", ""),
            "avatar_media": profile_media.get(profile_avatar_id),
            "profile_version": getattr(profile, "version", None),
            "updated_at": getattr(profile, "updated_at", None),
        },
        "identity": {
            "verification_type": identity.verification_type
            if identity
            else IdentityVerification.Type.REAL_NAME,
            "status": identity.status if identity else IdentityVerification.Status.NOT_SUBMITTED,
            "reject_reason": identity.reject_reason if identity else "",
            "has_id_card_media": bool(
                identity and (identity.id_card_front_media_id or identity.id_card_back_media_id)
            ),
            "submitted_at": identity.submitted_at if identity else None,
            "verified_at": identity.verified_at if identity else None,
        },
        "provider": {
            "provider_status": user.provider_status,
            "provider_status_text": enum_label(
                User.ProviderStatus,
                user.provider_status,
            ),
            "provider_enabled": user.provider_enabled,
            "nickname": getattr(provider_profile, "nickname", None),
            "signature": getattr(provider_profile, "signature", ""),
            "introduction": getattr(provider_profile, "introduction", ""),
            "avatar_media": profile_media.get(provider_avatar_id),
            "photo_media": get_media_payloads(provider_photo_ids, request),
            "application_no": str(application.application_no) if application else None,
            "application_status": application.status if application else None,
            "application_status_text": enum_label(
                ProviderApplication.Status,
                application.status,
            )
            if application
            else "未提交",
            "application_submitted_at": application.submitted_at if application else None,
            "rating_average": str(provider_rating.rating_average) if provider_rating else "0.00",
            "review_count": provider_rating.review_count if provider_rating else 0,
            "completed_order_count": provider_order_summary["completed"] or 0,
            "sales_amount": _amount_summary(provider_order_summary["paid_amount_minor"] or 0),
        },
        "finance": {
            "wallet": _finance_account_payload(
                account_type="WALLET",
                currency=getattr(wallet, "currency", "CNY"),
                balance_amount_minor=getattr(wallet, "balance_amount_minor", 0),
                frozen_amount_minor=getattr(wallet, "frozen_amount_minor", 0),
                total_income_amount_minor=0,
                total_withdrawn_amount_minor=0,
                credited_amount_minor=wallet_summary["credit_amount_minor"] or 0,
                debited_amount_minor=wallet_summary["debit_amount_minor"] or 0,
            ),
            "provider_earning": _finance_account_payload(
                account_type=EarningAccount.AccountType.PROVIDER_INCOME,
                currency=getattr(provider_earning, "currency", "CNY"),
                balance_amount_minor=getattr(provider_earning, "available_amount_minor", 0),
                frozen_amount_minor=getattr(provider_earning, "frozen_amount_minor", 0),
                total_income_amount_minor=getattr(provider_earning, "total_income_amount_minor", 0),
                total_withdrawn_amount_minor=getattr(
                    provider_earning, "total_withdrawn_amount_minor", 0
                ),
            ),
            "referral_earning": _finance_account_payload(
                account_type=EarningAccount.AccountType.REFERRAL_REWARD,
                currency=getattr(referral_earning, "currency", "CNY"),
                balance_amount_minor=getattr(referral_earning, "available_amount_minor", 0),
                frozen_amount_minor=getattr(referral_earning, "frozen_amount_minor", 0),
                total_income_amount_minor=getattr(referral_earning, "total_income_amount_minor", 0),
                total_withdrawn_amount_minor=getattr(
                    referral_earning, "total_withdrawn_amount_minor", 0
                ),
            ),
            "withdrawal_pending": _amount_summary(
                user.withdrawals.filter(
                    status__in=[
                        Withdrawal.Status.PENDING_REVIEW,
                        Withdrawal.Status.PROCESSING,
                    ]
                ).aggregate(total=Sum("amount_minor"))["total"]
                or 0
            ),
            "payout_methods": [
                payout_method_payload(item)
                for item in user.payout_methods.order_by("-is_default", "-created_at", "-id")
            ],
            "earning_summary": {
                "gross": _amount_summary(earning_summary["gross_total_minor"] or 0),
                "platform_commission": _amount_summary(
                    earning_summary["platform_fee_total_minor"] or 0
                ),
                "net_income": _amount_summary(earning_summary["net_total_minor"] or 0),
                "pending_settlement": _amount_summary(
                    earning_summary["pending_settlement_minor"] or 0
                ),
                "referral_reward_total": _amount_summary(
                    user.earning_entries.filter(
                        account__account_type=EarningAccount.AccountType.REFERRAL_REWARD
                    ).aggregate(total=Sum("net_amount_minor"))["total"]
                    or 0
                ),
            },
        },
        "orders": {
            "customer_total": order_summary["total"] or 0,
            "customer_completed": order_summary["completed"] or 0,
            "customer_canceled": order_summary["canceled"] or 0,
            "customer_refunded": order_summary["refunded"] or 0,
            "customer_paid_amount": _amount_summary(order_summary["paid_amount_minor"] or 0),
            "customer_refunded_amount": _amount_summary(
                order_summary["refunded_amount_minor"] or 0
            ),
            "provider_total": provider_order_summary["total"] or 0,
            "provider_completed": provider_order_summary["completed"] or 0,
            "provider_canceled": provider_order_summary["canceled"] or 0,
            "provider_paid_amount": _amount_summary(
                provider_order_summary["paid_amount_minor"] or 0
            ),
            "latest_at": user.orders.aggregate(latest=Max("created_at"))["latest"],
        },
        "social": {
            "review_given_count": user.reviews.filter(status=Review.Status.VISIBLE).count(),
            "review_received_count": user.received_reviews.filter(
                status=Review.Status.VISIBLE
            ).count(),
            "support_ticket_count": user.support_tickets.count(),
            "open_support_ticket_count": user.support_tickets.exclude(
                status__in=[
                    SupportTicket.Status.RESOLVED,
                    SupportTicket.Status.CLOSED,
                ]
            ).count(),
        },
        "security": {
            "phone_bound": bool(user.phone_hash),
            "last_login_at": user.last_login_at,
            "active_token_count": user.auth_tokens.filter(
                token_type="ACCESS", revoked_at__isnull=True, expires_at__gt=timezone.now()
            ).count(),
            "auth_types": list(
                user.auths.filter(status="ENABLED").values_list("auth_type", flat=True)
            ),
        },
    }


def _admin_user_order_payload(order: Order, request: HttpRequest | None = None) -> dict[str, Any]:
    """返回管理员用户关联订单摘要，不返回完整手机号和证件信息。"""
    snapshot = order.service_snapshot or {}
    cover_media_id = snapshot.get("cover_media_id")
    if order.service and order.service.cover_media_id:
        cover_media_id = order.service.cover_media_id
    cover_media = get_media_payloads([str(cover_media_id)], request) if cover_media_id else []
    return {
        "order_no": str(order.order_no),
        "role": "CUSTOMER" if getattr(order, "_admin_user_role", "") == "CUSTOMER" else "PROVIDER",
        "status": order.status,
        "service_title": order.service.title if order.service else snapshot.get("title", ""),
        "cover_media": cover_media[0] if cover_media else None,
        "currency": order.currency,
        "payable_amount_minor": order.payable_amount_minor,
        "paid_amount_minor": order.paid_amount_minor,
        "refunded_amount_minor": order.refunded_amount_minor,
        "created_at": order.created_at,
        "paid_at": order.paid_at,
        "completed_at": order.completed_at,
    }


def list_admin_user_orders(
    *,
    user: User,
    role: str = "ALL",
    status: str = "",
    page: int = 1,
    page_size: int = 20,
    request: HttpRequest | None = None,
) -> dict[str, Any]:
    """分页查看用户作为下单方或服务者参与的订单。"""
    if role not in {"ALL", "CUSTOMER", "PROVIDER"}:
        raise _invalid("role", "订单参与角色不存在")
    if status and status not in Order.Status.values:
        raise _invalid("status", "订单状态不存在")
    queryset = Order.objects.select_related("service").filter(Q(user=user) | Q(provider_user=user))
    if role == "CUSTOMER":
        queryset = queryset.filter(user=user)
    elif role == "PROVIDER":
        queryset = queryset.filter(provider_user=user)
    if status:
        queryset = queryset.filter(status=status)
    total = queryset.count()
    items = []
    for order in queryset.order_by("-created_at", "-id")[(page - 1) * page_size : page * page_size]:
        payload = _admin_user_order_payload(order, request)
        payload["role"] = "CUSTOMER" if order.user_id == user.id else "PROVIDER"
        items.append(payload)
    return {"items": items, "total": total, "page": page, "page_size": page_size}


def _wallet_transaction_payload(item: WalletTransaction) -> dict[str, Any]:
    """返回管理员可见钱包流水摘要。"""
    return {
        "ledger_type": "WALLET",
        "transaction_no": str(item.transaction_no),
        "account_type": "WALLET",
        "account_type_text": "钱包余额",
        "direction": item.direction,
        "direction_text": enum_label(WalletTransaction.Direction, item.direction),
        "transaction_type": item.transaction_type,
        "transaction_type_text": enum_label(
            WalletTransaction.TransactionType,
            item.transaction_type,
        ),
        "business_type": item.business_type,
        "business_no": item.business_no,
        "currency": item.currency,
        "amount_minor": item.amount_minor,
        "available_after_amount_minor": item.balance_after_amount_minor,
        "created_at": item.created_at,
    }


def _earning_entry_payload(item: EarningEntry) -> dict[str, Any]:
    """返回管理员可见收益业务记录摘要。"""
    return {
        "ledger_type": "EARNING_ENTRY",
        "transaction_no": str(item.earning_no),
        "account_type": item.account.account_type,
        "account_type_text": enum_label(
            EarningAccount.AccountType,
            item.account.account_type,
        ),
        "direction": "CREDIT",
        "transaction_type": item.business_type,
        "transaction_type_text": item.business_type,
        "business_type": item.business_type,
        "business_no": item.business_no,
        "currency": item.currency,
        "amount_minor": item.net_amount_minor,
        "gross_amount_minor": item.gross_amount_minor,
        "platform_fee_amount_minor": item.platform_fee_amount_minor,
        "status": item.status,
        "status_text": enum_label(EarningEntry.Status, item.status),
        "available_at": item.available_at,
        "settled_at": item.settled_at,
        "created_at": item.created_at,
    }


def _earning_transaction_payload(item: EarningTransaction) -> dict[str, Any]:
    """返回管理员可见收益资金流水摘要。"""
    return {
        "ledger_type": "EARNING_TRANSACTION",
        "transaction_no": str(item.transaction_no),
        "account_type": item.account.account_type,
        "account_type_text": enum_label(
            EarningAccount.AccountType,
            item.account.account_type,
        ),
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
        "available_after_amount_minor": item.available_after_amount_minor,
        "frozen_after_amount_minor": item.frozen_after_amount_minor,
        "created_at": item.created_at,
    }


def list_admin_user_finance(
    *,
    user: User,
    ledger_type: str = "ALL",
    page: int = 1,
    page_size: int = 20,
) -> dict[str, Any]:
    """分页查看用户钱包、收益记录和收益流水。"""
    if ledger_type not in {"ALL", "WALLET", "EARNING"}:
        raise _invalid("ledger_type", "资金明细类型不存在")
    wallet_items = []
    earning_entry_items = []
    earning_transaction_items = []
    if ledger_type in {"ALL", "WALLET"}:
        wallet_items = list(
            user.wallet_transactions.select_related("account").order_by("-created_at", "-id")
        )
    if ledger_type in {"ALL", "EARNING"}:
        earning_entry_items = list(
            user.earning_entries.select_related("account").order_by("-created_at", "-id")
        )
        earning_transaction_items = list(
            user.earning_transactions.select_related("account").order_by("-created_at", "-id")
        )
    combined = [
        *(_wallet_transaction_payload(item) for item in wallet_items),
    ]
    combined.extend(
        sorted(
            [
                *(_earning_entry_payload(item) for item in earning_entry_items),
                *(_earning_transaction_payload(item) for item in earning_transaction_items),
            ],
            key=lambda item: item["created_at"],
            reverse=True,
        )
    )
    combined.sort(key=lambda item: item["created_at"], reverse=True)
    total = len(combined)
    start = (page - 1) * page_size
    return {
        "items": combined[start : start + page_size],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


def list_admin_user_withdrawals(
    *,
    user: User,
    status: str = "",
    page: int = 1,
    page_size: int = 20,
) -> dict[str, Any]:
    """分页查看用户提现申请和脱敏收款方式。"""
    if status and status not in Withdrawal.Status.values:
        raise _invalid("status", "提现状态不存在")
    queryset = user.withdrawals.select_related("account", "payout_method").order_by(
        "-created_at", "-id"
    )
    if status:
        queryset = queryset.filter(status=status)
    total = queryset.count()
    items = queryset[(page - 1) * page_size : page * page_size]
    return {
        "items": [withdrawal_payload(item) for item in items],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


def _admin_review_payload(review: Review, request: HttpRequest | None = None) -> dict[str, Any]:
    """返回管理员评价摘要；管理员可查看匿名评价实际用户。"""
    payload = review_payload(review, request)
    payload["user_public_id"] = str(review.user.public_id)
    payload["user"] = {
        "public_id": str(review.user.public_id),
        "nickname": getattr(getattr(review.user, "profile", None), "nickname", None),
        "avatar_media": _user_avatar_payload(review.user, request),
        "is_anonymous_display": review.is_anonymous,
    }
    return payload


def list_admin_user_reviews(
    *,
    user: User,
    direction: str = "ALL",
    page: int = 1,
    page_size: int = 20,
    request: HttpRequest | None = None,
) -> dict[str, Any]:
    """分页查看用户发表或收到的服务评价。"""
    if direction not in {"ALL", "GIVEN", "RECEIVED"}:
        raise _invalid("direction", "评价方向不存在")
    queryset = Review.objects.select_related(
        "user", "user__profile", "provider_user", "provider_user__provider_profile"
    ).prefetch_related("tag_links__tag", "replies")
    if direction == "GIVEN":
        queryset = queryset.filter(user=user)
    elif direction == "RECEIVED":
        queryset = queryset.filter(provider_user=user)
    else:
        queryset = queryset.filter(Q(user=user) | Q(provider_user=user))
    total = queryset.count()
    items = queryset.order_by("-created_at", "-id")[(page - 1) * page_size : page * page_size]
    return {
        "items": [_admin_review_payload(item, request) for item in items],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


def list_admin_user_support_tickets(
    *,
    user: User,
    status: str = "",
    page: int = 1,
    page_size: int = 20,
) -> dict[str, Any]:
    """分页查看用户客服工单。"""
    if status and status not in SupportTicket.Status.values:
        raise _invalid("status", "客服工单状态不存在")
    queryset = user.support_tickets.order_by("-updated_at", "-id")
    if status:
        queryset = queryset.filter(status=status)
    total = queryset.count()
    items = queryset[(page - 1) * page_size : page * page_size]
    return {
        "items": [ticket_payload(item) for item in items],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


def list_admin_user_audit_logs(
    *,
    user: User,
    page: int = 1,
    page_size: int = 20,
) -> dict[str, Any]:
    """分页查看与用户相关的管理审计记录。"""
    from backend.adminops.models import AdminOperationLog

    queryset = AdminOperationLog.objects.select_related("operator").filter(
        target_id=str(user.public_id)
    )
    total = queryset.count()
    items = queryset.order_by("-created_at", "-id")[(page - 1) * page_size : page * page_size]
    return {
        "items": [
            {
                "operation_no": str(item.operation_no),
                "action": item.action,
                "action_text": audit_action_label(item.action),
                "target_type": item.target_type,
                "target_type_text": audit_target_type_label(item.target_type),
                "target_id": item.target_id,
                "operator_public_id": str(item.operator.public_id) if item.operator else None,
                "reason": item.reason,
                "trace_id": item.trace_id,
                "created_at": item.created_at,
            }
            for item in items
        ],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


def admin_provider_payload(user: User, profile: ProviderProfile | None) -> dict[str, Any]:
    """返回管理员服务者安全摘要。"""
    return {
        "user_public_id": str(user.public_id),
        "nickname": profile.nickname if profile else None,
        "phone_masked": user.phone_masked,
        "provider_status": user.provider_status,
        "provider_status_text": enum_label(User.ProviderStatus, user.provider_status),
        "provider_enabled": user.provider_enabled,
        "version": user.version,
    }


def list_admin_users(
    *,
    keyword: str = "",
    status: str = "",
    page: int = 1,
    page_size: int = 20,
    request: HttpRequest | None = None,
) -> dict[str, Any]:
    """分页筛选用户。"""
    customer_paid_subquery = (
        Order.objects.filter(user=OuterRef("pk"))
        .order_by()
        .values("user_id")
        .annotate(total=Sum("paid_amount_minor"))
        .values("total")[:1]
    )
    provider_paid_subquery = (
        Order.objects.filter(provider_user=OuterRef("pk"))
        .order_by()
        .values("provider_user_id")
        .annotate(total=Sum("paid_amount_minor"))
        .values("total")[:1]
    )
    queryset = User.objects.select_related("profile", "provider_profile").annotate(
        customer_order_total=Count("orders", distinct=True),
        customer_order_completed=Count(
            "orders", filter=Q(orders__status=Order.Status.COMPLETED), distinct=True
        ),
        customer_order_paid_amount_minor=Subquery(customer_paid_subquery),
        provider_order_total=Count(
            "provider_orders",
            filter=Q(provider_orders__isnull=False),
            distinct=True,
        ),
        provider_order_completed=Count(
            "provider_orders",
            filter=Q(provider_orders__status=Order.Status.COMPLETED),
            distinct=True,
        ),
        provider_order_paid_amount_minor=Subquery(provider_paid_subquery),
    )
    if keyword:
        queryset = queryset.filter(
            Q(phone_masked__icontains=keyword)
            | Q(profile__nickname__icontains=keyword)
            | Q(provider_profile__nickname__icontains=keyword)
        )
    if status:
        queryset = queryset.filter(status=status)
    total = queryset.count()
    items = queryset.order_by("-created_at", "-id")[(page - 1) * page_size : page * page_size]
    return {
        "items": [admin_user_payload(item, request) for item in items],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


def get_admin_user(*, user_public_id: str) -> User:
    """读取管理目标用户。"""
    user = User.objects.filter(public_id=user_public_id).first()
    if user is None:
        raise ApiError(
            ErrorCode.NOT_FOUND,
            ERROR_MESSAGES[ErrorCode.NOT_FOUND],
            status_code=404,
        )
    return user


def change_user_status(
    *,
    operator: User,
    user_public_id: str,
    action: str,
    expected_version: int,
    reason: str,
    idempotency_key: str = "",
) -> User:
    """封禁或解封用户并记录审计。"""
    if action not in {"ban", "unban"}:
        raise _invalid("action", "用户状态操作不存在")
    if len(reason.strip()) < 2:
        raise _invalid("reason", "操作原因至少需要 2 个字符")
    with transaction.atomic():
        user = User.objects.select_for_update().filter(public_id=user_public_id).first()
        if user is None:
            raise ApiError(
                ErrorCode.NOT_FOUND,
                ERROR_MESSAGES[ErrorCode.NOT_FOUND],
                status_code=404,
            )
        if user.version != expected_version:
            raise ApiError(
                ErrorCode.ADMIN_VERSION_CONFLICT,
                ERROR_MESSAGES[ErrorCode.ADMIN_VERSION_CONFLICT],
                status_code=409,
            )
        before = admin_user_payload(user)
        if action == "ban":
            if user.id == operator.id:
                raise _invalid("user_public_id", "不能封禁当前登录管理员")
            user.status = User.Status.FROZEN
            AuthToken.objects.filter(user=user, revoked_at__isnull=True).update(
                revoked_at=timezone.now()
            )
            AdminAuthToken.objects.filter(user=user, revoked_at__isnull=True).update(
                revoked_at=timezone.now()
            )
        else:
            user.status = User.Status.ACTIVE
        user.version = F("version") + 1
        user.save(update_fields=["status", "version", "updated_at"])
        user.refresh_from_db()
        write_admin_operation(
            operator=operator,
            action=f"USER_{action.upper()}",
            target_type="USER",
            target_id=str(user.public_id),
            before_state=before,
            after_state=admin_user_payload(user),
            reason=reason,
            idempotency_key=idempotency_key,
        )
        return user


def list_admin_providers(
    *,
    keyword: str = "",
    status: str = "",
    page: int = 1,
    page_size: int = 20,
) -> dict[str, Any]:
    """分页筛选服务者。"""
    queryset = User.objects.filter(
        provider_enabled=True,
        provider_status=User.ProviderStatus.APPROVED,
    ).select_related("provider_profile")
    if keyword:
        queryset = queryset.filter(provider_profile__nickname__icontains=keyword) | queryset.filter(
            phone_masked__icontains=keyword
        )
    if status:
        queryset = queryset.filter(provider_status=status)
    total = queryset.count()
    items = queryset.order_by("-created_at", "-id")[(page - 1) * page_size : page * page_size]
    return {
        "items": [
            admin_provider_payload(item, getattr(item, "provider_profile", None)) for item in items
        ],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


def list_admin_orders(
    *,
    keyword: str = "",
    status: str = "",
    page: int = 1,
    page_size: int = 20,
    request=None,
) -> dict[str, Any]:
    """分页筛选管理员订单。"""
    queryset = Order.objects.select_related("user", "provider_user", "service")
    if keyword:
        queryset = queryset.filter(order_no__icontains=keyword)
    if status:
        queryset = queryset.filter(status=status)
    total = queryset.count()
    items = queryset.order_by("-created_at", "-id")[(page - 1) * page_size : page * page_size]
    return {
        "items": [order_payload(item, request=request, viewer=request.user) for item in items],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


def get_admin_order(*, order_no: str, request=None) -> dict[str, Any]:
    """读取管理员订单详情。"""
    order = (
        Order.objects.select_related("user", "provider_user", "service")
        .filter(order_no=order_no)
        .first()
    )
    if order is None:
        raise ApiError(
            ErrorCode.NOT_FOUND,
            ERROR_MESSAGES[ErrorCode.NOT_FOUND],
            status_code=404,
        )
    return order_payload(order, request=request, viewer=request.user)


def export_admin_orders(*, keyword: str = "", status: str = "") -> str:
    """导出管理员订单 CSV，不导出手机号或联系信息。"""
    import csv
    import io

    queryset = Order.objects.select_related("user", "provider_user")
    if keyword:
        queryset = queryset.filter(order_no__icontains=keyword)
    if status:
        queryset = queryset.filter(status=status)
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(
        [
            "order_no",
            "status",
            "customer_public_id",
            "provider_public_id",
            "paid_amount_minor",
            "refunded_amount_minor",
            "platform_commission_amount_minor",
            "created_at",
        ]
    )
    for order in queryset.order_by("-created_at", "-id"):
        writer.writerow(
            [
                str(order.order_no),
                order.status,
                str(order.user.public_id),
                str(order.provider_user.public_id),
                order.paid_amount_minor,
                order.refunded_amount_minor,
                order.platform_commission_amount_minor,
                order.created_at.isoformat(),
            ]
        )
    return output.getvalue()


def admin_cancel_order(
    *,
    operator: User,
    order_no: str,
    expected_version: int,
    reason: str,
    idempotency_key: str = "",
) -> dict[str, Any]:
    """管理员取消订单并写统一审计。"""
    order = Order.objects.filter(order_no=order_no).first()
    if order is None:
        raise ApiError(
            ErrorCode.NOT_FOUND,
            ERROR_MESSAGES[ErrorCode.NOT_FOUND],
            status_code=404,
        )
    canceled = cancel_order(
        user=order.user,
        order_no=order_no,
        expected_version=expected_version,
        reason=reason,
        actor_user_id=operator.id,
    )
    write_admin_operation(
        operator=operator,
        action="ORDER_CANCEL",
        target_type="ORDER",
        target_id=order_no,
        after_state={"status": canceled.status, "version": canceled.version},
        reason=reason,
        idempotency_key=idempotency_key,
    )
    return order_payload(canceled, viewer=operator)


def list_admin_withdrawals(
    *,
    status: str = "",
    page: int = 1,
    page_size: int = 20,
) -> dict[str, Any]:
    """分页查看管理员提现单。"""
    return list_withdrawals(
        status=status or None,
        page=page,
        page_size=page_size,
    )


def review_admin_withdrawal(
    *,
    operator: User,
    request_no: str,
    action: str,
    expected_version: int,
    review_note: str = "",
    idempotency_key: str = "",
) -> dict[str, Any]:
    """执行提现审核并写统一管理审计。"""
    if action == "approve":
        result = approve_withdrawal(
            admin_user=operator,
            request_no=request_no,
            expected_version=expected_version,
            idempotency_key=idempotency_key or f"admin-withdrawal-{action}:{request_no}",
        )
    elif action == "reject":
        result = reject_withdrawal(
            admin_user=operator,
            request_no=request_no,
            expected_version=expected_version,
            review_note=review_note,
            idempotency_key=idempotency_key or f"admin-withdrawal-{action}:{request_no}",
        )
    elif action == "retry":
        result = retry_withdrawal(
            admin_user=operator,
            request_no=request_no,
            expected_version=expected_version,
            idempotency_key=idempotency_key or f"admin-withdrawal-{action}:{request_no}",
        )
    else:
        raise _invalid("action", "提现审核动作不存在")
    write_admin_operation(
        operator=operator,
        action=f"WITHDRAWAL_{action.upper()}",
        target_type="WITHDRAWAL",
        target_id=request_no,
        after_state={
            "status": result.get("status"),
            "version": result.get("version"),
        },
        reason=review_note,
        idempotency_key=idempotency_key,
    )
    return result


def get_admin_provider(*, user_public_id: str) -> User:
    """读取管理目标服务者。"""
    user = (
        User.objects.select_related("provider_profile")
        .filter(
            public_id=user_public_id,
            provider_status__in=[
                User.ProviderStatus.APPROVED,
                User.ProviderStatus.SUSPENDED,
            ],
        )
        .first()
    )
    if user is None:
        raise ApiError(
            ErrorCode.NOT_FOUND,
            ERROR_MESSAGES[ErrorCode.NOT_FOUND],
            status_code=404,
        )
    return user


def change_provider_status(
    *,
    operator: User,
    user_public_id: str,
    action: str,
    expected_version: int,
    reason: str,
    idempotency_key: str = "",
) -> User:
    """停用或恢复服务者权限。"""
    if action not in {"suspend", "restore"}:
        raise _invalid("action", "服务者状态操作不存在")
    if len(reason.strip()) < 2:
        raise _invalid("reason", "操作原因至少需要 2 个字符")
    with transaction.atomic():
        user = get_admin_provider(user_public_id=user_public_id)
        user = User.objects.select_for_update().get(pk=user.pk)
        if user.version != expected_version:
            raise ApiError(
                ErrorCode.ADMIN_VERSION_CONFLICT,
                ERROR_MESSAGES[ErrorCode.ADMIN_VERSION_CONFLICT],
                status_code=409,
            )
        before = admin_provider_payload(user, getattr(user, "provider_profile", None))
        if action == "suspend":
            user.provider_enabled = False
            user.provider_status = User.ProviderStatus.SUSPENDED
        else:
            user.provider_enabled = True
            user.provider_status = User.ProviderStatus.APPROVED
        user.version = F("version") + 1
        user.save(
            update_fields=[
                "provider_enabled",
                "provider_status",
                "version",
                "updated_at",
            ]
        )
        user.refresh_from_db()
        write_admin_operation(
            operator=operator,
            action=f"PROVIDER_{action.upper()}",
            target_type="PROVIDER",
            target_id=str(user.public_id),
            before_state=before,
            after_state=admin_provider_payload(
                user,
                getattr(user, "provider_profile", None),
            ),
            reason=reason,
            idempotency_key=idempotency_key,
        )
        return user


def list_admin_audit_logs(
    *,
    page: int = 1,
    page_size: int = 20,
) -> dict[str, Any]:
    """分页查看管理操作审计。"""
    from backend.adminops.models import AdminOperationLog

    queryset = AdminOperationLog.objects.select_related("operator").order_by(
        "-created_at",
        "-id",
    )
    total = queryset.count()
    items = queryset[(page - 1) * page_size : page * page_size]
    return {
        "items": [
            {
                "operation_no": str(item.operation_no),
                "action": item.action,
                "action_text": audit_action_label(item.action),
                "target_type": item.target_type,
                "target_type_text": audit_target_type_label(item.target_type),
                "target_id": item.target_id,
                "operator_public_id": (str(item.operator.public_id) if item.operator else None),
                "reason": item.reason,
                "trace_id": item.trace_id,
                "created_at": item.created_at,
            }
            for item in items
        ],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


def list_admin_permissions() -> list[dict[str, Any]]:
    """返回权限点配置。"""
    return [
        {
            "code": item.code,
            "name": item.name,
            "category": item.category,
        }
        for item in AdminPermission.objects.order_by("category", "code")
    ]


def list_admin_roles() -> list[dict[str, Any]]:
    """返回角色、权限点和成员数量。"""
    roles = AdminRole.objects.prefetch_related(
        "permission_links__permission",
        "members",
    ).order_by("code")
    return [
        {
            "role_no": str(role.role_no),
            "code": role.code,
            "name": role.name,
            "description": role.description,
            "status": role.status,
            "status_text": enum_label(AdminRole.Status, role.status),
            "permission_codes": [link.permission.code for link in role.permission_links.all()],
            "member_count": role.members.count(),
            "version": role.version,
        }
        for role in roles
    ]


def _role_payload(role: AdminRole) -> dict[str, Any]:
    return {
        "role_no": str(role.role_no),
        "code": role.code,
        "name": role.name,
        "description": role.description,
        "status": role.status,
        "status_text": enum_label(AdminRole.Status, role.status),
        "permission_codes": [link.permission.code for link in role.permission_links.all()],
        "member_count": role.members.count(),
        "version": role.version,
    }


def create_admin_role(
    *,
    operator: User,
    payload: dict[str, Any],
) -> dict[str, Any]:
    """创建管理员角色和初始权限点。"""
    code = str(payload.get("code", "")).strip()
    name = str(payload.get("name", "")).strip()
    if not code or not name:
        raise _invalid("code", "角色代码和名称不能为空")
    permission_codes = sorted(set(payload.get("permission_codes") or []))
    permissions = AdminPermission.objects.filter(code__in=permission_codes)
    if len(permissions) != len(permission_codes):
        raise _invalid("permission_codes", "包含不存在的权限点")
    with transaction.atomic():
        try:
            role = AdminRole.objects.create(
                code=code,
                name=name,
                description=str(payload.get("description", "")).strip(),
            )
        except IntegrityError as exc:
            raise ApiError(
                ErrorCode.ADMIN_VERSION_CONFLICT,
                "角色代码已存在",
                status_code=409,
            ) from exc
        for permission in permissions:
            AdminRolePermission.objects.create(role=role, permission=permission)
        result = _role_payload(role)
        write_admin_operation(
            operator=operator,
            action="ADMIN_ROLE_CREATE",
            target_type="ADMIN_ROLE",
            target_id=str(role.role_no),
            after_state=result,
        )
        return result


def update_admin_role(
    *,
    operator: User,
    role_no: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    """修改角色状态、说明和权限点。"""
    with transaction.atomic():
        role = AdminRole.objects.select_for_update().filter(role_no=role_no).first()
        if role is None:
            raise ApiError(
                ErrorCode.NOT_FOUND,
                ERROR_MESSAGES[ErrorCode.NOT_FOUND],
                status_code=404,
            )
        if role.code == "SUPER_ADMIN":
            raise _invalid("role_no", "超级管理员角色不允许修改")
        if role.version != payload["expected_version"]:
            raise ApiError(
                ErrorCode.ADMIN_VERSION_CONFLICT,
                ERROR_MESSAGES[ErrorCode.ADMIN_VERSION_CONFLICT],
                status_code=409,
            )
        before = _role_payload(role)
        if "name" in payload:
            role.name = str(payload["name"]).strip()
        if "description" in payload:
            role.description = str(payload["description"]).strip()
        if "status" in payload:
            role.status = payload["status"]
        if "permission_codes" in payload:
            permission_codes = sorted(set(payload["permission_codes"]))
            permissions = AdminPermission.objects.filter(code__in=permission_codes)
            if len(permissions) != len(permission_codes):
                raise _invalid("permission_codes", "包含不存在的权限点")
            role.permission_links.all().delete()
            AdminRolePermission.objects.bulk_create(
                [
                    AdminRolePermission(role=role, permission=permission)
                    for permission in permissions
                ]
            )
        role.version = F("version") + 1
        role.save()
        role.refresh_from_db()
        result = _role_payload(role)
        write_admin_operation(
            operator=operator,
            action="ADMIN_ROLE_UPDATE",
            target_type="ADMIN_ROLE",
            target_id=str(role.role_no),
            before_state=before,
            after_state=result,
        )
        return result


def delete_admin_role(*, operator: User, role_no: str) -> dict[str, bool]:
    """删除无成员且不是超级管理员的角色。"""
    with transaction.atomic():
        role = AdminRole.objects.select_for_update().filter(role_no=role_no).first()
        if role is None:
            raise ApiError(
                ErrorCode.NOT_FOUND,
                ERROR_MESSAGES[ErrorCode.NOT_FOUND],
                status_code=404,
            )
        if role.code == "SUPER_ADMIN" or role.members.exists():
            raise _invalid("role_no", "超级管理员或仍有成员的角色不能删除")
        before = _role_payload(role)
        role.delete()
        write_admin_operation(
            operator=operator,
            action="ADMIN_ROLE_DELETE",
            target_type="ADMIN_ROLE",
            target_id=role_no,
            before_state=before,
        )
        return {"deleted": True}


def add_admin_role_member(
    *,
    operator: User,
    role_no: str,
    user_public_id: str,
) -> dict[str, Any]:
    """为管理员分配角色。"""
    role = AdminRole.objects.filter(role_no=role_no, status=AdminRole.Status.ACTIVE).first()
    user = User.objects.filter(public_id=user_public_id, is_staff=True).first()
    if role is None or user is None:
        raise ApiError(
            ErrorCode.NOT_FOUND,
            ERROR_MESSAGES[ErrorCode.NOT_FOUND],
            status_code=404,
        )
    AdminRoleMember.objects.get_or_create(
        role=role,
        user=user,
        defaults={"assigned_by": operator.id},
    )
    write_admin_operation(
        operator=operator,
        action="ADMIN_ROLE_MEMBER_ADD",
        target_type="ADMIN_ROLE_MEMBER",
        target_id=f"{role.code}:{user.public_id}",
        after_state={"role": role.code, "user": str(user.public_id)},
    )
    return {"role_no": str(role.role_no), "user_public_id": str(user.public_id)}


def remove_admin_role_member(
    *,
    operator: User,
    role_no: str,
    user_public_id: str,
) -> dict[str, Any]:
    """移除管理员角色成员。"""
    role = AdminRole.objects.filter(role_no=role_no).first()
    user = User.objects.filter(public_id=user_public_id).first()
    if role is None or user is None:
        raise ApiError(
            ErrorCode.NOT_FOUND,
            ERROR_MESSAGES[ErrorCode.NOT_FOUND],
            status_code=404,
        )
    deleted, _ = AdminRoleMember.objects.filter(role=role, user=user).delete()
    if not deleted:
        raise ApiError(
            ErrorCode.NOT_FOUND,
            ERROR_MESSAGES[ErrorCode.NOT_FOUND],
            status_code=404,
        )
    write_admin_operation(
        operator=operator,
        action="ADMIN_ROLE_MEMBER_REMOVE",
        target_type="ADMIN_ROLE_MEMBER",
        target_id=f"{role.code}:{user.public_id}",
        before_state={"role": role.code, "user": str(user.public_id)},
    )
    return {"removed": True}
