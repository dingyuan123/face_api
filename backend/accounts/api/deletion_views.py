"""账号注销条件检查、短信确认和不可恢复注销接口。"""

from __future__ import annotations

from typing import ClassVar

from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework.authentication import BaseAuthentication
from rest_framework.permissions import BasePermission, IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from backend.accounts.api.deletion_serializers import (
    AccountDeletionCheckResponseSerializer,
    AccountDeletionConfirmRequestSerializer,
    AccountDeletionResponseSerializer,
    AccountDeletionSmsResponseSerializer,
)
from backend.accounts.authentication import BearerTokenAuthentication
from backend.accounts.deletion_services import (
    account_deletion_check,
    delete_account,
    send_account_deletion_sms,
)


class AccountDeletionCheckView(APIView):
    """查询当前账号是否满足注销条件。"""

    authentication_classes: ClassVar[list[type[BaseAuthentication]]] = [BearerTokenAuthentication]
    permission_classes: ClassVar[list[type[BasePermission]]] = [IsAuthenticated]

    @extend_schema(
        auth=[{"BearerTokenAuth": []}],
        summary="检查账号注销条件",
        description=(
            "固定返回 orders、wallet、services、security 四项条件；"
            "can_delete 仅在四项全部通过时为 true。"
        ),
        responses={200: AccountDeletionCheckResponseSerializer},
    )
    def get(self, request: Request) -> Response:
        return Response(account_deletion_check(user=request.user))


class AccountDeletionSmsView(APIView):
    """向绑定手机号发送账号注销确认验证码。"""

    authentication_classes: ClassVar[list[type[BaseAuthentication]]] = [BearerTokenAuthentication]
    permission_classes: ClassVar[list[type[BasePermission]]] = [IsAuthenticated]

    @extend_schema(
        auth=[{"BearerTokenAuth": []}],
        summary="发送账号注销验证码",
        description=(
            "验证码只发送到当前绑定手机号；60 秒内重复发送返回业务错误，默认有效 5 分钟。"
        ),
        request=OpenApiTypes.NONE,
        responses={200: AccountDeletionSmsResponseSerializer},
        parameters=[
            OpenApiParameter(
                "Idempotency-Key",
                location=OpenApiParameter.HEADER,
                type=str,
                required=False,
                description="重复发送同一验证码时使用的幂等键",
            )
        ],
    )
    def post(self, request: Request) -> Response:
        return Response(
            send_account_deletion_sms(
                user=request.user,
                idempotency_key=request.headers.get("Idempotency-Key"),
            )
        )


class AccountDeletionView(APIView):
    """验证短信并执行不可恢复的账号注销。"""

    authentication_classes: ClassVar[list[type[BaseAuthentication]]] = [BearerTokenAuthentication]
    permission_classes: ClassVar[list[type[BasePermission]]] = [IsAuthenticated]

    @extend_schema(
        auth=[{"BearerTokenAuth": []}],
        summary="确认注销账号",
        description=(
            "校验验证码和四项条件后清理个人资料、动态、收藏、关注及登录绑定；"
            "交易、支付、退款、安全、聊天和审计记录依法保留或匿名化。"
        ),
        request=AccountDeletionConfirmRequestSerializer,
        responses={200: AccountDeletionResponseSerializer},
    )
    def post(self, request: Request) -> Response:
        serializer = AccountDeletionConfirmRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return Response(
            delete_account(
                user=request.user,
                code=serializer.validated_data["code"],
                confirm=serializer.validated_data["confirm"],
            )
        )
