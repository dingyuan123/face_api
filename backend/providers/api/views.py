from __future__ import annotations

from typing import ClassVar

from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework.authentication import BaseAuthentication
from rest_framework.permissions import BasePermission, IsAdminUser, IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from backend.accounts.authentication import BearerTokenAuthentication
from backend.common.errors import ERROR_MESSAGES, ErrorCode
from backend.common.exceptions import ApiError
from backend.common.pagination import ApiCursorPagination
from backend.providers.api.serializers import (
    ProviderApplicationInputSerializer,
    ProviderApplicationResponseSerializer,
    ProviderApplicationUpdateRequestSerializer,
    ProviderReviewRequestSerializer,
)
from backend.providers.models import ProviderApplication
from backend.providers.services import (
    application_payload,
    get_application_for_user,
    review_application,
    submit_provider_application,
    update_application,
)


def _idempotency_header(required: bool = True) -> OpenApiParameter:
    return OpenApiParameter(
        "Idempotency-Key",
        location=OpenApiParameter.HEADER,
        type=str,
        required=required,
        description="创建服务者申请时用于重复请求去重。",
    )


class ProviderApplicationCreateView(APIView):
    authentication_classes: ClassVar[list[type[BaseAuthentication]]] = [BearerTokenAuthentication]
    permission_classes: ClassVar[list[type[BasePermission]]] = [IsAuthenticated]

    @extend_schema(
        summary="提交服务陪伴者入驻申请",
        description=(
            "同一用户只允许一个进行中的申请; 实名和人脸当前由开发 Mock 返回 MOCK_PASSED, "
            "接口不返回真实姓名或身份证号。"
        ),
        request=ProviderApplicationInputSerializer,
        responses={
            200: ProviderApplicationResponseSerializer,
            201: ProviderApplicationResponseSerializer,
        },
        parameters=[_idempotency_header()],
    )
    def post(self, request: Request) -> Response:
        serializer = ProviderApplicationInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        result = submit_provider_application(
            user=request.user,
            payload=serializer.validated_data,
            idempotency_key=request.headers.get("Idempotency-Key"),
        )
        return Response(
            application_payload(result.application, request.user, request),
            status=200 if result.reused else 201,
        )


class MyProviderApplicationView(APIView):
    authentication_classes: ClassVar[list[type[BaseAuthentication]]] = [BearerTokenAuthentication]
    permission_classes: ClassVar[list[type[BasePermission]]] = [IsAuthenticated]

    @extend_schema(
        summary="查询当前用户的服务者申请",
        responses={200: ProviderApplicationResponseSerializer},
    )
    def get(self, request: Request) -> Response:
        return Response(
            application_payload(
                get_application_for_user(request.user),
                request.user,
                request,
            )
        )

    @extend_schema(
        summary="修改被拒绝或已取消申请并重新提交",
        description="必须携带当前申请 version 作为 expected_version, 防止覆盖他人或并发修改。",
        request=ProviderApplicationUpdateRequestSerializer,
        responses={200: ProviderApplicationResponseSerializer},
    )
    def patch(self, request: Request) -> Response:
        serializer = ProviderApplicationUpdateRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        payload = dict(serializer.validated_data)
        expected_version = payload.pop("expected_version")
        result = update_application(
            user=request.user,
            payload=payload,
            expected_version=expected_version,
        )
        return Response(application_payload(result.application, request.user, request))


class ProviderApplicationCursorPagination(ApiCursorPagination):
    ordering = ("-submitted_at", "-id")


class AdminProviderApplicationListView(APIView):
    authentication_classes: ClassVar[list[type[BaseAuthentication]]] = [BearerTokenAuthentication]
    permission_classes: ClassVar[list[type[BasePermission]]] = [IsAdminUser]
    pagination_class = ProviderApplicationCursorPagination

    @extend_schema(
        summary="查看服务者申请列表",
        responses={200: ProviderApplicationResponseSerializer(many=True)},
    )
    def get(self, request: Request) -> Response:
        queryset = (
            ProviderApplication.objects.select_related("user")
            .order_by("-submitted_at", "-id")
            .all()
        )
        paginator = self.pagination_class()
        page = paginator.paginate_queryset(queryset, request, view=self)
        data = [application_payload(item, item.user, request) for item in page or []]
        return paginator.get_paginated_response(data)


class AdminProviderApplicationDetailView(APIView):
    authentication_classes: ClassVar[list[type[BaseAuthentication]]] = [BearerTokenAuthentication]
    permission_classes: ClassVar[list[type[BasePermission]]] = [IsAdminUser]

    @extend_schema(
        summary="查看单个服务者申请",
        responses={200: ProviderApplicationResponseSerializer},
    )
    def get(self, request: Request, application_no: str) -> Response:
        application = (
            ProviderApplication.objects.select_related("user")
            .filter(application_no=application_no)
            .first()
        )
        if application is None:
            raise ApiError(
                ErrorCode.PROVIDER_APPLICATION_NOT_FOUND,
                ERROR_MESSAGES[ErrorCode.PROVIDER_APPLICATION_NOT_FOUND],
                status_code=404,
            )
        return Response(application_payload(application, application.user, request))


class AdminProviderApplicationApproveView(APIView):
    authentication_classes: ClassVar[list[type[BaseAuthentication]]] = [BearerTokenAuthentication]
    permission_classes: ClassVar[list[type[BasePermission]]] = [IsAdminUser]

    @extend_schema(
        summary="审核通过服务者申请",
        request=ProviderReviewRequestSerializer,
        responses={200: ProviderApplicationResponseSerializer},
    )
    def post(self, request: Request, application_no: str) -> Response:
        serializer = ProviderReviewRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        application = review_application(
            application_no=application_no,
            approve=True,
            reviewer=request.user,
            expected_version=serializer.validated_data["expected_version"],
        )
        return Response(application_payload(application, application.user, request))


class AdminProviderApplicationRejectView(APIView):
    authentication_classes: ClassVar[list[type[BaseAuthentication]]] = [BearerTokenAuthentication]
    permission_classes: ClassVar[list[type[BasePermission]]] = [IsAdminUser]

    @extend_schema(
        summary="拒绝服务者申请",
        request=ProviderReviewRequestSerializer,
        responses={200: ProviderApplicationResponseSerializer},
    )
    def post(self, request: Request, application_no: str) -> Response:
        serializer = ProviderReviewRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        application = review_application(
            application_no=application_no,
            approve=False,
            reviewer=request.user,
            reason=serializer.validated_data.get("reason", ""),
            expected_version=serializer.validated_data["expected_version"],
        )
        return Response(application_payload(application, application.user, request))
