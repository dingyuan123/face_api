"""开发和自动化测试使用的模拟外部支付渠道。"""

from __future__ import annotations

from typing import Any

from backend.integrations.payments.contracts import (
    PaymentGateway,
    PaymentInitiation,
    PaymentNotification,
    RefundResult,
)


class MockExternalPaymentGateway(PaymentGateway):
    """模拟微信/支付宝 App 支付，不发起真实资金交易。"""

    def __init__(self, *, channel: str) -> None:
        self._channel = channel

    def create_app_payment(
        self,
        *,
        payment_no: str,
        description: str,
        amount_minor: int,
    ) -> PaymentInitiation:
        """返回前端联调可识别的模拟原生支付参数。"""
        return PaymentInitiation(
            channel_reference=f"mock-{payment_no}",
            client_payload={
                "mock": True,
                "channel": self._channel,
                "payment_no": payment_no,
                "description": description,
                "amount_minor": amount_minor,
            },
        )

    def refund(
        self,
        *,
        payment_no: str,
        refund_no: str,
        amount_minor: int,
    ) -> RefundResult:
        """模拟外部退款并立即确认成功。"""
        return RefundResult(
            channel_refund_no=f"mock-refund-{refund_no}",
            status="SUCCESS",
            channel_status="REFUND_SUCCESS",
        )

    def verify_notification(
        self,
        *,
        raw_body: bytes,
        headers: dict[str, str],
        form_data: dict[str, Any],
    ) -> PaymentNotification:
        """测试回调只在开发模式开放，生产环境不会使用该适配器。"""
        payload = dict(form_data)
        return PaymentNotification(
            event_type=str(payload.get("event_type", "PAYMENT")),
            out_trade_no=str(payload.get("out_trade_no", "")),
            transaction_no=str(payload.get("transaction_no", "")),
            amount_minor=int(payload.get("amount_minor", 0)),
            success=bool(payload.get("success", True)),
            channel_status=str(payload.get("channel_status", "SUCCESS")),
            refund_no=str(payload.get("refund_no", "")),
        )
