"""收款方式绑定、收益结算和提现审核业务服务。"""

from __future__ import annotations

import json
import re
import uuid
from datetime import timedelta
from typing import Any

from django.conf import settings
from django.db import IntegrityError, transaction
from django.db.models import F, Sum
from django.utils import timezone

from backend.accounts.models import User
from backend.common.context import current_trace_id
from backend.common.crypto import (
    decrypt_text,
    encrypt_text,
    hash_sensitive_text,
    sensitive_fingerprint,
)
from backend.common.errors import ERROR_MESSAGES, ErrorCode
from backend.common.exceptions import ApiError
from backend.payouts.adapters import get_payout_channel, get_payout_verifier
from backend.payouts.models import (
    EarningAccount,
    EarningEntry,
    EarningTransaction,
    PayoutMethod,
    PayoutMethodEvent,
    Withdrawal,
    WithdrawalStatusLog,
)


def _invalid(code: ErrorCode, field: str, message: str) -> ApiError:
    return ApiError(
        code,
        ERROR_MESSAGES[code],
        status_code=400,
        details={field: message},
    )


def _normalize_idempotency_key(
    value: str | None,
    prefix: str,
    *,
    error_code: ErrorCode = ErrorCode.WITHDRAWAL_IDEMPOTENCY_CONFLICT,
) -> str:
    if value is None:
        return f"auto:{prefix}:{uuid.uuid4()}"
    key = value.strip()
    if not key or len(key) > 128:
        raise _invalid(
            error_code,
            "idempotency_key",
            "幂等键长度必须在 1 到 128 之间",
        )
    return key


def _mask_name(value: str) -> str:
    """返回账户姓名脱敏值，不保留完整姓名。"""

    if len(value) == 1:
        return "*"
    if len(value) == 2:
        return f"{value[0]}*"
    return f"{value[0]}{'*' * (len(value) - 2)}{value[-1]}"


def _mask_account(method_type: str, value: str) -> str:
    """返回银行卡、支付宝或微信账号安全脱敏值。"""

    if method_type == PayoutMethod.MethodType.BANK_CARD:
        return f"**** **** **** {value[-4:]}" if len(value) >= 4 else "****"
    if len(value) <= 4:
        return "*" * len(value)
    return f"{value[:2]}{'*' * min(8, len(value) - 4)}{value[-2:]}"


def _validate_payout_payload(payload: dict[str, Any]) -> dict[str, Any]:
    method_type = payload.get("method_type")
    if method_type not in PayoutMethod.MethodType.values:
        raise _invalid(
            ErrorCode.PAYOUT_METHOD_INVALID,
            "method_type",
            "收款方式只支持银行卡、支付宝或微信支付",
        )
    account_name = str(payload.get("account_name", "")).strip()
    if not 2 <= len(account_name) <= 50:
        raise _invalid(
            ErrorCode.PAYOUT_METHOD_INVALID,
            "account_name",
            "账户姓名必须为 2 到 50 个字符",
        )
    account_number = re.sub(r"\s+", "", str(payload.get("account_number", "")).strip())
    if not 4 <= len(account_number) <= 128:
        raise _invalid(
            ErrorCode.PAYOUT_METHOD_INVALID,
            "account_number",
            "收款账号长度必须为 4 到 128 个字符",
        )
    if method_type == PayoutMethod.MethodType.BANK_CARD:
        if not account_number.isdigit() or not 8 <= len(account_number) <= 32:
            raise _invalid(
                ErrorCode.PAYOUT_METHOD_INVALID,
                "account_number",
                "银行卡号必须为 8 到 32 位数字",
            )
        institution_name = str(payload.get("institution_name", "")).strip()
        if not 2 <= len(institution_name) <= 100:
            raise _invalid(
                ErrorCode.PAYOUT_METHOD_INVALID,
                "institution_name",
                "银行名称必须为 2 到 100 个字符",
            )
    else:
        institution_name = "支付宝" if method_type == PayoutMethod.MethodType.ALIPAY else "微信支付"
    return {
        "method_type": method_type,
        "account_name": account_name,
        "account_number": account_number,
        "institution_name": institution_name,
        "is_default": bool(payload.get("is_default", True)),
    }


def payout_method_payload(method: PayoutMethod) -> dict[str, Any]:
    """返回收款方式脱敏摘要，不返回账户明文。"""

    return {
        "id": str(method.public_id),
        "method_type": method.method_type,
        "binding_mode": method.binding_mode,
        "status": method.status,
        "verification_status": method.verification_status,
        "is_default": method.is_default,
        "account_name_masked": method.account_name_masked,
        "account_number_masked": method.account_number_masked,
        "institution_name": method.institution_name,
        "display_text": method.display_text,
        "version": method.version,
        "created_at": method.created_at,
        "updated_at": method.updated_at,
        "deactivated_at": method.deactivated_at,
    }


def list_payout_methods(*, user: User) -> dict[str, Any]:
    """返回当前用户可用和已停用的收款方式。"""

    methods = list(
        PayoutMethod.objects.filter(user=user).order_by(
            "-is_default",
            "-created_at",
            "-id",
        )
    )
    return {
        "items": [payout_method_payload(item) for item in methods],
        "has_default": any(
            item.status == PayoutMethod.Status.ACTIVE and item.is_default for item in methods
        ),
    }


def create_payout_method(
    *,
    user: User,
    payload: dict[str, Any],
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    """创建普通用户和服务者共用的收款方式并执行模拟验证。"""

    normalized = _validate_payout_payload(payload)
    normalized_key = _normalize_idempotency_key(
        idempotency_key,
        "payout-method",
        error_code=ErrorCode.PAYOUT_METHOD_IDEMPOTENCY_CONFLICT,
    )
    fingerprint = sensitive_fingerprint(
        {
            "user_id": user.id,
            **normalized,
        }
    )
    account_fingerprint = hash_sensitive_text(
        f"{normalized['method_type']}:{normalized['account_number']}"
    )
    verifier = get_payout_verifier()
    verification_reference = verifier.verify(
        method_type=normalized["method_type"],
        account_number=normalized["account_number"],
    )
    try:
        with transaction.atomic():
            existing = PayoutMethod.objects.filter(
                user=user,
                idempotency_key=normalized_key,
            ).first()
            if existing:
                if existing.request_fingerprint != fingerprint:
                    raise ApiError(
                        ErrorCode.PAYOUT_METHOD_IDEMPOTENCY_CONFLICT,
                        ERROR_MESSAGES[ErrorCode.PAYOUT_METHOD_IDEMPOTENCY_CONFLICT],
                        status_code=409,
                    )
                return {**payout_method_payload(existing), "reused": True}
            active_exists = PayoutMethod.objects.filter(
                user=user,
                status=PayoutMethod.Status.ACTIVE,
            ).exists()
            is_default = normalized["is_default"] or not active_exists
            if is_default:
                PayoutMethod.objects.filter(
                    user=user,
                    status=PayoutMethod.Status.ACTIVE,
                    is_default=True,
                ).update(is_default=False, version=F("version") + 1)
            method = PayoutMethod.objects.create(
                user=user,
                method_type=normalized["method_type"],
                account_name_encrypted=encrypt_text(normalized["account_name"]),
                account_name_masked=_mask_name(normalized["account_name"]),
                account_number_encrypted=encrypt_text(normalized["account_number"]),
                account_number_masked=_mask_account(
                    normalized["method_type"],
                    normalized["account_number"],
                ),
                institution_name=normalized["institution_name"],
                account_fingerprint=account_fingerprint,
                display_text=(
                    f"{normalized['institution_name']}"
                    f"（{_mask_account(normalized['method_type'], normalized['account_number'])}）"
                ),
                is_default=is_default,
                idempotency_key=normalized_key,
                request_fingerprint=fingerprint,
            )
            PayoutMethodEvent.objects.create(
                payout_method=method,
                event_type=PayoutMethodEvent.EventType.CREATED,
                actor_user_id=user.id,
                reason=f"模拟验证引用：{verification_reference}",
                trace_id=current_trace_id(),
            )
            return {**payout_method_payload(method), "reused": False}
    except IntegrityError as exc:
        existing = PayoutMethod.objects.filter(
            user=user,
            idempotency_key=normalized_key,
        ).first()
        if existing and existing.request_fingerprint == fingerprint:
            return {**payout_method_payload(existing), "reused": True}
        raise ApiError(
            ErrorCode.PAYOUT_METHOD_INVALID,
            ERROR_MESSAGES[ErrorCode.PAYOUT_METHOD_INVALID],
            status_code=409,
            details={"account_number": "该收款账号已绑定"},
        ) from exc


def set_default_payout_method(
    *,
    user: User,
    payout_method_id: str,
    expected_version: int,
) -> dict[str, Any]:
    """将本人启用中的收款方式设为默认。"""

    with transaction.atomic():
        method = (
            PayoutMethod.objects.select_for_update()
            .filter(public_id=payout_method_id, user=user)
            .first()
        )
        if method is None:
            raise ApiError(
                ErrorCode.PAYOUT_METHOD_NOT_FOUND,
                ERROR_MESSAGES[ErrorCode.PAYOUT_METHOD_NOT_FOUND],
                status_code=404,
            )
        if method.status != PayoutMethod.Status.ACTIVE:
            raise ApiError(
                ErrorCode.PAYOUT_METHOD_STATE_INVALID,
                ERROR_MESSAGES[ErrorCode.PAYOUT_METHOD_STATE_INVALID],
                status_code=409,
            )
        if method.version != expected_version:
            raise ApiError(
                ErrorCode.PAYOUT_METHOD_VERSION_CONFLICT,
                ERROR_MESSAGES[ErrorCode.PAYOUT_METHOD_VERSION_CONFLICT],
                status_code=409,
            )
        PayoutMethod.objects.filter(
            user=user,
            status=PayoutMethod.Status.ACTIVE,
            is_default=True,
        ).update(is_default=False)
        method.is_default = True
        method.version += 1
        method.save(update_fields=["is_default", "version", "updated_at"])
        PayoutMethodEvent.objects.create(
            payout_method=method,
            event_type=PayoutMethodEvent.EventType.SET_DEFAULT,
            actor_user_id=user.id,
            trace_id=current_trace_id(),
        )
        return payout_method_payload(method)


def deactivate_payout_method(
    *,
    user: User,
    payout_method_id: str,
    expected_version: int,
) -> dict[str, Any]:
    """停用本人收款方式并保留历史提现快照。"""

    with transaction.atomic():
        method = (
            PayoutMethod.objects.select_for_update()
            .filter(public_id=payout_method_id, user=user)
            .first()
        )
        if method is None:
            raise ApiError(
                ErrorCode.PAYOUT_METHOD_NOT_FOUND,
                ERROR_MESSAGES[ErrorCode.PAYOUT_METHOD_NOT_FOUND],
                status_code=404,
            )
        if method.status == PayoutMethod.Status.INACTIVE:
            return payout_method_payload(method)
        if method.version != expected_version:
            raise ApiError(
                ErrorCode.PAYOUT_METHOD_VERSION_CONFLICT,
                ERROR_MESSAGES[ErrorCode.PAYOUT_METHOD_VERSION_CONFLICT],
                status_code=409,
            )
        method.status = PayoutMethod.Status.INACTIVE
        method.is_default = False
        method.deactivated_at = timezone.now()
        method.version += 1
        method.save(
            update_fields=[
                "status",
                "is_default",
                "deactivated_at",
                "version",
                "updated_at",
            ],
        )
        fallback = (
            PayoutMethod.objects.filter(
                user=user,
                status=PayoutMethod.Status.ACTIVE,
            )
            .order_by("-created_at", "-id")
            .first()
        )
        if fallback:
            fallback.is_default = True
            fallback.version += 1
            fallback.save(update_fields=["is_default", "version", "updated_at"])
        PayoutMethodEvent.objects.create(
            payout_method=method,
            event_type=PayoutMethodEvent.EventType.DEACTIVATED,
            actor_user_id=user.id,
            trace_id=current_trace_id(),
        )
        return payout_method_payload(method)


def get_or_create_earning_account(
    *,
    user: User,
    account_type: str,
    currency: str = "CNY",
) -> EarningAccount:
    """返回指定类型的收益账户，必要时创建零余额账户。"""

    if account_type not in EarningAccount.AccountType.values:
        raise _invalid(
            ErrorCode.WITHDRAWAL_INVALID,
            "account_type",
            "账户类型只支持 PROVIDER_INCOME 或 REFERRAL_REWARD",
        )
    if currency != "CNY":
        raise _invalid(ErrorCode.WITHDRAWAL_INVALID, "currency", "当前仅支持 CNY")
    account, _ = EarningAccount.objects.get_or_create(
        user=user,
        account_type=account_type,
        currency=currency,
    )
    return account


def _earning_account_payload(account: EarningAccount) -> dict[str, Any]:
    return {
        "account_type": account.account_type,
        "currency": account.currency,
        "available_amount_minor": account.available_amount_minor,
        "frozen_amount_minor": account.frozen_amount_minor,
        "total_income_amount_minor": account.total_income_amount_minor,
        "total_withdrawn_amount_minor": account.total_withdrawn_amount_minor,
        "pending_settlement_amount_minor": EarningEntry.objects.filter(
            account=account,
            status=EarningEntry.Status.PENDING_SETTLEMENT,
        ).aggregate(total=Sum("net_amount_minor"))["total"]
        or 0,
        "version": account.version,
        "updated_at": account.updated_at,
    }


def create_provider_order_earning(order: Any) -> EarningEntry | None:
    """订单确认完成后幂等生成服务者收入记录并按配置结算。"""

    gross_amount_minor = max(0, order.paid_amount_minor - order.refunded_amount_minor)
    platform_fee_amount_minor = min(order.platform_fee_amount_minor, gross_amount_minor)
    net_amount_minor = gross_amount_minor - platform_fee_amount_minor
    if net_amount_minor <= 0:
        return None
    fingerprint = sensitive_fingerprint(
        {
            "order_no": str(order.order_no),
            "gross_amount_minor": gross_amount_minor,
            "platform_fee_amount_minor": platform_fee_amount_minor,
            "net_amount_minor": net_amount_minor,
        }
    )
    available_at = order.completed_at + timedelta(
        days=settings.PROVIDER_INCOME_SETTLEMENT_DELAY_DAYS
    )
    account = get_or_create_earning_account(
        user=order.provider_user,
        account_type=EarningAccount.AccountType.PROVIDER_INCOME,
        currency=order.currency,
    )
    try:
        with transaction.atomic():
            entry, _created = EarningEntry.objects.get_or_create(
                account=account,
                business_type="PROVIDER_ORDER_INCOME",
                business_no=str(order.order_no),
                defaults={
                    "user": order.provider_user,
                    "currency": order.currency,
                    "gross_amount_minor": gross_amount_minor,
                    "platform_fee_amount_minor": platform_fee_amount_minor,
                    "net_amount_minor": net_amount_minor,
                    "available_at": available_at,
                    "rule_snapshot": {
                        "rule_version": "order-platform-fee-v1",
                        "platform_commission_rate_bps": settings.PROVIDER_PLATFORM_COMMISSION_RATE_BPS,
                        "order_paid_amount_minor": order.paid_amount_minor,
                        "order_refunded_amount_minor": order.refunded_amount_minor,
                        "order_platform_fee_amount_minor": order.platform_fee_amount_minor,
                        "settlement_delay_days": settings.PROVIDER_INCOME_SETTLEMENT_DELAY_DAYS,
                    },
                    "idempotency_key": f"order-income:{order.order_no}",
                    "request_fingerprint": fingerprint,
                },
            )
            settle_due_earnings(account=account)
            return entry
    except IntegrityError:
        return EarningEntry.objects.filter(
            account=account,
            business_type="PROVIDER_ORDER_INCOME",
            business_no=str(order.order_no),
        ).first()


def settle_due_earnings(*, account: EarningAccount) -> int:
    """结算到期收益并写入不可变入账流水。"""

    settled_count = 0
    now = timezone.now()
    entries = list(
        EarningEntry.objects.select_for_update()
        .filter(
            account=account,
            status=EarningEntry.Status.PENDING_SETTLEMENT,
            available_at__lte=now,
        )
        .order_by("available_at", "id")
    )
    for entry in entries:
        transaction_record, created = _create_earning_transaction(
            account=account,
            direction=EarningTransaction.Direction.CREDIT,
            transaction_type=EarningTransaction.TransactionType.INCOME,
            business_type=entry.business_type,
            business_no=entry.business_no,
            amount_minor=entry.net_amount_minor,
            idempotency_key=f"income-settlement:{entry.earning_no}",
            request_fingerprint=entry.request_fingerprint,
            update_totals=True,
        )
        if created:
            entry.status = EarningEntry.Status.AVAILABLE
            entry.settled_at = transaction_record.created_at
            entry.save(update_fields=["status", "settled_at", "updated_at"])
            settled_count += 1
    return settled_count


def _create_earning_transaction(
    *,
    account: EarningAccount,
    direction: str,
    transaction_type: str,
    business_type: str,
    business_no: str,
    amount_minor: int,
    idempotency_key: str,
    request_fingerprint: str,
    update_totals: bool = False,
) -> tuple[EarningTransaction, bool]:
    existing = EarningTransaction.objects.filter(
        account=account,
        business_type=business_type,
        business_no=business_no,
        idempotency_key=idempotency_key,
    ).first()
    if existing:
        if existing.request_fingerprint != request_fingerprint:
            raise ApiError(
                ErrorCode.EARNING_TRANSACTION_CONFLICT,
                ERROR_MESSAGES[ErrorCode.EARNING_TRANSACTION_CONFLICT],
                status_code=409,
            )
        account.refresh_from_db()
        return existing, False
    if direction == EarningTransaction.Direction.CREDIT:
        available_after = account.available_amount_minor + amount_minor
        frozen_after = account.frozen_amount_minor
        total_income_after = account.total_income_amount_minor + (
            amount_minor if update_totals else 0
        )
        total_withdrawn_after = account.total_withdrawn_amount_minor
    elif direction == EarningTransaction.Direction.DEBIT:
        available_after = account.available_amount_minor
        frozen_after = account.frozen_amount_minor - amount_minor
        total_income_after = account.total_income_amount_minor
        total_withdrawn_after = account.total_withdrawn_amount_minor + (
            amount_minor if update_totals else 0
        )
    elif direction == EarningTransaction.Direction.HOLD:
        available_after = account.available_amount_minor - amount_minor
        frozen_after = account.frozen_amount_minor + amount_minor
        total_income_after = account.total_income_amount_minor
        total_withdrawn_after = account.total_withdrawn_amount_minor
    else:
        available_after = account.available_amount_minor + amount_minor
        frozen_after = account.frozen_amount_minor - amount_minor
        total_income_after = account.total_income_amount_minor
        total_withdrawn_after = account.total_withdrawn_amount_minor
    record = EarningTransaction.objects.create(
        account=account,
        user=account.user,
        direction=direction,
        transaction_type=transaction_type,
        business_type=business_type,
        business_no=business_no,
        currency=account.currency,
        amount_minor=amount_minor,
        available_after_amount_minor=available_after,
        frozen_after_amount_minor=frozen_after,
        total_income_after_amount_minor=total_income_after,
        total_withdrawn_after_amount_minor=total_withdrawn_after,
        idempotency_key=idempotency_key,
        request_fingerprint=request_fingerprint,
        trace_id=current_trace_id(),
    )
    account.available_amount_minor = available_after
    account.frozen_amount_minor = frozen_after
    account.total_income_amount_minor = total_income_after
    account.total_withdrawn_amount_minor = total_withdrawn_after
    account.version += 1
    account.save(
        update_fields=[
            "available_amount_minor",
            "frozen_amount_minor",
            "total_income_amount_minor",
            "total_withdrawn_amount_minor",
            "version",
            "updated_at",
        ],
    )
    return record, True


def earning_account_payload(
    *,
    user: User,
    account_type: str,
) -> dict[str, Any]:
    """查询并返回当前用户指定收益账户汇总。"""

    account = get_or_create_earning_account(user=user, account_type=account_type)
    with transaction.atomic():
        account = EarningAccount.objects.select_for_update().get(pk=account.pk)
        settle_due_earnings(account=account)
    return _earning_account_payload(account)


def list_earning_entries(
    *,
    user: User,
    account_type: str,
    page: int,
    page_size: int,
) -> dict[str, Any]:
    """分页返回当前用户收益业务明细。"""

    account = get_or_create_earning_account(user=user, account_type=account_type)
    queryset = EarningEntry.objects.filter(user=user, account=account).order_by(
        "-created_at",
        "-id",
    )
    start = max(0, (page - 1) * page_size)
    items = []
    for entry in queryset[start : start + page_size]:
        items.append(
            {
                "earning_no": str(entry.earning_no),
                "business_type": entry.business_type,
                "business_no": entry.business_no,
                "currency": entry.currency,
                "gross_amount_minor": entry.gross_amount_minor,
                "platform_fee_amount_minor": entry.platform_fee_amount_minor,
                "net_amount_minor": entry.net_amount_minor,
                "status": entry.status,
                "available_at": entry.available_at,
                "settled_at": entry.settled_at,
                "created_at": entry.created_at,
            }
        )
    return {
        "items": items,
        "total": queryset.count(),
        "page": page,
        "page_size": page_size,
    }


def list_earning_transactions(
    *,
    user: User,
    account_type: str,
    page: int,
    page_size: int,
) -> dict[str, Any]:
    """分页返回当前用户收益账户不可变流水。"""

    account = get_or_create_earning_account(user=user, account_type=account_type)
    queryset = EarningTransaction.objects.filter(user=user, account=account).order_by(
        "-created_at",
        "-id",
    )
    start = max(0, (page - 1) * page_size)
    items = []
    for item in queryset[start : start + page_size]:
        items.append(
            {
                "transaction_no": str(item.transaction_no),
                "direction": item.direction,
                "transaction_type": item.transaction_type,
                "business_type": item.business_type,
                "business_no": item.business_no,
                "currency": item.currency,
                "amount_minor": item.amount_minor,
                "available_after_amount_minor": item.available_after_amount_minor,
                "frozen_after_amount_minor": item.frozen_after_amount_minor,
                "created_at": item.created_at,
            }
        )
    return {
        "items": items,
        "total": queryset.count(),
        "page": page,
        "page_size": page_size,
    }


def withdrawal_payload(withdrawal: Withdrawal) -> dict[str, Any]:
    """返回提现单安全摘要和脱敏收款信息。"""

    return {
        "withdrawal_no": str(withdrawal.withdrawal_no),
        "account_type": withdrawal.account.account_type,
        "currency": withdrawal.currency,
        "amount_minor": withdrawal.amount_minor,
        "fee_amount_minor": withdrawal.fee_amount_minor,
        "payout_amount_minor": withdrawal.payout_amount_minor,
        "status": withdrawal.status,
        "payout_method": {
            "id": str(withdrawal.payout_method.public_id),
            "method_type": withdrawal.payout_method.method_type,
            "display_text": withdrawal.payout_method_display,
        },
        "review_note": withdrawal.review_note,
        "failure_reason": withdrawal.failure_reason,
        "channel_reference": withdrawal.channel_reference,
        "version": withdrawal.version,
        "created_at": withdrawal.created_at,
        "updated_at": withdrawal.updated_at,
        "reviewed_at": withdrawal.reviewed_at,
        "completed_at": withdrawal.completed_at,
    }


def _withdrawal_replay(
    *,
    withdrawal: Withdrawal,
    action: str,
    idempotency_key: str,
    request_fingerprint: str,
) -> Withdrawal | None:
    log = WithdrawalStatusLog.objects.filter(
        withdrawal=withdrawal,
        action=action,
        idempotency_key=idempotency_key,
    ).first()
    if log is None:
        return None
    if log.request_fingerprint != request_fingerprint:
        raise ApiError(
            ErrorCode.WITHDRAWAL_IDEMPOTENCY_CONFLICT,
            ERROR_MESSAGES[ErrorCode.WITHDRAWAL_IDEMPOTENCY_CONFLICT],
            status_code=409,
        )
    return withdrawal


def create_withdrawal(
    *,
    user: User,
    account_type: str,
    amount_minor: int,
    payout_method_id: str,
    expected_version: int,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    """冻结收益余额并创建待人工审核提现单。"""

    if not isinstance(amount_minor, int) or amount_minor <= 0:
        raise _invalid(ErrorCode.WITHDRAWAL_INVALID, "amount_minor", "金额必须大于 0")
    if amount_minor < settings.WITHDRAWAL_MIN_AMOUNT_MINOR:
        raise _invalid(
            ErrorCode.WITHDRAWAL_INVALID,
            "amount_minor",
            f"提现金额不能低于 {settings.WITHDRAWAL_MIN_AMOUNT_MINOR} 分",
        )
    fee_amount_minor = settings.WITHDRAWAL_FEE_AMOUNT_MINOR
    payout_amount_minor = amount_minor - fee_amount_minor
    if payout_amount_minor <= 0:
        raise _invalid(
            ErrorCode.WITHDRAWAL_INVALID,
            "amount_minor",
            "扣除手续费后实际打款金额必须大于 0",
        )
    normalized_key = _normalize_idempotency_key(idempotency_key, "withdrawal")
    account = get_or_create_earning_account(user=user, account_type=account_type)
    payout_method = PayoutMethod.objects.filter(
        public_id=payout_method_id,
        user=user,
        status=PayoutMethod.Status.ACTIVE,
    ).first()
    if payout_method is None:
        raise ApiError(
            ErrorCode.PAYOUT_METHOD_NOT_FOUND,
            ERROR_MESSAGES[ErrorCode.PAYOUT_METHOD_NOT_FOUND],
            status_code=404,
        )
    fingerprint = sensitive_fingerprint(
        {
            "user_id": user.id,
            "account_type": account_type,
            "amount_minor": amount_minor,
            "payout_method_id": payout_method_id,
        }
    )
    try:
        with transaction.atomic():
            existing = Withdrawal.objects.filter(
                user=user,
                idempotency_key=normalized_key,
            ).first()
            if existing:
                if existing.request_fingerprint != fingerprint:
                    raise ApiError(
                        ErrorCode.WITHDRAWAL_IDEMPOTENCY_CONFLICT,
                        ERROR_MESSAGES[ErrorCode.WITHDRAWAL_IDEMPOTENCY_CONFLICT],
                        status_code=409,
                    )
                return {**withdrawal_payload(existing), "reused": True}
            locked_account = EarningAccount.objects.select_for_update().get(pk=account.pk)
            if locked_account.version != expected_version:
                raise ApiError(
                    ErrorCode.WITHDRAWAL_VERSION_CONFLICT,
                    ERROR_MESSAGES[ErrorCode.WITHDRAWAL_VERSION_CONFLICT],
                    status_code=409,
                )
            if locked_account.available_amount_minor < amount_minor:
                raise _invalid(
                    ErrorCode.WITHDRAWAL_INVALID,
                    "amount_minor",
                    "可提现余额不足",
                )
            _create_earning_transaction(
                account=locked_account,
                direction=EarningTransaction.Direction.HOLD,
                transaction_type=EarningTransaction.TransactionType.WITHDRAWAL_HOLD,
                business_type="WITHDRAWAL",
                business_no=f"WITHDRAWAL-HOLD-{normalized_key}",
                amount_minor=amount_minor,
                idempotency_key=f"withdrawal-hold:{normalized_key}",
                request_fingerprint=fingerprint,
            )
            withdrawal = Withdrawal.objects.create(
                user=user,
                account=locked_account,
                payout_method=payout_method,
                payout_method_snapshot_encrypted=encrypt_text(
                    json.dumps(
                        {
                            "method_type": payout_method.method_type,
                            "account_name": decrypt_text(payout_method.account_name_encrypted),
                            "account_number": decrypt_text(payout_method.account_number_encrypted),
                            "institution_name": payout_method.institution_name,
                        },
                        ensure_ascii=False,
                        separators=(",", ":"),
                    )
                ),
                payout_method_display=payout_method.display_text,
                currency=locked_account.currency,
                amount_minor=amount_minor,
                fee_amount_minor=fee_amount_minor,
                payout_amount_minor=payout_amount_minor,
                idempotency_key=normalized_key,
                request_fingerprint=fingerprint,
            )
            WithdrawalStatusLog.objects.create(
                withdrawal=withdrawal,
                action=WithdrawalStatusLog.Action.CREATED,
                from_status="",
                to_status=withdrawal.status,
                actor_user_id=user.id,
                idempotency_key=f"create:{normalized_key}",
                request_fingerprint=fingerprint,
                trace_id=current_trace_id(),
            )
            return {**withdrawal_payload(withdrawal), "reused": False}
    except IntegrityError as exc:
        existing = Withdrawal.objects.filter(
            user=user,
            idempotency_key=normalized_key,
        ).first()
        if existing and existing.request_fingerprint == fingerprint:
            return {**withdrawal_payload(existing), "reused": True}
        raise ApiError(
            ErrorCode.WITHDRAWAL_IDEMPOTENCY_CONFLICT,
            ERROR_MESSAGES[ErrorCode.WITHDRAWAL_IDEMPOTENCY_CONFLICT],
            status_code=409,
        ) from exc


def _release_withdrawal_hold(
    *,
    account: EarningAccount,
    withdrawal: Withdrawal,
    action: str,
    idempotency_key: str,
) -> None:
    """将失败、拒绝或撤销提现的冻结金额恢复为可用余额。"""

    _create_earning_transaction(
        account=account,
        direction=EarningTransaction.Direction.RELEASE,
        transaction_type=EarningTransaction.TransactionType.WITHDRAWAL_RELEASE,
        business_type="WITHDRAWAL",
        business_no=str(withdrawal.withdrawal_no),
        amount_minor=withdrawal.amount_minor,
        idempotency_key=idempotency_key,
        request_fingerprint=withdrawal.request_fingerprint,
    )


def _freeze_for_retry(
    *,
    account: EarningAccount,
    withdrawal: Withdrawal,
    idempotency_key: str,
) -> None:
    """打款失败恢复余额后，重试前重新冻结提现金额。"""

    if account.available_amount_minor < withdrawal.amount_minor:
        raise _invalid(
            ErrorCode.WITHDRAWAL_INVALID,
            "amount_minor",
            "可提现余额不足，无法重新发起打款",
        )
    _create_earning_transaction(
        account=account,
        direction=EarningTransaction.Direction.HOLD,
        transaction_type=EarningTransaction.TransactionType.WITHDRAWAL_HOLD,
        business_type="WITHDRAWAL",
        business_no=str(withdrawal.withdrawal_no),
        amount_minor=withdrawal.amount_minor,
        idempotency_key=idempotency_key,
        request_fingerprint=withdrawal.request_fingerprint,
    )


def _execute_payout(
    *,
    admin_user: User,
    withdrawal: Withdrawal,
    action: str,
    idempotency_key: str,
) -> Withdrawal:
    """执行人工审核通过或失败重试，并完成模拟打款账务处理。"""

    previous_status = withdrawal.status
    withdrawal.status = Withdrawal.Status.PROCESSING
    withdrawal.reviewed_by_user_id = admin_user.id
    withdrawal.reviewed_at = timezone.now()
    withdrawal.failure_reason = ""
    withdrawal.version += 1
    withdrawal.save(
        update_fields=[
            "status",
            "reviewed_by_user_id",
            "reviewed_at",
            "failure_reason",
            "version",
            "updated_at",
        ],
    )
    WithdrawalStatusLog.objects.create(
        withdrawal=withdrawal,
        action=action,
        from_status=previous_status,
        to_status=withdrawal.status,
        actor_user_id=admin_user.id,
        idempotency_key=idempotency_key,
        request_fingerprint=withdrawal.request_fingerprint,
        trace_id=current_trace_id(),
    )
    try:
        channel_reference = get_payout_channel().payout(
            withdrawal_no=str(withdrawal.withdrawal_no),
            amount_minor=withdrawal.payout_amount_minor,
            account_snapshot=_parse_snapshot(withdrawal.payout_method_snapshot_encrypted),
        )
    except ApiError as exc:
        _release_withdrawal_hold(
            account=withdrawal.account,
            withdrawal=withdrawal,
            action=action,
            idempotency_key=f"payout-failed:{idempotency_key}",
        )
        withdrawal.status = Withdrawal.Status.FAILED
        withdrawal.failure_reason = str(exc.detail or exc.message)
        withdrawal.version += 1
        withdrawal.save(
            update_fields=["status", "failure_reason", "version", "updated_at"],
        )
        WithdrawalStatusLog.objects.create(
            withdrawal=withdrawal,
            action=WithdrawalStatusLog.Action.PAYOUT_FAILED,
            from_status=Withdrawal.Status.PROCESSING,
            to_status=withdrawal.status,
            actor_user_id=admin_user.id,
            reason=withdrawal.failure_reason,
            idempotency_key=f"payout-failed:{idempotency_key}",
            request_fingerprint=withdrawal.request_fingerprint,
            trace_id=current_trace_id(),
        )
        return withdrawal
    _create_earning_transaction(
        account=withdrawal.account,
        direction=EarningTransaction.Direction.DEBIT,
        transaction_type=EarningTransaction.TransactionType.WITHDRAWAL_PAYOUT,
        business_type="WITHDRAWAL",
        business_no=str(withdrawal.withdrawal_no),
        amount_minor=withdrawal.amount_minor,
        idempotency_key=f"payout-success:{idempotency_key}",
        request_fingerprint=withdrawal.request_fingerprint,
        update_totals=True,
    )
    withdrawal.status = Withdrawal.Status.SUCCESS
    withdrawal.channel_reference = channel_reference
    withdrawal.failure_reason = ""
    withdrawal.completed_at = timezone.now()
    withdrawal.version += 1
    withdrawal.save(
        update_fields=[
            "status",
            "channel_reference",
            "failure_reason",
            "completed_at",
            "version",
            "updated_at",
        ],
    )
    WithdrawalStatusLog.objects.create(
        withdrawal=withdrawal,
        action=WithdrawalStatusLog.Action.PAYOUT_SUCCEEDED,
        from_status=Withdrawal.Status.PROCESSING,
        to_status=withdrawal.status,
        actor_user_id=admin_user.id,
        idempotency_key=f"payout-success:{idempotency_key}",
        request_fingerprint=withdrawal.request_fingerprint,
        trace_id=current_trace_id(),
    )
    return withdrawal


def _parse_snapshot(value: str) -> dict[str, Any]:
    return json.loads(decrypt_text(value))


def list_withdrawals(
    *,
    user: User | None = None,
    status: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> dict[str, Any]:
    """分页返回当前用户或管理员可见提现单。"""

    queryset = Withdrawal.objects.select_related(
        "account",
        "payout_method",
    ).order_by("-created_at", "-id")
    if user is not None:
        queryset = queryset.filter(user=user)
    if status:
        queryset = queryset.filter(status=status)
    start = max(0, (page - 1) * page_size)
    return {
        "items": [withdrawal_payload(item) for item in queryset[start : start + page_size]],
        "total": queryset.count(),
        "page": page,
        "page_size": page_size,
    }


def _get_withdrawal(*, request_no: str, user: User | None = None) -> Withdrawal:
    queryset = Withdrawal.objects.select_related(
        "account",
        "payout_method",
    ).filter(withdrawal_no=request_no)
    if user is not None:
        queryset = queryset.filter(user=user)
    withdrawal = queryset.first()
    if withdrawal is None:
        raise ApiError(
            ErrorCode.WITHDRAWAL_NOT_FOUND,
            ERROR_MESSAGES[ErrorCode.WITHDRAWAL_NOT_FOUND],
            status_code=404,
        )
    return withdrawal


def cancel_withdrawal(
    *,
    user: User,
    request_no: str,
    expected_version: int,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    """用户撤销待审核提现并解冻余额。"""

    normalized_key = _normalize_idempotency_key(idempotency_key, "withdrawal-cancel")
    withdrawal = _get_withdrawal(request_no=request_no, user=user)
    fingerprint = sensitive_fingerprint(
        {
            "withdrawal_no": str(withdrawal.withdrawal_no),
            "expected_version": expected_version,
        }
    )
    replay = _withdrawal_replay(
        withdrawal=withdrawal,
        action=WithdrawalStatusLog.Action.CANCEL,
        idempotency_key=normalized_key,
        request_fingerprint=fingerprint,
    )
    if replay:
        return {**withdrawal_payload(replay), "reused": True}
    with transaction.atomic():
        locked = Withdrawal.objects.select_for_update().get(pk=withdrawal.pk)
        account = EarningAccount.objects.select_for_update().get(pk=locked.account_id)
        if locked.version != expected_version:
            raise ApiError(
                ErrorCode.WITHDRAWAL_VERSION_CONFLICT,
                ERROR_MESSAGES[ErrorCode.WITHDRAWAL_VERSION_CONFLICT],
                status_code=409,
            )
        if locked.status != Withdrawal.Status.PENDING_REVIEW:
            raise ApiError(
                ErrorCode.WITHDRAWAL_STATE_INVALID,
                ERROR_MESSAGES[ErrorCode.WITHDRAWAL_STATE_INVALID],
                status_code=409,
            )
        previous_status = locked.status
        _release_withdrawal_hold(
            account=account,
            withdrawal=locked,
            action=WithdrawalStatusLog.Action.CANCEL,
            idempotency_key=f"withdrawal-release:{normalized_key}",
        )
        locked.status = Withdrawal.Status.CANCELED
        locked.version += 1
        locked.completed_at = timezone.now()
        locked.save(update_fields=["status", "version", "completed_at", "updated_at"])
        WithdrawalStatusLog.objects.create(
            withdrawal=locked,
            action=WithdrawalStatusLog.Action.CANCEL,
            from_status=previous_status,
            to_status=locked.status,
            actor_user_id=user.id,
            idempotency_key=normalized_key,
            request_fingerprint=fingerprint,
            trace_id=current_trace_id(),
        )
        return {**withdrawal_payload(locked), "reused": False}


def reject_withdrawal(
    *,
    admin_user: User,
    request_no: str,
    expected_version: int,
    review_note: str,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    """管理员拒绝待审核提现并解冻余额。"""

    normalized_key = _normalize_idempotency_key(idempotency_key, "withdrawal-reject")
    withdrawal = _get_withdrawal(request_no=request_no)
    fingerprint = sensitive_fingerprint(
        {
            "withdrawal_no": str(withdrawal.withdrawal_no),
            "expected_version": expected_version,
            "review_note": review_note.strip(),
        }
    )
    replay = _withdrawal_replay(
        withdrawal=withdrawal,
        action=WithdrawalStatusLog.Action.REJECT,
        idempotency_key=normalized_key,
        request_fingerprint=fingerprint,
    )
    if replay:
        return {**withdrawal_payload(replay), "reused": True}
    with transaction.atomic():
        locked = Withdrawal.objects.select_for_update().get(pk=withdrawal.pk)
        account = EarningAccount.objects.select_for_update().get(pk=locked.account_id)
        if locked.version != expected_version:
            raise ApiError(
                ErrorCode.WITHDRAWAL_VERSION_CONFLICT,
                ERROR_MESSAGES[ErrorCode.WITHDRAWAL_VERSION_CONFLICT],
                status_code=409,
            )
        if locked.status != Withdrawal.Status.PENDING_REVIEW:
            raise ApiError(
                ErrorCode.WITHDRAWAL_STATE_INVALID,
                ERROR_MESSAGES[ErrorCode.WITHDRAWAL_STATE_INVALID],
                status_code=409,
            )
        previous_status = locked.status
        _release_withdrawal_hold(
            account=account,
            withdrawal=locked,
            action=WithdrawalStatusLog.Action.REJECT,
            idempotency_key=f"withdrawal-release:{normalized_key}",
        )
        locked.status = Withdrawal.Status.REJECTED
        locked.reviewed_by_user_id = admin_user.id
        locked.review_note = review_note.strip()
        locked.reviewed_at = timezone.now()
        locked.completed_at = timezone.now()
        locked.version += 1
        locked.save(
            update_fields=[
                "status",
                "reviewed_by_user_id",
                "review_note",
                "reviewed_at",
                "completed_at",
                "version",
                "updated_at",
            ],
        )
        WithdrawalStatusLog.objects.create(
            withdrawal=locked,
            action=WithdrawalStatusLog.Action.REJECT,
            from_status=previous_status,
            to_status=locked.status,
            actor_user_id=admin_user.id,
            reason=locked.review_note,
            idempotency_key=normalized_key,
            request_fingerprint=fingerprint,
            trace_id=current_trace_id(),
        )
        return {**withdrawal_payload(locked), "reused": False}


def approve_withdrawal(
    *,
    admin_user: User,
    request_no: str,
    expected_version: int,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    """管理员审核通过提现并调用模拟打款渠道。"""

    normalized_key = _normalize_idempotency_key(idempotency_key, "withdrawal-approve")
    withdrawal = _get_withdrawal(request_no=request_no)
    fingerprint = sensitive_fingerprint(
        {
            "withdrawal_no": str(withdrawal.withdrawal_no),
            "expected_version": expected_version,
            "action": "APPROVE",
        }
    )
    replay = _withdrawal_replay(
        withdrawal=withdrawal,
        action=WithdrawalStatusLog.Action.APPROVE,
        idempotency_key=normalized_key,
        request_fingerprint=fingerprint,
    )
    if replay:
        return {**withdrawal_payload(replay), "reused": True}
    with transaction.atomic():
        locked = Withdrawal.objects.select_for_update().get(pk=withdrawal.pk)
        if locked.version != expected_version:
            raise ApiError(
                ErrorCode.WITHDRAWAL_VERSION_CONFLICT,
                ERROR_MESSAGES[ErrorCode.WITHDRAWAL_VERSION_CONFLICT],
                status_code=409,
            )
        if locked.status != Withdrawal.Status.PENDING_REVIEW:
            raise ApiError(
                ErrorCode.WITHDRAWAL_STATE_INVALID,
                ERROR_MESSAGES[ErrorCode.WITHDRAWAL_STATE_INVALID],
                status_code=409,
            )
        result = _execute_payout(
            admin_user=admin_user,
            withdrawal=locked,
            action=WithdrawalStatusLog.Action.APPROVE,
            idempotency_key=normalized_key,
        )
        return {**withdrawal_payload(result), "reused": False}


def retry_withdrawal(
    *,
    admin_user: User,
    request_no: str,
    expected_version: int,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    """管理员重新发起失败提现打款。"""

    normalized_key = _normalize_idempotency_key(idempotency_key, "withdrawal-retry")
    withdrawal = _get_withdrawal(request_no=request_no)
    fingerprint = sensitive_fingerprint(
        {
            "withdrawal_no": str(withdrawal.withdrawal_no),
            "expected_version": expected_version,
            "action": "RETRY",
        }
    )
    replay = _withdrawal_replay(
        withdrawal=withdrawal,
        action=WithdrawalStatusLog.Action.RETRY,
        idempotency_key=normalized_key,
        request_fingerprint=fingerprint,
    )
    if replay:
        return {**withdrawal_payload(replay), "reused": True}
    with transaction.atomic():
        locked = Withdrawal.objects.select_for_update().get(pk=withdrawal.pk)
        account = EarningAccount.objects.select_for_update().get(pk=locked.account_id)
        if locked.version != expected_version:
            raise ApiError(
                ErrorCode.WITHDRAWAL_VERSION_CONFLICT,
                ERROR_MESSAGES[ErrorCode.WITHDRAWAL_VERSION_CONFLICT],
                status_code=409,
            )
        if locked.status != Withdrawal.Status.FAILED:
            raise ApiError(
                ErrorCode.WITHDRAWAL_STATE_INVALID,
                ERROR_MESSAGES[ErrorCode.WITHDRAWAL_STATE_INVALID],
                status_code=409,
            )
        _freeze_for_retry(
            account=account,
            withdrawal=locked,
            idempotency_key=f"withdrawal-retry-hold:{normalized_key}",
        )
        result = _execute_payout(
            admin_user=admin_user,
            withdrawal=locked,
            action=WithdrawalStatusLog.Action.RETRY,
            idempotency_key=normalized_key,
        )
        return {**withdrawal_payload(result), "reused": False}
