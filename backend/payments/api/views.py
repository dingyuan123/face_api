"""支付单查询和第三方支付回调接口，只负责协议转换与安全响应。"""

from __future__ import annotations

from typing import ClassVar

from django.http import HttpResponse
from drf_spectacular.utils import extend_schema
from rest_framework.authentication import BaseAuthentication
from rest_framework.permissions import AllowAny, BasePermission, IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from backend.accounts.authentication import BearerTokenAuthentication
from backend.common.exceptions import ApiError
from backend.integrations.payments.contracts import PaymentGatewayError
from backend.integrations.payments.factory import get_payment_gateway
from backend.payments.api.serializers import (
    PaymentDetailSerializer,
    PaymentNotifyResponseSerializer,
)
from backend.payments.models import Payment
from backend.payments.services import get_payment, handle_payment_notification, payment_payload


class PaymentDetailView(APIView):
    """当前用户查询订单支付状态和客户端支付参数。"""

    authentication_classes: ClassVar[list[type[BaseAuthentication]]] = [BearerTokenAuthentication]
    permission_classes: ClassVar[list[type[BasePermission]]] = [IsAuthenticated]

    @extend_schema(
        summary="查询支付单",
        responses={200: PaymentDetailSerializer},
    )
    def get(self, request: Request, payment_no: str) -> Response:
        return Response(payment_payload(get_payment(user=request.user, payment_no=payment_no)))


class WeChatPaymentNotifyView(APIView):
    """微信支付 APIv3 异步通知，响应必须使用微信要求的 JSON 格式。"""

    authentication_classes: ClassVar[list[type[BaseAuthentication]]] = []
    permission_classes: ClassVar[list[type[BasePermission]]] = [AllowAny]

    @extend_schema(
        auth=[],
        exclude=True,
        request=None,
        responses={200: PaymentNotifyResponseSerializer},
    )
    def post(self, request: Request) -> HttpResponse:
        return _handle_notification(request, Payment.Method.WECHAT_APP)


class AlipayPaymentNotifyView(APIView):
    """支付宝 App 支付异步通知，验签后以 success 文本确认。"""

    authentication_classes: ClassVar[list[type[BaseAuthentication]]] = []
    permission_classes: ClassVar[list[type[BasePermission]]] = [AllowAny]

    @extend_schema(
        auth=[],
        exclude=True,
        request=None,
        responses={200: PaymentNotifyResponseSerializer},
    )
    def post(self, request: Request) -> HttpResponse:
        return _handle_notification(request, Payment.Method.ALIPAY_APP)


def _handle_notification(request: Request, payment_method: str) -> HttpResponse:
    """验签、校验金额并幂等落账，按渠道返回最小必要响应。"""
    is_wechat = payment_method == Payment.Method.WECHAT_APP
    try:
        notification = get_payment_gateway(payment_method).verify_notification(
            raw_body=request.body,
            headers={key: value for key, value in request.headers.items()},
            form_data=request.data if isinstance(request.data, dict) else {},
        )
        handle_payment_notification(notification=notification)
    except PaymentGatewayError as exc:
        return _notification_error(is_wechat, 400, "FAIL", str(exc))
    except ApiError as exc:
        return _notification_error(is_wechat, 409, "FAIL", exc.message)
    if is_wechat:
        return HttpResponse(
            '{"code":"SUCCESS","message":"成功"}',
            content_type="application/json",
            status=200,
        )
    return HttpResponse("success", content_type="text/plain", status=200)


def _notification_error(
    is_wechat: bool,
    status: int,
    code: str,
    message: str,
) -> HttpResponse:
    """返回渠道要求的简短失败结果，不包含敏感通知内容。"""
    if is_wechat:
        import json

        return HttpResponse(
            json.dumps({"code": code, "message": message[:120]}, ensure_ascii=False),
            content_type="application/json",
            status=status,
        )
    return HttpResponse("fail", content_type="text/plain", status=status)
