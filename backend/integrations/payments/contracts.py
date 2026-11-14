"""支付渠道适配器统一契约，业务层不依赖具体支付 SDK。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


class PaymentGatewayError(Exception):
    """支付渠道返回业务拒绝、签名错误或请求参数错误。"""


class PaymentGatewayUnavailable(Exception):
    """支付渠道网络、配置或服务能力暂时不可用。"""


@dataclass(frozen=True)
class PaymentInitiation:
    """第三方 App 支付下单结果，只包含可交给客户端 SDK 的参数。"""

    channel_reference: str
    client_payload: dict[str, Any]


@dataclass(frozen=True)
class RefundResult:
    """原渠道退款受理结果。"""

    channel_refund_no: str
    status: str
    channel_status: str
    failure_reason: str = ""


@dataclass(frozen=True)
class PaymentNotification:
    """已经验签并通过基础业务校验的支付或退款回调。"""

    event_type: str
    out_trade_no: str
    transaction_no: str
    amount_minor: int
    success: bool
    channel_status: str
    refund_no: str = ""


class PaymentGateway:
    """支付渠道必须实现下单、退款和回调验签三个能力。"""

    def create_app_payment(
        self,
        *,
        payment_no: str,
        description: str,
        amount_minor: int,
    ) -> PaymentInitiation:
        raise NotImplementedError

    def refund(
        self,
        *,
        payment_no: str,
        refund_no: str,
        amount_minor: int,
    ) -> RefundResult:
        raise NotImplementedError

    def verify_notification(
        self,
        *,
        raw_body: bytes,
        headers: dict[str, str],
        form_data: dict[str, Any],
    ) -> PaymentNotification:
        raise NotImplementedError
