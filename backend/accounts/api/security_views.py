"""账号密码设置、找回密码和更换手机号接口。"""

from __future__ import annotations

from typing import ClassVar

from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework.authentication import BaseAuthentication
from rest_framework.permissions import AllowAny, BasePermission, IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from backend.accounts.api.security_serializers import (
    AccountSecurityResponseSerializer,
    PasswordChangeRequestSerializer,
    PasswordChangeResponseSerializer,
    PasswordForgotSmsRequestSerializer,
    PasswordResetRequestSerializer,
    PasswordResetResponseSerializer,
    PhoneChangeConfirmRequestSerializer,
    PhoneChangeConfirmResponseSerializer,
    PhoneChangeRequestSerializer,
    PhoneChangeResponseSerializer,
    SecuritySmsResponseSerializer,
)
from backend.accounts.authentication import BearerTokenAuthentication
from backend.accounts.security_services import (
    account_security_payload,
    confirm_phone_change,
    request_phone_change,
    reset_password,
    send_password_change_sms,
    send_password_reset_sms,
    set_or_change_password,
)


def _idempotency_header() -> OpenApiParameter:
    """返回统一的可选幂等请求头。"""
    return OpenApiParameter(
        "Idempotency-Key",
        location=OpenApiParameter.HEADER,
        type=str,
        required=False,
        description="重复安全写请求使用的幂等键",
    )


class AccountSecurityView(APIView):
    """查询当前账号密码、登录方式和安全操作能力。"""

    authentication_classes: ClassVar[list[type[BaseAuthentication]]] = [BearerTokenAuthentication]
    permission_classes: ClassVar[list[type[BasePermission]]] = [IsAuthenticated]

    @extend_schema(
        auth=[{"BearerTokenAuth": []}],
        summary="查看账号安全信息",
        responses={200: AccountSecurityResponseSerializer},
    )
    def get(self, request: Request) -> Response:
        return Response(account_security_payload(request.user))


class PasswordChangeSmsView(APIView):
    """向绑定手机号发送设置或修改密码验证码。"""

    authentication_classes: ClassVar[list[type[BaseAuthentication]]] = [BearerTokenAuthentication]
    permission_classes: ClassVar[list[type[BasePermission]]] = [IsAuthenticated]

    @extend_schema(
        auth=[{"BearerTokenAuth": []}],
        summary="发送设置或修改密码验证码",
        request=OpenApiTypes.NONE,
        responses={200: SecuritySmsResponseSerializer},
        parameters=[_idempotency_header()],
    )
    def post(self, request: Request) -> Response:
        return Response(
            send_password_change_sms(
                user=request.user,
                idempotency_key=request.headers.get("Idempotency-Key"),
            )
        )


class PasswordChangeView(APIView):
    """设置首次密码或修改当前用户密码。"""

    authentication_classes: ClassVar[list[type[BaseAuthentication]]] = [BearerTokenAuthentication]
    permission_classes: ClassVar[list[type[BasePermission]]] = [IsAuthenticated]

    @extend_schema(
        auth=[{"BearerTokenAuth": []}],
        summary="设置或修改登录密码",
        description=(
            "首次设置密码使用短信验证码；修改已有密码还必须提供当前密码。"
            "成功后保留当前设备并撤销其他设备会话。"
        ),
        request=PasswordChangeRequestSerializer,
        responses={200: PasswordChangeResponseSerializer},
        parameters=[_idempotency_header()],
    )
    def post(self, request: Request) -> Response:
        serializer = PasswordChangeRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return Response(
            set_or_change_password(
                user=request.user,
                new_password=serializer.validated_data["new_password"],
                current_password=serializer.validated_data.get("current_password", ""),
                code=serializer.validated_data["code"],
                idempotency_key=request.headers.get("Idempotency-Key", ""),
                current_session_id=getattr(request.auth, "session_id", None),
            )
        )


class PasswordForgotSmsView(APIView):
    """向已绑定手机号发送忘记密码验证码。"""

    authentication_classes: ClassVar[list[type[BaseAuthentication]]] = []
    permission_classes: ClassVar[list[type[BasePermission]]] = [AllowAny]

    @extend_schema(
        auth=[],
        summary="发送忘记密码验证码",
        request=PasswordForgotSmsRequestSerializer,
        responses={200: SecuritySmsResponseSerializer},
        parameters=[_idempotency_header()],
    )
    def post(self, request: Request) -> Response:
        serializer = PasswordForgotSmsRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return Response(
            send_password_reset_sms(
                phone_value=serializer.validated_data["phone"],
                idempotency_key=request.headers.get("Idempotency-Key"),
            )
        )


class PasswordResetView(APIView):
    """使用手机号验证码重置忘记的登录密码。"""

    authentication_classes: ClassVar[list[type[BaseAuthentication]]] = []
    permission_classes: ClassVar[list[type[BasePermission]]] = [AllowAny]

    @extend_schema(
        auth=[],
        summary="重置忘记的登录密码",
        description="成功后撤销账号全部设备登录令牌，用户需要重新登录。",
        request=PasswordResetRequestSerializer,
        responses={200: PasswordResetResponseSerializer},
        parameters=[_idempotency_header()],
    )
    def post(self, request: Request) -> Response:
        serializer = PasswordResetRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return Response(
            reset_password(
                phone_value=serializer.validated_data["phone"],
                code=serializer.validated_data["code"],
                new_password=serializer.validated_data["new_password"],
                idempotency_key=request.headers.get("Idempotency-Key", ""),
            )
        )


class PhoneChangeRequestView(APIView):
    """发起更换绑定手机号和双验证码请求。"""

    authentication_classes: ClassVar[list[type[BaseAuthentication]]] = [BearerTokenAuthentication]
    permission_classes: ClassVar[list[type[BasePermission]]] = [IsAuthenticated]

    @extend_schema(
        auth=[{"BearerTokenAuth": []}],
        summary="申请更换绑定手机号",
        description=(
            "已有手机号使用新旧手机号双验证码；无手机号账号使用当前密码加新手机号验证码。"
        ),
        request=PhoneChangeRequestSerializer,
        responses={200: PhoneChangeResponseSerializer},
        parameters=[_idempotency_header()],
    )
    def post(self, request: Request) -> Response:
        serializer = PhoneChangeRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return Response(
            request_phone_change(
                user=request.user,
                new_phone_value=serializer.validated_data["new_phone"],
                current_password=serializer.validated_data.get(
                    "current_password",
                    "",
                ),
                idempotency_key=request.headers.get("Idempotency-Key", ""),
            )
        )


class PhoneChangeConfirmView(APIView):
    """确认验证码并完成绑定手机号更换。"""

    authentication_classes: ClassVar[list[type[BaseAuthentication]]] = [BearerTokenAuthentication]
    permission_classes: ClassVar[list[type[BasePermission]]] = [IsAuthenticated]

    @extend_schema(
        auth=[{"BearerTokenAuth": []}],
        summary="确认更换绑定手机号",
        description="成功后保留当前设备并撤销其他设备登录令牌。",
        request=PhoneChangeConfirmRequestSerializer,
        responses={200: PhoneChangeConfirmResponseSerializer},
    )
    def post(self, request: Request) -> Response:
        serializer = PhoneChangeConfirmRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return Response(
            confirm_phone_change(
                user=request.user,
                request_no=str(serializer.validated_data["request_no"]),
                old_code=serializer.validated_data.get("old_code", ""),
                new_code=serializer.validated_data["new_code"],
                current_session_id=getattr(request.auth, "session_id", None),
            )
        )
