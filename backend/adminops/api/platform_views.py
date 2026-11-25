"""管理后台平台分析、系统设置和公告接口。"""

from __future__ import annotations

from typing import ClassVar

from django.conf import settings
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework.authentication import BaseAuthentication
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.permissions import BasePermission, IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from backend.adminops.api.serializers import (
    AdminAnalyticsBreakdownResponseSerializer,
    AdminAnalyticsOverviewResponseSerializer,
    AdminAnalyticsTrendsResponseSerializer,
    AdminAnnouncementListResponseSerializer,
    AdminAnnouncementRequestSerializer,
    AdminAnnouncementResponseSerializer,
    AdminCommissionRuleResponseSerializer,
    AdminCommissionRuleUpdateRequestSerializer,
    AdminCompanyLicenseUploadRequestSerializer,
    AdminCompanyProfileResponseSerializer,
    AdminCompanyProfileUpdateRequestSerializer,
    AdminConfigOptionListResponseSerializer,
    AdminConfigOptionRequestSerializer,
    AdminConfigOptionResponseSerializer,
    AdminSystemSettingResponseSerializer,
    AdminSystemSettingUpdateRequestSerializer,
)
from backend.adminops.auth import AdminBearerTokenAuthentication, require_admin_permission
from backend.adminops.company_services import (
    get_company_profile,
    update_company_profile,
    upload_company_business_license,
)
from backend.adminops.platform_services import (
    create_announcement,
    create_city_setting,
    create_service_category_setting,
    get_basic_settings,
    get_commission_rules,
    list_announcements,
    list_city_settings,
    list_service_category_settings,
    platform_analytics_breakdown,
    platform_analytics_overview,
    platform_analytics_trends,
    update_announcement,
    update_basic_settings,
    update_city_setting,
    update_commission_rules,
    update_service_category_setting,
)
from backend.common.errors import ERROR_MESSAGES, ErrorCode
from backend.common.exceptions import ApiError
from backend.media.api.serializers import MediaAssetResponseSerializer
from backend.media.services import media_payload


def _integer_query(request: Request, name: str, default: int, minimum: int, maximum: int) -> int:
    raw = request.query_params.get(name)
    if raw in {None, ""}:
        return default
    try:
        value = int(raw)
    except ValueError:
        value = default
    return max(minimum, min(value, maximum))


class AdminAnalyticsOverviewView(APIView):
    authentication_classes: ClassVar[list[type[BaseAuthentication]]] = [
        AdminBearerTokenAuthentication
    ]
    permission_classes: ClassVar[list[type[BasePermission]]] = [IsAuthenticated]

    @extend_schema(
        summary="平台数据概览", responses={200: AdminAnalyticsOverviewResponseSerializer}
    )
    def get(self, request: Request) -> Response:
        require_admin_permission(request.user, "admin.analytics.read")
        return Response(platform_analytics_overview())


class AdminAnalyticsTrendsView(APIView):
    authentication_classes: ClassVar[list[type[BaseAuthentication]]] = [
        AdminBearerTokenAuthentication
    ]
    permission_classes: ClassVar[list[type[BasePermission]]] = [IsAuthenticated]

    @extend_schema(
        summary="平台数据趋势",
        parameters=[OpenApiParameter("range", required=False, description="7d 或 30d")],
        responses={200: AdminAnalyticsTrendsResponseSerializer},
    )
    def get(self, request: Request) -> Response:
        require_admin_permission(request.user, "admin.analytics.read")
        return Response(
            platform_analytics_trends(range_name=request.query_params.get("range", "7d"))
        )


class AdminAnalyticsBreakdownView(APIView):
    authentication_classes: ClassVar[list[type[BaseAuthentication]]] = [
        AdminBearerTokenAuthentication
    ]
    permission_classes: ClassVar[list[type[BasePermission]]] = [IsAuthenticated]

    @extend_schema(
        summary="平台数据分组",
        parameters=[
            OpenApiParameter(
                "dimension",
                required=False,
                description="city/category/service_category/provider/channel",
            )
        ],
        responses={200: AdminAnalyticsBreakdownResponseSerializer},
    )
    def get(self, request: Request) -> Response:
        require_admin_permission(request.user, "admin.analytics.read")
        return Response(
            platform_analytics_breakdown(dimension=request.query_params.get("dimension", "city"))
        )


class AdminBasicSettingsView(APIView):
    authentication_classes: ClassVar[list[type[BaseAuthentication]]] = [
        AdminBearerTokenAuthentication
    ]
    permission_classes: ClassVar[list[type[BasePermission]]] = [IsAuthenticated]

    @extend_schema(
        summary="查看基础系统设置", responses={200: AdminSystemSettingResponseSerializer}
    )
    def get(self, request: Request) -> Response:
        require_admin_permission(request.user, "admin.settings.read")
        return Response(get_basic_settings())

    @extend_schema(
        summary="修改基础系统设置",
        request=AdminSystemSettingUpdateRequestSerializer,
        responses={200: AdminSystemSettingResponseSerializer},
    )
    def patch(self, request: Request) -> Response:
        require_admin_permission(request.user, "admin.settings.write")
        serializer = AdminSystemSettingUpdateRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return Response(
            update_basic_settings(
                operator=request.user,
                values=serializer.validated_data["settings"],
                expected_versions=serializer.validated_data["expected_versions"],
            )
        )


class AdminCompanyProfileView(APIView):
    """管理后台公司简介和营业执照资料维护接口。"""

    authentication_classes: ClassVar[list[type[BaseAuthentication]]] = [
        AdminBearerTokenAuthentication
    ]
    permission_classes: ClassVar[list[type[BasePermission]]] = [IsAuthenticated]

    @extend_schema(
        summary="查看公司简介和营业执照",
        responses={200: AdminCompanyProfileResponseSerializer},
    )
    def get(self, request: Request) -> Response:
        require_admin_permission(request.user, "admin.settings.read")
        return Response(get_company_profile(request))

    @extend_schema(
        summary="创建或更新公司简介和营业执照",
        description=(
            "首次创建时 expected_version 必须为 0；更新使用版本号防止并发覆盖。"
            "可选 Idempotency-Key 用于重放同一写请求；同键不同请求返回 409。"
        ),
        request=AdminCompanyProfileUpdateRequestSerializer,
        responses={200: AdminCompanyProfileResponseSerializer},
        parameters=[
            OpenApiParameter(
                "Idempotency-Key",
                location=OpenApiParameter.HEADER,
                type=str,
                required=False,
                description="重复保存同一公司资料时使用的幂等键",
            )
        ],
    )
    def patch(self, request: Request) -> Response:
        require_admin_permission(request.user, "admin.settings.write")
        serializer = AdminCompanyProfileUpdateRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return Response(
            update_company_profile(
                operator=request.user,
                payload=serializer.validated_data,
                request=request,
                idempotency_key=request.headers.get("Idempotency-Key", ""),
            )
        )


class AdminCompanyLicenseUploadView(APIView):
    """管理后台营业执照图片上传接口。"""

    authentication_classes: ClassVar[list[type[BaseAuthentication]]] = [
        AdminBearerTokenAuthentication
    ]
    permission_classes: ClassVar[list[type[BasePermission]]] = [IsAuthenticated]
    parser_classes: ClassVar[list[type]] = [MultiPartParser, FormParser]

    @extend_schema(
        summary="上传公司营业执照图片",
        description=("图片保存到服务端媒体存储并返回 media_id；保存公司资料时提交该 media_id。"),
        request=AdminCompanyLicenseUploadRequestSerializer,
        responses={
            200: MediaAssetResponseSerializer,
            201: MediaAssetResponseSerializer,
        },
        parameters=[
            OpenApiParameter(
                "Idempotency-Key",
                location=OpenApiParameter.HEADER,
                type=str,
                required=False,
                description="重复上传同一营业执照时使用的幂等键",
            )
        ],
    )
    def post(self, request: Request) -> Response:
        require_admin_permission(request.user, "admin.settings.write")
        serializer = AdminCompanyLicenseUploadRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        uploaded = serializer.validated_data["file"]
        if uploaded.size > settings.MEDIA_MAX_UPLOAD_BYTES:
            raise ApiError(
                ErrorCode.MEDIA_UPLOAD_TOO_LARGE,
                ERROR_MESSAGES[ErrorCode.MEDIA_UPLOAD_TOO_LARGE],
                status_code=413,
            )
        asset, reused = upload_company_business_license(
            operator=request.user,
            data=uploaded.read(),
            idempotency_key=request.headers.get("Idempotency-Key"),
        )
        payload = {
            **media_payload(asset, request),
            "reused": reused,
        }
        return Response(payload, status=200 if reused else 201)


class AdminAnnouncementListView(APIView):
    authentication_classes: ClassVar[list[type[BaseAuthentication]]] = [
        AdminBearerTokenAuthentication
    ]
    permission_classes: ClassVar[list[type[BasePermission]]] = [IsAuthenticated]

    @extend_schema(summary="查看公告", responses={200: AdminAnnouncementListResponseSerializer})
    def get(self, request: Request) -> Response:
        require_admin_permission(request.user, "admin.settings.read")
        return Response(
            list_announcements(
                status=request.query_params.get("status", ""),
                page=_integer_query(request, "page", 1, 1, 10_000),
                page_size=_integer_query(request, "page_size", 20, 1, 100),
            )
        )

    @extend_schema(
        summary="创建公告",
        request=AdminAnnouncementRequestSerializer,
        responses={201: AdminAnnouncementResponseSerializer},
    )
    def post(self, request: Request) -> Response:
        require_admin_permission(request.user, "admin.settings.write")
        serializer = AdminAnnouncementRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return Response(
            create_announcement(operator=request.user, payload=dict(serializer.validated_data)),
            status=201,
        )


class AdminAnnouncementDetailView(APIView):
    authentication_classes: ClassVar[list[type[BaseAuthentication]]] = [
        AdminBearerTokenAuthentication
    ]
    permission_classes: ClassVar[list[type[BasePermission]]] = [IsAuthenticated]

    @extend_schema(
        summary="修改公告",
        request=AdminAnnouncementRequestSerializer,
        responses={200: AdminAnnouncementResponseSerializer},
    )
    def patch(self, request: Request, announcement_no: str) -> Response:
        require_admin_permission(request.user, "admin.settings.write")
        serializer = AdminAnnouncementRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return Response(
            update_announcement(
                operator=request.user,
                announcement_no=announcement_no,
                payload=dict(serializer.validated_data),
            )
        )


class AdminCitySettingView(APIView):
    authentication_classes: ClassVar[list[type[BaseAuthentication]]] = [
        AdminBearerTokenAuthentication
    ]
    permission_classes: ClassVar[list[type[BasePermission]]] = [IsAuthenticated]

    @extend_schema(summary="查看城市配置", responses={200: AdminConfigOptionListResponseSerializer})
    def get(self, request: Request) -> Response:
        require_admin_permission(request.user, "admin.settings.read")
        return Response({"items": list_city_settings()})

    @extend_schema(
        summary="创建城市配置",
        request=AdminConfigOptionRequestSerializer,
        responses={201: AdminConfigOptionResponseSerializer},
    )
    def post(self, request: Request) -> Response:
        require_admin_permission(request.user, "admin.settings.write")
        serializer = AdminConfigOptionRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return Response(
            create_city_setting(operator=request.user, payload=dict(serializer.validated_data)),
            status=201,
        )


class AdminCitySettingDetailView(APIView):
    authentication_classes: ClassVar[list[type[BaseAuthentication]]] = [
        AdminBearerTokenAuthentication
    ]
    permission_classes: ClassVar[list[type[BasePermission]]] = [IsAuthenticated]

    @extend_schema(
        summary="修改城市配置",
        request=AdminConfigOptionRequestSerializer,
        responses={200: AdminConfigOptionResponseSerializer},
    )
    def patch(self, request: Request, code: str) -> Response:
        require_admin_permission(request.user, "admin.settings.write")
        serializer = AdminConfigOptionRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return Response(
            update_city_setting(
                operator=request.user, code=code, payload=dict(serializer.validated_data)
            )
        )

    @extend_schema(summary="停用城市配置", responses={200: AdminConfigOptionResponseSerializer})
    def delete(self, request: Request, code: str) -> Response:
        require_admin_permission(request.user, "admin.settings.write")
        return Response(
            update_city_setting(
                operator=request.user,
                code=code,
                payload={
                    "is_active": False,
                    "expected_version": int(request.data.get("expected_version", 0)),
                },
            )
        )


class AdminServiceCategorySettingView(APIView):
    authentication_classes: ClassVar[list[type[BaseAuthentication]]] = [
        AdminBearerTokenAuthentication
    ]
    permission_classes: ClassVar[list[type[BasePermission]]] = [IsAuthenticated]

    @extend_schema(
        summary="查看服务类目配置", responses={200: AdminConfigOptionListResponseSerializer}
    )
    def get(self, request: Request) -> Response:
        require_admin_permission(request.user, "admin.settings.read")
        return Response({"items": list_service_category_settings()})

    @extend_schema(
        summary="创建服务类目配置",
        request=AdminConfigOptionRequestSerializer,
        responses={201: AdminConfigOptionResponseSerializer},
    )
    def post(self, request: Request) -> Response:
        require_admin_permission(request.user, "admin.settings.write")
        serializer = AdminConfigOptionRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return Response(
            create_service_category_setting(
                operator=request.user,
                payload=dict(serializer.validated_data),
            ),
            status=201,
        )


class AdminServiceCategorySettingDetailView(APIView):
    authentication_classes: ClassVar[list[type[BaseAuthentication]]] = [
        AdminBearerTokenAuthentication
    ]
    permission_classes: ClassVar[list[type[BasePermission]]] = [IsAuthenticated]

    @extend_schema(
        summary="修改服务类目配置",
        request=AdminConfigOptionRequestSerializer,
        responses={200: AdminConfigOptionResponseSerializer},
    )
    def patch(self, request: Request, code: str) -> Response:
        require_admin_permission(request.user, "admin.settings.write")
        serializer = AdminConfigOptionRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return Response(
            update_service_category_setting(
                operator=request.user,
                code=code,
                payload=dict(serializer.validated_data),
            )
        )

    @extend_schema(summary="停用服务类目配置", responses={200: AdminConfigOptionResponseSerializer})
    def delete(self, request: Request, code: str) -> Response:
        require_admin_permission(request.user, "admin.settings.write")
        return Response(
            update_service_category_setting(
                operator=request.user,
                code=code,
                payload={
                    "is_active": False,
                    "expected_version": int(request.data.get("expected_version", 0)),
                },
            )
        )


class AdminCommissionRuleView(APIView):
    authentication_classes: ClassVar[list[type[BaseAuthentication]]] = [
        AdminBearerTokenAuthentication
    ]
    permission_classes: ClassVar[list[type[BasePermission]]] = [IsAuthenticated]

    @extend_schema(summary="查看佣金规则", responses={200: AdminCommissionRuleResponseSerializer})
    def get(self, request: Request) -> Response:
        require_admin_permission(request.user, "admin.settings.read")
        return Response(get_commission_rules())

    @extend_schema(
        summary="修改佣金规则",
        request=AdminCommissionRuleUpdateRequestSerializer,
        responses={200: AdminCommissionRuleResponseSerializer},
    )
    def patch(self, request: Request) -> Response:
        require_admin_permission(request.user, "admin.settings.write")
        serializer = AdminCommissionRuleUpdateRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return Response(
            update_commission_rules(operator=request.user, payload=dict(serializer.validated_data))
        )

    @extend_schema(summary="停用公告", responses={200: AdminAnnouncementResponseSerializer})
    def delete(self, request: Request, announcement_no: str) -> Response:
        require_admin_permission(request.user, "admin.settings.write")
        expected_version = request.data.get("expected_version")
        return Response(
            update_announcement(
                operator=request.user,
                announcement_no=announcement_no,
                payload={
                    "status": "DISABLED",
                    "expected_version": int(expected_version),
                },
            )
        )
