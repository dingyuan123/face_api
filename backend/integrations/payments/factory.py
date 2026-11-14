"""支付渠道工厂，业务层按配置选择模拟、微信或支付宝适配器。"""

from __future__ import annotations

from django.conf import settings

from backend.common.errors import ERROR_MESSAGES, ErrorCode
from backend.common.exceptions import ApiError
from backend.integrations.payments.contracts import PaymentGateway
from backend.integrations.payments.mock import MockExternalPaymentGateway
from backend.payments.models import Payment


def get_payment_gateway(payment_method: str) -> PaymentGateway:
    """根据支付方式返回适配器，生产真实渠道仅在配置完整时启用。"""
    if payment_method == Payment.Method.BALANCE:
        raise ApiError(
            ErrorCode.PAYMENT_INVALID,
            ERROR_MESSAGES[ErrorCode.PAYMENT_INVALID],
            status_code=400,
            details={"payment_method": "钱包余额支付不使用外部渠道"},
        )
    if payment_method == Payment.Method.WECHAT_APP:
        if settings.PAYMENT_GATEWAY_MODE == "MOCK":
            return MockExternalPaymentGateway(channel="WECHAT")
        from backend.integrations.payments.wechat import WeChatPayGateway

        return WeChatPayGateway()
    if payment_method == Payment.Method.ALIPAY_APP:
        if settings.PAYMENT_GATEWAY_MODE == "MOCK":
            return MockExternalPaymentGateway(channel="ALIPAY")
        from backend.integrations.payments.alipay import AlipayGateway

        return AlipayGateway()
    raise ApiError(
        ErrorCode.PAYMENT_INVALID,
        ERROR_MESSAGES[ErrorCode.PAYMENT_INVALID],
        status_code=400,
        details={"payment_method": "不支持的支付方式"},
    )
