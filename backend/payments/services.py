"""订单余额、微信和支付宝支付及原路退款的统一业务服务。"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from django.db import IntegrityError, transaction
from django.utils import timezone

from backend.accounts.models import User
from backend.common.crypto import sensitive_fingerprint
from backend.common.display import enum_label
from backend.common.errors import ERROR_MESSAGES, ErrorCode
from backend.common.exceptions import ApiError
from backend.integrations.payments.contracts import (
    PaymentGatewayError,
    PaymentGatewayUnavailable,
    PaymentNotification,
)
from backend.integrations.payments.factory import get_payment_gateway
from backend.payments.models import Payment, Refund
from backend.wallets.models import WalletTransaction
from backend.wallets.services import credit_wallet, debit_wallet


@dataclass(frozen=True)
class PaymentChargeResult:
    """支付发起或幂等复用结果。"""

    payment: Payment
    reused: bool


def _normalize_idempotency_key(value: str | None, prefix: str) -> str:
    """规范化幂等键，未提供时使用一次性自动键。"""
    if value is None:
        return f"auto:{prefix}:{uuid.uuid4()}"
    key = value.strip()
    if not key or len(key) > 128:
        raise ApiError(
            ErrorCode.PAYMENT_INVALID,
            ERROR_MESSAGES[ErrorCode.PAYMENT_INVALID],
            status_code=400,
            details={"idempotency_key": "幂等键长度必须在 1 到 128 之间"},
        )
    return key


def payment_payload(payment: Payment) -> dict[str, Any]:
    """返回支付单安全摘要和原生 SDK 参数，不返回商户密钥。"""
    return {
        "payment_no": str(payment.payment_no),
        "order_no": payment.order_no,
        "business_type": payment.business_type,
        "business_no": payment.business_no,
        "payment_method": payment.payment_method,
        "payment_method_text": enum_label(Payment.Method, payment.payment_method),
        "payment_channel": payment.payment_channel,
        "currency": payment.currency,
        "amount_minor": payment.amount_minor,
        "status": payment.status,
        "status_text": enum_label(Payment.Status, payment.status),
        "client_payload": payment.client_payload,
        "expires_at": payment.expires_at,
        "paid_at": payment.paid_at,
        "version": payment.version,
    }


def charge_wallet_for_order(
    *,
    user: User,
    order_no: str,
    amount_minor: int,
    idempotency_key: str | None = None,
    business_type: str = Payment.BusinessType.ORDER,
    business_no: str | None = None,
) -> PaymentChargeResult:
    """同步执行钱包余额业务支付并落支付单，重复请求返回原支付单。"""
    normalized_key = _normalize_idempotency_key(idempotency_key, "payment")
    effective_business_no = business_no or order_no
    fingerprint = sensitive_fingerprint(
        {
            "business_type": business_type,
            "business_no": effective_business_no,
            "order_no": order_no,
            "amount_minor": amount_minor,
            "payment_method": "BALANCE",
        }
    )
    try:
        with transaction.atomic():
            existing = Payment.objects.filter(user=user, idempotency_key=normalized_key).first()
            if existing:
                _ensure_same_payment_request(existing, fingerprint)
                return PaymentChargeResult(existing, reused=True)
            _account, _ = debit_wallet(
                user=user,
                amount_minor=amount_minor,
                transaction_type=(
                    WalletTransaction.TransactionType.ORDER_PAYMENT
                    if business_type == Payment.BusinessType.ORDER
                    else WalletTransaction.TransactionType.MEMBERSHIP_PURCHASE
                ),
                business_type=(
                    "ORDER_PAYMENT"
                    if business_type == Payment.BusinessType.ORDER
                    else "MEMBERSHIP_PURCHASE"
                ),
                business_no=effective_business_no,
                idempotency_key=normalized_key,
                request_fingerprint=fingerprint,
            )
            payment = Payment.objects.create(
                user=user,
                order_no=order_no,
                business_type=business_type,
                business_no=effective_business_no,
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
            ErrorCode.PAYMENT_INVALID,
            ERROR_MESSAGES[ErrorCode.PAYMENT_INVALID],
            status_code=409,
        ) from exc


def create_external_payment(
    *,
    user: User,
    order_no: str,
    amount_minor: int,
    payment_method: str,
    description: str,
    idempotency_key: str | None = None,
    business_type: str = Payment.BusinessType.ORDER,
    business_no: str | None = None,
) -> PaymentChargeResult:
    """创建微信或支付宝 App 支付单，提交事务后再安全调用外部渠道。"""
    if payment_method not in {
        Payment.Method.WECHAT_APP,
        Payment.Method.ALIPAY_APP,
    }:
        raise ApiError(
            ErrorCode.PAYMENT_INVALID,
            ERROR_MESSAGES[ErrorCode.PAYMENT_INVALID],
            status_code=400,
        )
    normalized_key = _normalize_idempotency_key(idempotency_key, "external-payment")
    effective_business_no = business_no or order_no
    fingerprint = sensitive_fingerprint(
        {
            "business_type": business_type,
            "business_no": effective_business_no,
            "order_no": order_no,
            "amount_minor": amount_minor,
            "payment_method": payment_method,
        }
    )
    channel = "WECHAT" if payment_method == Payment.Method.WECHAT_APP else "ALIPAY"
    try:
        with transaction.atomic():
            existing = Payment.objects.filter(user=user, idempotency_key=normalized_key).first()
            if existing:
                _ensure_same_payment_request(existing, fingerprint)
                if existing.status not in {Payment.Status.PENDING, Payment.Status.FAILED}:
                    return PaymentChargeResult(existing, reused=True)
                payment = existing
            else:
                payment = Payment.objects.create(
                    user=user,
                    order_no=order_no,
                    business_type=business_type,
                    business_no=effective_business_no,
                    payment_method=payment_method,
                    payment_channel=channel,
                    amount_minor=amount_minor,
                    status=Payment.Status.PENDING,
                    idempotency_key=normalized_key,
                    request_fingerprint=fingerprint,
                )
    except IntegrityError as exc:
        raise ApiError(
            ErrorCode.PAYMENT_INVALID,
            ERROR_MESSAGES[ErrorCode.PAYMENT_INVALID],
            status_code=409,
        ) from exc

    try:
        initiation = get_payment_gateway(payment_method).create_app_payment(
            payment_no=str(payment.payment_no),
            description=description,
            amount_minor=amount_minor,
        )
    except PaymentGatewayUnavailable as exc:
        _mark_payment_failed(payment, str(exc))
        raise ApiError(
            ErrorCode.PAYMENT_GATEWAY_UNAVAILABLE,
            ERROR_MESSAGES[ErrorCode.PAYMENT_GATEWAY_UNAVAILABLE],
            status_code=503,
        ) from exc
    except PaymentGatewayError as exc:
        _mark_payment_failed(payment, str(exc))
        raise ApiError(
            ErrorCode.PAYMENT_INVALID,
            ERROR_MESSAGES[ErrorCode.PAYMENT_INVALID],
            status_code=502,
            details={"payment_method": str(exc)},
        ) from exc

    payment.channel_reference = initiation.channel_reference
    payment.client_payload = initiation.client_payload
    payment.status = Payment.Status.PENDING
    payment.failure_reason = ""
    payment.version += 1
    payment.save(
        update_fields=[
            "channel_reference",
            "client_payload",
            "status",
            "failure_reason",
            "version",
            "updated_at",
        ]
    )
    return PaymentChargeResult(payment, reused=False)


def handle_payment_notification(
    *,
    notification: PaymentNotification,
) -> Payment | Refund:
    """将已验签的渠道通知幂等落账，并在同一事务确认订单支付。"""
    if notification.refund_no:
        return handle_refund_notification(notification=notification)
    if not notification.out_trade_no:
        raise ApiError(
            ErrorCode.PAYMENT_NOTIFY_INVALID,
            ERROR_MESSAGES[ErrorCode.PAYMENT_NOTIFY_INVALID],
            status_code=400,
        )
    try:
        payment_uuid = uuid.UUID(notification.out_trade_no)
    except ValueError as exc:
        raise ApiError(
            ErrorCode.PAYMENT_NOTIFY_INVALID,
            ERROR_MESSAGES[ErrorCode.PAYMENT_NOTIFY_INVALID],
            status_code=400,
        ) from exc
    with transaction.atomic():
        payment = Payment.objects.select_for_update().filter(payment_no=payment_uuid).first()
        if payment is None:
            raise ApiError(
                ErrorCode.PAYMENT_NOT_FOUND,
                ERROR_MESSAGES[ErrorCode.PAYMENT_NOT_FOUND],
                status_code=404,
            )
        if not notification.success:
            if payment.status == Payment.Status.PENDING:
                payment.status = Payment.Status.FAILED
                payment.channel_status = notification.channel_status
                payment.failure_reason = "支付渠道通知交易未成功"
                payment.version += 1
                payment.save(
                    update_fields=[
                        "status",
                        "channel_status",
                        "failure_reason",
                        "version",
                        "updated_at",
                    ]
                )
            return payment
        if payment.status == Payment.Status.SUCCESS:
            if (
                payment.channel_transaction_no
                and payment.channel_transaction_no != notification.transaction_no
            ):
                raise ApiError(
                    ErrorCode.PAYMENT_NOTIFY_INVALID,
                    ERROR_MESSAGES[ErrorCode.PAYMENT_NOTIFY_INVALID],
                    status_code=409,
                )
            return payment
        if payment.status not in {
            Payment.Status.PENDING,
            Payment.Status.FAILED,
        }:
            raise ApiError(
                ErrorCode.PAYMENT_STATE_INVALID,
                ERROR_MESSAGES[ErrorCode.PAYMENT_STATE_INVALID],
                status_code=409,
            )
        if notification.amount_minor != payment.amount_minor:
            raise ApiError(
                ErrorCode.PAYMENT_AMOUNT_MISMATCH,
                ERROR_MESSAGES[ErrorCode.PAYMENT_AMOUNT_MISMATCH],
                status_code=409,
            )
        if not notification.transaction_no:
            raise ApiError(
                ErrorCode.PAYMENT_NOTIFY_INVALID,
                ERROR_MESSAGES[ErrorCode.PAYMENT_NOTIFY_INVALID],
                status_code=400,
            )
        payment.channel_transaction_no = notification.transaction_no
        payment.channel_status = notification.channel_status
        payment.status = Payment.Status.SUCCESS
        payment.paid_at = timezone.now()
        payment.failure_reason = ""
        payment.version += 1
        payment.save(
            update_fields=[
                "channel_transaction_no",
                "channel_status",
                "status",
                "paid_at",
                "failure_reason",
                "version",
                "updated_at",
            ]
        )
        if payment.business_type == Payment.BusinessType.MEMBERSHIP_PURCHASE:
            from backend.memberships.services import confirm_membership_payment

            confirm_membership_payment(payment=payment)
        else:
            from backend.orders.services import confirm_order_payment

            confirm_order_payment(payment=payment)
        return payment


def handle_refund_notification(
    *,
    notification: PaymentNotification,
) -> Refund:
    """将已验签的原渠道退款通知幂等写入退款单和订单退款申请。"""
    if not notification.refund_no:
        raise ApiError(
            ErrorCode.PAYMENT_NOTIFY_INVALID,
            ERROR_MESSAGES[ErrorCode.PAYMENT_NOTIFY_INVALID],
            status_code=400,
        )
    try:
        refund_uuid = uuid.UUID(notification.refund_no)
    except ValueError as exc:
        raise ApiError(
            ErrorCode.PAYMENT_NOTIFY_INVALID,
            ERROR_MESSAGES[ErrorCode.PAYMENT_NOTIFY_INVALID],
            status_code=400,
        ) from exc
    with transaction.atomic():
        refund = (
            Refund.objects.select_for_update()
            .select_related("payment")
            .filter(refund_no=refund_uuid)
            .first()
        )
        if refund is None:
            raise ApiError(
                ErrorCode.PAYMENT_NOT_FOUND,
                ERROR_MESSAGES[ErrorCode.PAYMENT_NOT_FOUND],
                status_code=404,
            )
        _require_order_payment(refund.payment)
        try:
            notification_payment_uuid = uuid.UUID(notification.out_trade_no)
        except ValueError as exc:
            raise ApiError(
                ErrorCode.PAYMENT_NOTIFY_INVALID,
                ERROR_MESSAGES[ErrorCode.PAYMENT_NOTIFY_INVALID],
                status_code=400,
            ) from exc
        if refund.payment.payment_no != notification_payment_uuid:
            raise ApiError(
                ErrorCode.PAYMENT_NOTIFY_INVALID,
                ERROR_MESSAGES[ErrorCode.PAYMENT_NOTIFY_INVALID],
                status_code=409,
            )
        if notification.amount_minor != refund.refund_amount_minor:
            raise ApiError(
                ErrorCode.PAYMENT_AMOUNT_MISMATCH,
                ERROR_MESSAGES[ErrorCode.PAYMENT_AMOUNT_MISMATCH],
                status_code=409,
            )
        if refund.status == Refund.Status.SUCCESS:
            if not notification.success or (
                refund.channel_refund_no
                and notification.transaction_no
                and refund.channel_refund_no != notification.transaction_no
            ):
                raise ApiError(
                    ErrorCode.PAYMENT_NOTIFY_INVALID,
                    ERROR_MESSAGES[ErrorCode.PAYMENT_NOTIFY_INVALID],
                    status_code=409,
                )
            updated = refund
        elif refund.status == Refund.Status.FAILED and not notification.success:
            updated = refund
        else:
            updated = _complete_refund(
                refund,
                Refund.Status.SUCCESS if notification.success else Refund.Status.FAILED,
                "" if notification.success else "支付渠道退款通知未成功",
                notification.channel_status,
                notification.transaction_no,
            )
    from backend.orders.services import apply_order_refund_result

    apply_order_refund_result(refund=updated)
    updated.refresh_from_db()
    return updated


def get_payment(*, user: User, payment_no: str) -> Payment:
    """查询当前用户的支付单，防止跨账号读取支付信息。"""
    try:
        payment_uuid = uuid.UUID(payment_no)
    except ValueError as exc:
        raise ApiError(
            ErrorCode.PAYMENT_NOT_FOUND,
            ERROR_MESSAGES[ErrorCode.PAYMENT_NOT_FOUND],
            status_code=404,
        ) from exc
    payment = Payment.objects.filter(user=user, payment_no=payment_uuid).first()
    if payment is None:
        raise ApiError(
            ErrorCode.PAYMENT_NOT_FOUND,
            ERROR_MESSAGES[ErrorCode.PAYMENT_NOT_FOUND],
            status_code=404,
        )
    return payment


def refund_payment(
    *,
    payment: Payment,
    refund_amount_minor: int,
    idempotency_key: str | None = None,
) -> Refund:
    """按支付单原渠道退款，余额支付入账，外部支付由适配器受理。"""
    _require_order_payment(payment)
    normalized_key = _normalize_idempotency_key(idempotency_key, "refund")
    existing = Refund.objects.filter(
        payment=payment,
        idempotency_key=normalized_key,
    ).first()
    if existing:
        return existing
    if payment.status != Payment.Status.SUCCESS:
        raise ApiError(
            ErrorCode.PAYMENT_STATE_INVALID,
            ERROR_MESSAGES[ErrorCode.PAYMENT_STATE_INVALID],
            status_code=409,
            details={"payment_status": "支付单未成功，不能退款"},
        )
    refund = register_refund(
        payment=payment,
        refund_amount_minor=refund_amount_minor,
        idempotency_key=normalized_key,
    )
    executed = execute_refund(refund)
    payment.refresh_from_db()
    return executed


def _require_order_payment(payment: Payment) -> None:
    """禁止对会员购买等非预约订单支付单发起退款。"""
    if payment.business_type != Payment.BusinessType.ORDER:
        raise ApiError(
            ErrorCode.PAYMENT_REFUND_NOT_ALLOWED,
            ERROR_MESSAGES[ErrorCode.PAYMENT_REFUND_NOT_ALLOWED],
            status_code=409,
        )


def register_refund(
    *,
    payment: Payment,
    refund_amount_minor: int,
    idempotency_key: str,
) -> Refund:
    """只登记退款单，不在数据库事务内调用外部退款渠道。"""
    _require_order_payment(payment)
    existing = Refund.objects.filter(
        payment=payment,
        idempotency_key=idempotency_key,
    ).first()
    if existing:
        return existing
    if payment.status != Payment.Status.SUCCESS:
        raise ApiError(
            ErrorCode.PAYMENT_STATE_INVALID,
            ERROR_MESSAGES[ErrorCode.PAYMENT_STATE_INVALID],
            status_code=409,
            details={"payment_status": "支付单未成功，不能退款"},
        )
    if refund_amount_minor <= 0:
        raise ApiError(
            ErrorCode.PAYMENT_AMOUNT_MISMATCH,
            "退款金额必须大于 0",
            status_code=400,
        )
    already_refundable = sum(
        item.refund_amount_minor
        for item in payment.refunds.filter(
            status__in=[Refund.Status.PENDING, Refund.Status.SUCCESS]
        )
    )
    if refund_amount_minor > payment.amount_minor - already_refundable:
        raise ApiError(
            ErrorCode.PAYMENT_AMOUNT_MISMATCH,
            "退款金额超过支付单剩余可退金额",
            status_code=409,
        )
    refund_method = Payment.Method(payment.payment_method)
    try:
        with transaction.atomic():
            return Refund.objects.create(
                payment=payment,
                user=payment.user,
                order_no=payment.order_no,
                refund_method=refund_method,
                currency=payment.currency,
                refund_amount_minor=refund_amount_minor,
                idempotency_key=idempotency_key,
            )
    except IntegrityError as exc:
        existing = Refund.objects.filter(
            payment=payment,
            idempotency_key=idempotency_key,
        ).first()
        if existing:
            return existing
        raise ApiError(
            ErrorCode.PAYMENT_STATE_INVALID,
            ERROR_MESSAGES[ErrorCode.PAYMENT_STATE_INVALID],
            status_code=409,
        ) from exc


def execute_refund(refund: Refund) -> Refund:
    """执行已经登记的退款，不在数据库事务或行锁内访问外部支付网络。"""
    _require_order_payment(refund.payment)
    if refund.status == Refund.Status.SUCCESS:
        return refund
    if refund.payment.payment_method == Payment.Method.BALANCE:
        with transaction.atomic():
            current = Refund.objects.select_for_update().get(pk=refund.pk)
            if current.status != Refund.Status.PENDING:
                return current
            _account, _ = credit_wallet(
                user=current.user,
                amount_minor=current.refund_amount_minor,
                transaction_type=WalletTransaction.TransactionType.ORDER_REFUND,
                business_type="ORDER_REFUND",
                business_no=current.order_no,
                idempotency_key=current.idempotency_key,
                request_fingerprint=sensitive_fingerprint(
                    {
                        "payment_no": str(current.payment.payment_no),
                        "refund_amount_minor": current.refund_amount_minor,
                    }
                ),
            )
            return _complete_refund(current, "SUCCESS", "", "INTERNAL")
    try:
        result = get_payment_gateway(refund.payment.payment_method).refund(
            payment_no=str(refund.payment.payment_no),
            refund_no=str(refund.refund_no),
            amount_minor=refund.refund_amount_minor,
        )
    except PaymentGatewayUnavailable as exc:
        return _complete_refund(refund, "PENDING", str(exc), "GATEWAY_UNAVAILABLE")
    except PaymentGatewayError as exc:
        return _complete_refund(refund, "FAILED", str(exc), "GATEWAY_REJECTED")
    return _complete_refund(
        refund,
        result.status,
        result.failure_reason,
        result.channel_status,
        result.channel_refund_no,
    )


def refund_wallet_for_payment(
    *,
    payment: Payment,
    refund_amount_minor: int,
    idempotency_key: str | None = None,
) -> Refund:
    """兼容旧调用的统一退款入口，实际按支付单原渠道执行。"""
    return refund_payment(
        payment=payment,
        refund_amount_minor=refund_amount_minor,
        idempotency_key=idempotency_key,
    )


def _complete_refund(
    refund: Refund,
    status: str,
    failure_reason: str,
    channel_status: str,
    channel_refund_no: str = "",
) -> Refund:
    """在数据库事务内确认退款结果并仅在成功时更新支付单。"""
    with transaction.atomic():
        current = Refund.objects.select_for_update().get(pk=refund.pk)
        current.status = status
        current.failure_reason = failure_reason[:500]
        current.channel_status = channel_status[:32]
        if channel_refund_no:
            current.channel_refund_no = channel_refund_no[:128]
        current.completed_at = timezone.now() if status == Refund.Status.SUCCESS else None
        current.save(
            update_fields=[
                "status",
                "failure_reason",
                "channel_status",
                "channel_refund_no",
                "completed_at",
            ]
        )
        if status == Refund.Status.SUCCESS:
            payment = Payment.objects.select_for_update().get(pk=current.payment_id)
            payment.status = Payment.Status.REFUNDED
            payment.version += 1
            payment.save(update_fields=["status", "version", "updated_at"])
        return current


def _mark_payment_failed(payment: Payment, reason: str) -> None:
    """渠道下单失败时安全记录简短原因，不保存完整第三方响应。"""
    payment.status = Payment.Status.FAILED
    payment.failure_reason = reason[:500]
    payment.version += 1
    payment.save(update_fields=["status", "failure_reason", "version", "updated_at"])


def _ensure_same_payment_request(payment: Payment, fingerprint: str) -> None:
    """确保相同幂等键对应完全一致的订单和支付金额。"""
    if payment.request_fingerprint != fingerprint:
        raise ApiError(
            ErrorCode.PAYMENT_INVALID,
            ERROR_MESSAGES[ErrorCode.PAYMENT_INVALID],
            status_code=409,
            details={"idempotency_key": "幂等请求与原请求不一致"},
        )
