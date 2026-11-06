"""钱包账户、余额变动和测试充值业务服务。"""

from __future__ import annotations

import uuid
from typing import Any

from django.conf import settings
from django.db import IntegrityError, transaction
from django.db.models import F

from backend.accounts.models import User
from backend.common.context import current_trace_id
from backend.common.crypto import sensitive_fingerprint
from backend.common.errors import ERROR_MESSAGES, ErrorCode
from backend.common.exceptions import ApiError
from backend.wallets.models import WalletAccount, WalletTopUp, WalletTransaction


def _invalid(field: str, message: str) -> ApiError:
    return ApiError(
        ErrorCode.WALLET_TRANSACTION_CONFLICT,
        ERROR_MESSAGES[ErrorCode.WALLET_TRANSACTION_CONFLICT],
        status_code=400,
        details={field: message},
    )


def _validate_amount(amount_minor: int, field: str = "amount_minor") -> int:
    if not isinstance(amount_minor, int) or amount_minor <= 0:
        raise _invalid(field, "金额必须大于 0，单位为分")
    return amount_minor


def _normalize_idempotency_key(value: str | None, prefix: str) -> str:
    if value is None:
        return f"auto:{prefix}:{uuid.uuid4()}"
    key = value.strip()
    if not key or len(key) > 128:
        raise _invalid("idempotency_key", "幂等键长度必须在 1 到 128 之间")
    return key


def get_or_create_wallet(user: User, currency: str = "CNY") -> WalletAccount:
    """返回用户钱包账户，必要时创建初始零余额账户。"""

    if currency != "CNY":
        raise _invalid("currency", "当前仅支持 CNY")
    account, _ = WalletAccount.objects.get_or_create(user=user, currency=currency)
    return account


def wallet_payload(account: WalletAccount) -> dict[str, Any]:
    """返回钱包余额安全摘要。"""

    return {
        "currency": account.currency,
        "balance_amount_minor": account.balance_amount_minor,
        "frozen_amount_minor": account.frozen_amount_minor,
        "available_amount_minor": account.available_amount_minor,
        "version": account.version,
        "updated_at": account.updated_at,
    }


def wallet_transaction_payload(transaction: WalletTransaction) -> dict[str, Any]:
    """返回单条钱包流水摘要。"""

    return {
        "transaction_no": str(transaction.transaction_no),
        "direction": transaction.direction,
        "transaction_type": transaction.transaction_type,
        "business_type": transaction.business_type,
        "business_no": transaction.business_no,
        "currency": transaction.currency,
        "amount_minor": transaction.amount_minor,
        "balance_after_amount_minor": transaction.balance_after_amount_minor,
        "created_at": transaction.created_at,
    }


def _create_transaction(
    *,
    account: WalletAccount,
    direction: str,
    transaction_type: str,
    business_type: str,
    business_no: str,
    amount_minor: int,
    idempotency_key: str,
    request_fingerprint: str,
) -> tuple[WalletTransaction, bool]:
    existing = WalletTransaction.objects.filter(
        account=account,
        business_type=business_type,
        business_no=business_no,
        idempotency_key=idempotency_key,
    ).first()
    if existing:
        if existing.request_fingerprint != request_fingerprint:
            raise ApiError(
                ErrorCode.WALLET_TRANSACTION_CONFLICT,
                ERROR_MESSAGES[ErrorCode.WALLET_TRANSACTION_CONFLICT],
                status_code=409,
            )
        return existing, False
    if direction == WalletTransaction.Direction.DEBIT:
        balance_after = account.balance_amount_minor - amount_minor
    else:
        balance_after = account.balance_amount_minor + amount_minor
    return (
        WalletTransaction.objects.create(
            account=account,
            user=account.user,
            direction=direction,
            transaction_type=transaction_type,
            business_type=business_type,
            business_no=business_no,
            currency=account.currency,
            amount_minor=amount_minor,
            balance_after_amount_minor=balance_after,
            idempotency_key=idempotency_key,
            request_fingerprint=request_fingerprint,
            trace_id=current_trace_id(),
        ),
        True,
    )


def get_wallet_available_amount(user: User, currency: str = "CNY") -> int:
    """查询用户指定币种的当前可用余额，不存在账户时返回 0。"""

    account = WalletAccount.objects.filter(user=user, currency=currency).first()
    return account.available_amount_minor if account else 0


def debit_wallet(
    *,
    user: User,
    amount_minor: int,
    transaction_type: str,
    business_type: str,
    business_no: str,
    idempotency_key: str,
    request_fingerprint: str | None = None,
) -> tuple[WalletAccount, WalletTransaction]:
    """原子扣减钱包余额并写入不可变 DEBIT 流水。"""

    amount_minor = _validate_amount(amount_minor)
    normalized_key = _normalize_idempotency_key(idempotency_key, business_type)
    fingerprint = request_fingerprint or sensitive_fingerprint(
        {
            "amount_minor": amount_minor,
            "business_type": business_type,
            "business_no": business_no,
        }
    )
    with transaction.atomic():
        account = WalletAccount.objects.select_for_update().get_or_create(
            user=user,
            currency="CNY",
        )[0]
        if account.available_amount_minor < amount_minor:
            raise ApiError(
                ErrorCode.WALLET_INSUFFICIENT_BALANCE,
                ERROR_MESSAGES[ErrorCode.WALLET_INSUFFICIENT_BALANCE],
                status_code=402,
                details={
                    "available_amount_minor": account.available_amount_minor,
                    "required_amount_minor": amount_minor,
                },
            )
        wallet_transaction, created = _create_transaction(
            account=account,
            direction=WalletTransaction.Direction.DEBIT,
            transaction_type=transaction_type,
            business_type=business_type,
            business_no=business_no,
            amount_minor=amount_minor,
            idempotency_key=normalized_key,
            request_fingerprint=fingerprint,
        )
        if not created:
            account.refresh_from_db()
            return account, wallet_transaction
        account.balance_amount_minor = F("balance_amount_minor") - amount_minor
        account.version = F("version") + 1
        account.save(update_fields=["balance_amount_minor", "version", "updated_at"])
        account.refresh_from_db()
        return account, wallet_transaction


def credit_wallet(
    *,
    user: User,
    amount_minor: int,
    transaction_type: str,
    business_type: str,
    business_no: str,
    idempotency_key: str,
    request_fingerprint: str | None = None,
) -> tuple[WalletAccount, WalletTransaction]:
    """原子增加钱包余额并写入不可变 CREDIT 流水。"""

    amount_minor = _validate_amount(amount_minor)
    normalized_key = _normalize_idempotency_key(idempotency_key, business_type)
    fingerprint = request_fingerprint or sensitive_fingerprint(
        {
            "amount_minor": amount_minor,
            "business_type": business_type,
            "business_no": business_no,
        }
    )
    with transaction.atomic():
        account = WalletAccount.objects.select_for_update().get_or_create(
            user=user,
            currency="CNY",
        )[0]
        wallet_transaction, created = _create_transaction(
            account=account,
            direction=WalletTransaction.Direction.CREDIT,
            transaction_type=transaction_type,
            business_type=business_type,
            business_no=business_no,
            amount_minor=amount_minor,
            idempotency_key=normalized_key,
            request_fingerprint=fingerprint,
        )
        if not created:
            account.refresh_from_db()
            return account, wallet_transaction
        account.balance_amount_minor = F("balance_amount_minor") + amount_minor
        account.version = F("version") + 1
        account.save(update_fields=["balance_amount_minor", "version", "updated_at"])
        account.refresh_from_db()
        return account, wallet_transaction


def admin_top_up_wallet(
    *,
    target_user: User,
    created_by: User,
    amount_minor: int,
    reason: str,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    """由管理员写入开发测试余额，普通用户不能自主调用。"""

    if not settings.ENABLE_DEV_WALLET_TOPUP or settings.PAYMENT_MODE == "REAL":
        raise ApiError(
            ErrorCode.WALLET_TOPUP_DISABLED,
            ERROR_MESSAGES[ErrorCode.WALLET_TOPUP_DISABLED],
            status_code=403,
        )
    amount_minor = _validate_amount(amount_minor)
    normalized_key = _normalize_idempotency_key(idempotency_key, "topup")
    fingerprint = sensitive_fingerprint(
        {
            "target_user_id": target_user.id,
            "amount_minor": amount_minor,
            "reason": reason.strip(),
        }
    )
    try:
        with transaction.atomic():
            account, wallet_transaction = credit_wallet(
                user=target_user,
                amount_minor=amount_minor,
                transaction_type=WalletTransaction.TransactionType.TOPUP,
                business_type="WALLET_TOPUP",
                business_no=f"TOPUP-{uuid.uuid4().hex.upper()}",
                idempotency_key=normalized_key,
                request_fingerprint=fingerprint,
            )
            topup = WalletTopUp.objects.create(
                user=target_user,
                account=account,
                amount_minor=amount_minor,
                idempotency_key=normalized_key,
                reason=reason.strip(),
                created_by_user_id=created_by.id,
            )
            return {
                "topup_no": str(topup.topup_no),
                "status": topup.status,
                "channel": topup.channel,
                "currency": topup.currency,
                "amount_minor": topup.amount_minor,
                "wallet_balance_amount_minor": account.balance_amount_minor,
                "transaction_no": str(wallet_transaction.transaction_no),
            }
    except IntegrityError as exc:
        topup = WalletTopUp.objects.filter(
            user=target_user,
            idempotency_key=normalized_key,
        ).first()
        if topup and topup.amount_minor == amount_minor:
            return {
                "topup_no": str(topup.topup_no),
                "status": topup.status,
                "channel": topup.channel,
                "currency": topup.currency,
                "amount_minor": topup.amount_minor,
                "wallet_balance_amount_minor": topup.account.balance_amount_minor,
                "transaction_no": None,
            }
        raise ApiError(
            ErrorCode.WALLET_TRANSACTION_CONFLICT,
            ERROR_MESSAGES[ErrorCode.WALLET_TRANSACTION_CONFLICT],
            status_code=409,
        ) from exc
