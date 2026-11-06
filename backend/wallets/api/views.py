from __future__ import annotations

from typing import ClassVar

from drf_spectacular.utils import extend_schema
from rest_framework.authentication import BaseAuthentication
from rest_framework.permissions import BasePermission, IsAdminUser, IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from backend.accounts.authentication import BearerTokenAuthentication
from backend.accounts.models import User
from backend.common.errors import ERROR_MESSAGES, ErrorCode
from backend.common.exceptions import ApiError
from backend.wallets.api.serializers import (
    WalletResponseSerializer,
    WalletTopUpRequestSerializer,
    WalletTopUpResponseSerializer,
    WalletTransactionResponseSerializer,
)
from backend.wallets.models import WalletTransaction
from backend.wallets.services import (
    admin_top_up_wallet,
    get_or_create_wallet,
    wallet_payload,
    wallet_transaction_payload,
)


class WalletView(APIView):
    """当前用户钱包余额查询。"""

    authentication_classes: ClassVar[list[type[BaseAuthentication]]] = [BearerTokenAuthentication]
    permission_classes: ClassVar[list[type[BasePermission]]] = [IsAuthenticated]

    @extend_schema(summary="查询钱包余额", responses={200: WalletResponseSerializer})
    def get(self, request: Request) -> Response:
        return Response(wallet_payload(get_or_create_wallet(request.user)))


class WalletTransactionsView(APIView):
    """当前用户钱包流水查询。"""

    authentication_classes: ClassVar[list[type[BaseAuthentication]]] = [BearerTokenAuthentication]
    permission_classes: ClassVar[list[type[BasePermission]]] = [IsAuthenticated]

    @extend_schema(
        summary="查询钱包流水",
        responses={200: WalletTransactionResponseSerializer(many=True)},
    )
    def get(self, request: Request) -> Response:
        page = int(request.query_params.get("page", 1))
        page_size = int(request.query_params.get("page_size", 20))
        queryset = WalletTransaction.objects.filter(user=request.user).order_by(
            "-created_at", "-id"
        )
        start = max(0, (page - 1) * page_size)
        return Response(
            {
                "items": [
                    wallet_transaction_payload(item) for item in queryset[start : start + page_size]
                ],
                "total": queryset.count(),
                "page": page,
                "page_size": page_size,
            }
        )


class AdminWalletTopUpView(APIView):
    """管理员写入开发测试余额。"""

    authentication_classes: ClassVar[list[type[BaseAuthentication]]] = [BearerTokenAuthentication]
    permission_classes: ClassVar[list[type[BasePermission]]] = [IsAdminUser]

    @extend_schema(
        summary="为指定用户创建测试余额",
        request=WalletTopUpRequestSerializer,
        responses={201: WalletTopUpResponseSerializer},
    )
    def post(self, request: Request) -> Response:
        serializer = WalletTopUpRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        target_user = User.objects.filter(
            public_id=serializer.validated_data["target_user_public_id"]
        ).first()
        if target_user is None:
            raise ApiError(
                ErrorCode.WALLET_NOT_FOUND,
                ERROR_MESSAGES[ErrorCode.WALLET_NOT_FOUND],
                status_code=404,
            )
        if serializer.validated_data.get("currency", "CNY") != "CNY":
            raise ApiError(
                ErrorCode.WALLET_TRANSACTION_CONFLICT,
                ERROR_MESSAGES[ErrorCode.WALLET_TRANSACTION_CONFLICT],
                status_code=400,
                details={"currency": "当前仅支持 CNY"},
            )
        result = admin_top_up_wallet(
            target_user=target_user,
            created_by=request.user,
            amount_minor=serializer.validated_data["amount_minor"],
            reason=serializer.validated_data.get("reason", ""),
            idempotency_key=request.headers.get("Idempotency-Key"),
        )
        return Response(result, status=201)
