"""普通用户实名认证提交和管理员人工审核接口。"""

from __future__ import annotations

from typing import ClassVar

from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework.authentication import BaseAuthentication
from rest_framework.permissions import BasePermission, IsAdminUser, IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from backend.accounts.authentication import BearerTokenAuthentication
from backend.common.errors import ErrorCode
from backend.common.exceptions import ApiError
from backend.identity.api.serializers import (
    IdentityReviewRequestSerializer,
    IdentityVerificationResponseSerializer,
    RealNameVerificationRequestSerializer,
)
from backend.identity.models import IdentityVerification
from backend.identity.services import (
    identity_verification_payload,
    review_real_name_verification,
    submit_real_name_verification,
)


def _integer_query(request: Request, name: str, default: int, minimum: int, maximum: int) -> int:
    """读取并限制分页参数。"""
    raw = request.query_params.get(name)
    if raw in {None, ""}:
        return default
    try:
        value = int(raw)
    except ValueError:
        value = default
    return max(minimum, min(value, maximum))


class MyRealNameVerificationView(APIView):
    """查询当前用户实名认证状态。"""

    authentication_classes: ClassVar[list[type[BaseAuthentication]]] = [BearerTokenAuthentication]
    permission_classes: ClassVar[list[type[BasePermission]]] = [IsAuthenticated]

    @extend_schema(
        summary="查询我的实名认证",
        responses={200: IdentityVerificationResponseSerializer},
    )
    def get(self, request: Request) -> Response:
        verification = IdentityVerification.objects.filter(
            user=request.user,
            verification_type=IdentityVerification.Type.REAL_NAME,
        ).first()
        return Response(
            identity_verification_payload(
                verification,
                user=request.user,
                request=request._request,
            )
        )


class RealNameVerificationSubmitView(APIView):
    """提交或重新提交普通用户实名资料，进入人工审核。"""

    authentication_classes: ClassVar[list[type[BaseAuthentication]]] = [BearerTokenAuthentication]
    permission_classes: ClassVar[list[type[BasePermission]]] = [IsAuthenticated]

    @extend_schema(
        summary="提交实名认证资料",
        description="不执行人脸认证；姓名、身份证号和照片进入人工审核。",
        request=RealNameVerificationRequestSerializer,
        responses={201: IdentityVerificationResponseSerializer},
    )
    def post(self, request: Request) -> Response:
        serializer = RealNameVerificationRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        payload = dict(serializer.validated_data)
        expected_version = payload.pop("expected_version", 0)
        verification = submit_real_name_verification(
            user=request.user,
            payload=payload,
            expected_version=expected_version,
            idempotency_key=request.headers.get("Idempotency-Key"),
        )
        return Response(
            identity_verification_payload(
                verification,
                user=request.user,
                request=request._request,
            ),
            status=201,
        )


class AdminIdentityVerificationListView(APIView):
    """管理员分页查看实名认证记录。"""

    authentication_classes: ClassVar[list[type[BaseAuthentication]]] = [BearerTokenAuthentication]
    permission_classes: ClassVar[list[type[BasePermission]]] = [IsAdminUser]

    @extend_schema(
        summary="查看实名认证列表",
        parameters=[
            OpenApiParameter("status", required=False, description="认证状态筛选"),
            OpenApiParameter("page", type=int, required=False),
            OpenApiParameter("page_size", type=int, required=False),
        ],
        responses={200: IdentityVerificationResponseSerializer(many=True)},
    )
    def get(self, request: Request) -> Response:
        queryset = IdentityVerification.objects.select_related("user").filter(
            verification_type=IdentityVerification.Type.REAL_NAME
        )
        status = request.query_params.get("status")
        if status:
            queryset = queryset.filter(status=status)
        total = queryset.count()
        page = _integer_query(request, "page", 1, 1, 10_000)
        page_size = _integer_query(request, "page_size", 20, 1, 100)
        items = queryset.order_by("-submitted_at", "-id")[(page - 1) * page_size : page * page_size]
        return Response(
            {
                "items": [
                    identity_verification_payload(
                        item,
                        user=item.user,
                        request=request._request,
                    )
                    for item in items
                ],
                "total": total,
                "page": page,
                "page_size": page_size,
            }
        )


class AdminIdentityVerificationReviewView(APIView):
    """管理员通过或拒绝实名认证。"""

    authentication_classes: ClassVar[list[type[BaseAuthentication]]] = [BearerTokenAuthentication]
    permission_classes: ClassVar[list[type[BasePermission]]] = [IsAdminUser]

    @extend_schema(
        summary="人工审核实名认证",
        request=IdentityReviewRequestSerializer,
        responses={200: IdentityVerificationResponseSerializer},
    )
    def post(self, request: Request, verification_no: str, action: str) -> Response:
        if action not in {"approve", "reject"}:
            raise ApiError(
                ErrorCode.IDENTITY_VERIFICATION_INVALID,
                "审核动作不存在",
                status_code=400,
            )
        serializer = IdentityReviewRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        verification = review_real_name_verification(
            verification_no=verification_no,
            approve=action == "approve",
            reason=serializer.validated_data.get("reason", ""),
            expected_version=serializer.validated_data["expected_version"],
            reviewer=request.user,
        )
        return Response(
            identity_verification_payload(
                verification,
                user=verification.user,
                request=request._request,
            )
        )
