"""钱包余额支付和退款适配业务服务。"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from django.db import IntegrityError, transaction
from django.utils import timezone

from backend.accounts.models import User
from backend.common.crypto import sensitive_fingerprint
from backend.common.errors import ERROR_MESSAGES, ErrorCode
from backend.common.exceptions import ApiError
from backend.payments.models import Payment, Refund
from backend.wallets.models import WalletTransaction
from backend.wallets.services import credit_wallet, debit_wallet


@dataclass(frozen=True)
class PaymentChargeResult:
    """余额支付结果。"""

    payment: Payment
    reused: bool


def _normalize_idempotency_key(value: str | None, prefix: str) -> str:
    if value is None:
        return f"auto:{prefix}:{uuid.uuid4()}"
    key = value.strip()
    if not key or len(key) > 128:
        raise ApiError(
            ErrorCode.WALLET_TRANSACTION_CONFLICT,
            ERROR_MESSAGES[ErrorCode.WALLET_TRANSACTION_CONFLICT],
            status_code=400,
            details={"idempotency_key": "幂等键长度必须在 1 到 128 之间"},
        )
    return key


def payment_payload(payment: Payment) -> dict[str, Any]:
    """返回支付单安全摘要。"""

    return {
        "payment_no": str(payment.payment_no),
        "order_no": payment.order_no,
        "payment_method": payment.payment_method,
        "payment_channel": payment.payment_channel,
        "currency": payment.currency,
        "amount_minor": payment.amount_minor,
        "status": payment.status,
        "paid_at": payment.paid_at,
        "version": payment.version,
    }


def charge_wallet_for_order(
    *,
    user: User,
    order_no: str,
    amount_minor: int,
    idempotency_key: str | None = None,
) -> PaymentChargeResult:
    """为订单同步执行钱包余额支付并落支付单。"""

    normalized_key = _normalize_idempotency_key(idempotency_key, "payment")
    fingerprint = sensitive_fingerprint(
        {
            "order_no": order_no,
            "amount_minor": amount_minor,
            "payment_method": "BALANCE",
        }
    )
    try:
        with transaction.atomic():
            existing = Payment.objects.filter(
                user=user,
                idempotency_key=normalized_key,
            ).first()
            if existing:
                if existing.request_fingerprint != fingerprint:
                    raise ApiError(
                        ErrorCode.WALLET_TRANSACTION_CONFLICT,
                        ERROR_MESSAGES[ErrorCode.WALLET_TRANSACTION_CONFLICT],
                        status_code=409,
                    )
                return PaymentChargeResult(existing, reused=True)
            _account, _ = debit_wallet(
                user=user,
                amount_minor=amount_minor,
                transaction_type=WalletTransaction.TransactionType.ORDER_PAYMENT,
                business_type="ORDER_PAYMENT",
                business_no=order_no,
                idempotency_key=normalized_key,
                request_fingerprint=fingerprint,
            )
            payment = Payment.objects.create(
                user=user,
                order_no=order_no,
                amount_minor=amount_minor,
                status=Payment.Status.SUCCESS,
                paid_at=timezone.now(),
                idempotency_key=normalized_key,
                request_fingerprint=fingerprint,
            )
            return PaymentChargeResult(payment, reused=False)
    except IntegrityError as exc:
        existing = Payment.objects.filter(user=user, idempotency_key=normalized_key).first()
        if existing and existing.request_fingerprint == fingerprint:
            return PaymentChargeResult(existing, reused=True)
        raise ApiError(
            ErrorCode.WALLET_TRANSACTION_CONFLICT,
            ERROR_MESSAGES[ErrorCode.WALLET_TRANSACTION_CONFLICT],
            status_code=409,
        ) from exc


def refund_wallet_for_payment(
    *,
    payment: Payment,
    refund_amount_minor: int,
    idempotency_key: str | None = None,
) -> Refund:
    """将余额支付金额原路退回钱包并落退款单。"""

    normalized_key = _normalize_idempotency_key(idempotency_key, "refund")
    existing = Refund.objects.filter(
        payment=payment,
        idempotency_key=normalized_key,
    ).first()
    if existing:
        return existing
    if payment.status != Payment.Status.SUCCESS:
        raise ApiError(
            ErrorCode.WALLET_TRANSACTION_CONFLICT,
            ERROR_MESSAGES[ErrorCode.WALLET_TRANSACTION_CONFLICT],
            status_code=409,
            details={"payment_status": "支付单未成功，不能退款"},
        )
    try:
        with transaction.atomic():
            _account, _ = credit_wallet(
                user=payment.user,
                amount_minor=refund_amount_minor,
                transaction_type=WalletTransaction.TransactionType.ORDER_REFUND,
                business_type="ORDER_REFUND",
                business_no=payment.order_no,
                idempotency_key=normalized_key,
                request_fingerprint=sensitive_fingerprint(
                    {
                        "payment_no": str(payment.payment_no),
                        "refund_amount_minor": refund_amount_minor,
                    }
                ),
            )
            refund = Refund.objects.create(
                payment=payment,
                user=payment.user,
                order_no=payment.order_no,
                refund_amount_minor=refund_amount_minor,
                idempotency_key=normalized_key,
            )
            payment.status = Payment.Status.REFUNDED
            payment.version += 1
            payment.save(update_fields=["status", "version", "updated_at"])
            return refund
    except IntegrityError as exc:
        existing = Refund.objects.filter(payment=payment, idempotency_key=normalized_key).first()
        if existing:
            return existing
        raise ApiError(
            ErrorCode.WALLET_TRANSACTION_CONFLICT,
            ERROR_MESSAGES[ErrorCode.WALLET_TRANSACTION_CONFLICT],
            status_code=409,
        ) from exc
