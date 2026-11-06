from __future__ import annotations

from typing import ClassVar

from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework.authentication import BaseAuthentication
from rest_framework.permissions import AllowAny, BasePermission, IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from backend.accounts.api.serializers import (
    DevPasswordLoginRequestSerializer,
    InitialRoleRequestSerializer,
    InitialRoleResponseSerializer,
    LoginRequestSerializer,
    LogoutResponseSerializer,
    RefreshRequestSerializer,
    SessionResponseSerializer,
    SmsCodeRequestSerializer,
    SmsCodeResponseSerializer,
    TokenPairResponseSerializer,
)
from backend.accounts.authentication import BearerTokenAuthentication
from backend.accounts.services import (
    login_with_code,
    login_with_password,
    logout_session,
    refresh_access_token,
    select_initial_role,
    send_sms_code,
    session_payload,
)
from backend.providers.services import current_application_payload


def _idempotency_header() -> OpenApiParameter:
    return OpenApiParameter(
        "Idempotency-Key",
        location=OpenApiParameter.HEADER,
        type=str,
        required=False,
        description="同一请求重复提交时使用的幂等键; 发送验证码和登录接口支持。",
    )


class SmsCodeView(APIView):
    authentication_classes: ClassVar[list[type[BaseAuthentication]]] = []
    permission_classes: ClassVar[list[type[BasePermission]]] = [AllowAny]

    @extend_schema(
        auth=[],
        summary="发送手机号登录验证码",
        description="当前未接入真实短信服务, 仅在开发/测试 mock 模式返回 debug_code。",
        request=SmsCodeRequestSerializer,
        responses={200: SmsCodeResponseSerializer},
        parameters=[_idempotency_header()],
    )
    def post(self, request: Request) -> Response:
        serializer = SmsCodeRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        result = send_sms_code(
            phone_value=serializer.validated_data["phone"],
            idempotency_key=request.headers.get("Idempotency-Key"),
        )
        return Response(
            {
                "request_id": result.request_id,
                "expires_in": result.expires_in,
                "debug_code": result.debug_code,
                "reused": result.reused,
            }
        )


class LoginView(APIView):
    authentication_classes: ClassVar[list[type[BaseAuthentication]]] = []
    permission_classes: ClassVar[list[type[BasePermission]]] = [AllowAny]

    @extend_schema(
        auth=[],
        summary="手机号验证码登录或自动注册",
        description="验证码校验成功后创建用户和认证凭据; 客户端不能提交用户状态或用户 ID。",
        request=LoginRequestSerializer,
        responses={200: TokenPairResponseSerializer},
        parameters=[_idempotency_header()],
    )
    def post(self, request: Request) -> Response:
        serializer = LoginRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        result = login_with_code(
            phone_value=serializer.validated_data["phone"],
            code_value=serializer.validated_data["code"],
            idempotency_key=request.headers.get("Idempotency-Key"),
        )
        return Response(_token_payload(result))


class DevPasswordLoginView(APIView):
    """开发测试账号密码登录接口，成功后返回标准 Bearer 令牌。"""

    authentication_classes: ClassVar[list[type[BaseAuthentication]]] = []
    permission_classes: ClassVar[list[type[BasePermission]]] = [AllowAny]

    @extend_schema(
        auth=[],
        summary="开发测试账号密码登录",
        description=(
            "仅供开发测试。使用已经设置密码的手机号账号登录，成功返回访问和刷新令牌；"
            "生产环境强制禁用。将 access_token 填入 Swagger Authorize 后调用其他接口。"
        ),
        request=DevPasswordLoginRequestSerializer,
        responses={200: TokenPairResponseSerializer},
        parameters=[_idempotency_header()],
    )
    def post(self, request: Request) -> Response:
        serializer = DevPasswordLoginRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        result = login_with_password(
            phone_value=serializer.validated_data["phone"],
            password_value=serializer.validated_data["password"],
            idempotency_key=request.headers.get("Idempotency-Key"),
        )
        return Response(_token_payload(result))


class RefreshView(APIView):
    authentication_classes: ClassVar[list[type[BaseAuthentication]]] = []
    permission_classes: ClassVar[list[type[BasePermission]]] = [AllowAny]

    @extend_schema(
        auth=[],
        summary="轮换访问令牌和刷新令牌",
        request=RefreshRequestSerializer,
        responses={200: TokenPairResponseSerializer},
    )
    def post(self, request: Request) -> Response:
        serializer = RefreshRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        result = refresh_access_token(
            refresh_token_value=serializer.validated_data["refresh_token"]
        )
        return Response(_token_payload(result))


class LogoutView(APIView):
    authentication_classes: ClassVar[list[type[BaseAuthentication]]] = [BearerTokenAuthentication]
    permission_classes: ClassVar[list[type[BasePermission]]] = [IsAuthenticated]

    @extend_schema(
        summary="退出当前登录会话",
        request=None,
        description=(
            "撤销当前会话的访问/刷新令牌; 不影响其他设备会话。"
            "令牌撤销后重复请求会返回 401, 但不会产生额外副作用。"
        ),
        responses={200: LogoutResponseSerializer},
    )
    def post(self, request: Request) -> Response:
        logout_session(user=request.user, access_token=request.auth)
        return Response({"logged_out": True})


class MeView(APIView):
    authentication_classes: ClassVar[list[type[BaseAuthentication]]] = [BearerTokenAuthentication]
    permission_classes: ClassVar[list[type[BasePermission]]] = [IsAuthenticated]

    @extend_schema(
        summary="获取当前登录会话",
        responses={200: SessionResponseSerializer},
    )
    def get(self, request: Request) -> Response:
        payload = session_payload(request.user)
        payload["provider_application"] = current_application_payload(request.user, request)
        return Response(payload)


class InitialRoleView(APIView):
    authentication_classes: ClassVar[list[type[BaseAuthentication]]] = [BearerTokenAuthentication]
    permission_classes: ClassVar[list[type[BasePermission]]] = [IsAuthenticated]

    @extend_schema(
        summary="选择首次登录身份",
        description="同一身份重复提交幂等成功; 已选择后不能通过该接口切换身份。",
        request=InitialRoleRequestSerializer,
        responses={200: InitialRoleResponseSerializer},
    )
    def post(self, request: Request) -> Response:
        serializer = InitialRoleRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return Response(select_initial_role(request.user, serializer.validated_data["role"]))


def _token_payload(result) -> dict[str, object]:
    return {
        "token_type": "Bearer",
        "access_token": result.access_token,
        "refresh_token": result.refresh_token,
        "expires_in": result.expires_in,
        "refresh_expires_in": result.refresh_expires_in,
        "user_public_id": result.user_public_id,
        "is_new_user": result.is_new_user,
        "requires_identity_selection": result.requires_identity_selection,
    }
