"""内容举报和敏感词 HTTP 接口。"""

from __future__ import annotations

from typing import ClassVar

from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework.authentication import BaseAuthentication
from rest_framework.permissions import BasePermission, IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from backend.accounts.authentication import BearerTokenAuthentication
from backend.adminops.auth import AdminBearerTokenAuthentication, require_admin_permission
from backend.common.errors import ErrorCode
from backend.common.exceptions import ApiError
from backend.moderation.api.serializers import (
    ContentReportCreateRequestSerializer,
    ContentReportListResponseSerializer,
    ContentReportResponseSerializer,
    ContentReportReviewRequestSerializer,
    SensitiveWordListResponseSerializer,
    SensitiveWordRequestSerializer,
    SensitiveWordResponseSerializer,
    SensitiveWordUpdateRequestSerializer,
)
from backend.moderation.services import (
    create_content_report,
    create_sensitive_word,
    delete_sensitive_word,
    list_content_reports,
    list_sensitive_words,
    resolve_content_report,
    update_sensitive_word,
)


def _integer_query(request: Request, name: str, default: int, minimum: int, maximum: int) -> int:
    raw = request.query_params.get(name)
    if raw in {None, ""}:
        return default
    try:
        value = int(raw)
    except ValueError:
        value = default
    return max(minimum, min(value, maximum))


class ContentReportCreateView(APIView):
    """用户提交内容举报。"""

    authentication_classes: ClassVar[list[type[BaseAuthentication]]] = [BearerTokenAuthentication]
    permission_classes: ClassVar[list[type[BasePermission]]] = [IsAuthenticated]

    @extend_schema(
        summary="提交内容举报",
        request=ContentReportCreateRequestSerializer,
        responses={201: ContentReportResponseSerializer},
    )
    def post(self, request: Request) -> Response:
        serializer = ContentReportCreateRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        report = create_content_report(
            user=request.user,
            payload=dict(serializer.validated_data),
        )
        return Response(
            {
                "report_no": str(report.report_no),
                "reporter_public_id": str(report.reporter.public_id),
                "target_type": report.target_type,
                "target_id": report.target_id,
                "reason": report.reason,
                "evidence_urls": report.evidence_urls,
                "status": report.status,
                "resolution": report.resolution,
                "handled_at": report.handled_at,
                "version": report.version,
                "created_at": report.created_at,
                "updated_at": report.updated_at,
            },
            status=201,
        )


class AdminContentReportListView(APIView):
    """管理员举报列表。"""

    authentication_classes: ClassVar[list[type[BaseAuthentication]]] = [
        AdminBearerTokenAuthentication
    ]
    permission_classes: ClassVar[list[type[BasePermission]]] = [IsAuthenticated]

    @extend_schema(
        summary="查看内容举报",
        parameters=[
            OpenApiParameter("status", required=False),
            OpenApiParameter("target_type", required=False),
            OpenApiParameter("page", type=int, required=False),
            OpenApiParameter("page_size", type=int, required=False),
        ],
        responses={200: ContentReportListResponseSerializer},
    )
    def get(self, request: Request) -> Response:
        require_admin_permission(request.user, "admin.report.read")
        return Response(
            list_content_reports(
                status=request.query_params.get("status", ""),
                target_type=request.query_params.get("target_type", ""),
                page=_integer_query(request, "page", 1, 1, 10_000),
                page_size=_integer_query(request, "page_size", 20, 1, 100),
            )
        )


class AdminContentReportReviewView(APIView):
    """管理员处理内容举报。"""

    authentication_classes: ClassVar[list[type[BaseAuthentication]]] = [
        AdminBearerTokenAuthentication
    ]
    permission_classes: ClassVar[list[type[BasePermission]]] = [IsAuthenticated]

    @extend_schema(
        summary="处理内容举报",
        request=ContentReportReviewRequestSerializer,
        responses={200: ContentReportResponseSerializer},
    )
    def post(self, request: Request, report_no: str, action: str) -> Response:
        require_admin_permission(request.user, "admin.report.write")
        serializer = ContentReportReviewRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return Response(
            resolve_content_report(
                operator=request.user,
                report_no=report_no,
                action=action,
                expected_version=serializer.validated_data["expected_version"],
                resolution=serializer.validated_data["resolution"],
            )
        )


class AdminSensitiveWordListView(APIView):
    """管理员敏感词列表和创建。"""

    authentication_classes: ClassVar[list[type[BaseAuthentication]]] = [
        AdminBearerTokenAuthentication
    ]
    permission_classes: ClassVar[list[type[BasePermission]]] = [IsAuthenticated]

    @extend_schema(
        summary="查看敏感词",
        responses={200: SensitiveWordListResponseSerializer},
    )
    def get(self, request: Request) -> Response:
        require_admin_permission(request.user, "admin.moderation.read")
        return Response(
            list_sensitive_words(
                status=request.query_params.get("status", ""),
                page=_integer_query(request, "page", 1, 1, 10_000),
                page_size=_integer_query(request, "page_size", 20, 1, 100),
            )
        )

    @extend_schema(
        summary="创建敏感词",
        request=SensitiveWordRequestSerializer,
        responses={201: SensitiveWordResponseSerializer},
    )
    def post(self, request: Request) -> Response:
        require_admin_permission(request.user, "admin.moderation.write")
        serializer = SensitiveWordRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return Response(
            create_sensitive_word(operator=request.user, payload=dict(serializer.validated_data)),
            status=201,
        )


class AdminSensitiveWordDetailView(APIView):
    """管理员修改或停用敏感词。"""

    authentication_classes: ClassVar[list[type[BaseAuthentication]]] = [
        AdminBearerTokenAuthentication
    ]
    permission_classes: ClassVar[list[type[BasePermission]]] = [IsAuthenticated]

    @extend_schema(
        summary="修改敏感词",
        request=SensitiveWordUpdateRequestSerializer,
        responses={200: SensitiveWordResponseSerializer},
    )
    def patch(self, request: Request, word_id: int) -> Response:
        require_admin_permission(request.user, "admin.moderation.write")
        serializer = SensitiveWordUpdateRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return Response(
            update_sensitive_word(
                operator=request.user,
                word_id=word_id,
                payload=dict(serializer.validated_data),
            )
        )

    @extend_schema(summary="停用敏感词", responses={200: dict})
    def delete(self, request: Request, word_id: int) -> Response:
        require_admin_permission(request.user, "admin.moderation.write")
        expected_version = request.data.get("expected_version")
        if expected_version is None:
            raise ApiError(
                ErrorCode.VALIDATION_ERROR,
                "expected_version 不能为空",
                status_code=400,
            )
        return Response(
            delete_sensitive_word(
                operator=request.user,
                word_id=word_id,
                expected_version=int(expected_version),
            )
        )
