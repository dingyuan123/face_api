from __future__ import annotations

from typing import ClassVar

from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework.authentication import BaseAuthentication
from rest_framework.permissions import AllowAny, BasePermission, IsAdminUser, IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from backend.accounts.authentication import BearerTokenAuthentication
from backend.catalog.api.serializers import (
    AdminServiceListResponseSerializer,
    ExpectedVersionSerializer,
    ProviderTagResponseSerializer,
    ServiceCategoryResponseSerializer,
    ServiceCreateRequestSerializer,
    ServiceListResponseSerializer,
    ServiceResponseSerializer,
    ServiceReviewRequestSerializer,
    ServiceTagResponseSerializer,
    ServiceUpdateRequestSerializer,
)
from backend.catalog.models import ProviderService
from backend.catalog.services import (
    change_service_visibility,
    create_service,
    delete_service,
    get_public_service_payload,
    get_service_payload,
    list_admin_service_payloads,
    list_service_payloads,
    provider_tag_payloads,
    review_service,
    service_category_payloads,
    service_payload,
    service_tag_payloads,
    submit_service_for_review,
    update_service,
)
from backend.common.errors import ERROR_MESSAGES, ErrorCode
from backend.common.exceptions import ApiError


def _integer_query(request: Request, name: str, default: int, minimum: int, maximum: int) -> int:
    value = request.query_params.get(name)
    if value is None:
        return default
    try:
        parsed = int(value)
    except ValueError:
        raise ApiError(
            ErrorCode.SERVICE_INVALID,
            ERROR_MESSAGES[ErrorCode.SERVICE_INVALID],
            status_code=400,
            details={name: "必须是整数"},
        ) from None
    if not minimum <= parsed <= maximum:
        raise ApiError(
            ErrorCode.SERVICE_INVALID,
            ERROR_MESSAGES[ErrorCode.SERVICE_INVALID],
            status_code=400,
            details={name: f"必须在 {minimum} 到 {maximum} 之间"},
        )
    return parsed


class ServiceCategoryOptionsView(APIView):
    """服务类目配置查询接口。"""

    authentication_classes: ClassVar[list[type[BaseAuthentication]]] = []
    permission_classes: ClassVar[list[type[BasePermission]]] = [AllowAny]

    @extend_schema(
        auth=[],
        summary="获取服务类目",
        responses={200: ServiceCategoryResponseSerializer(many=True)},
    )
    def get(self, request: Request) -> Response:
        return Response(service_category_payloads())


class ServiceTagOptionsView(APIView):
    """服务标签配置查询接口。"""

    authentication_classes: ClassVar[list[type[BaseAuthentication]]] = []
    permission_classes: ClassVar[list[type[BasePermission]]] = [AllowAny]

    @extend_schema(
        auth=[], summary="获取服务标签", responses={200: ServiceTagResponseSerializer(many=True)}
    )
    def get(self, request: Request) -> Response:
        return Response(service_tag_payloads())


class ProviderTagOptionsView(APIView):
    """服务者资料标签配置查询接口。"""

    authentication_classes: ClassVar[list[type[BaseAuthentication]]] = []
    permission_classes: ClassVar[list[type[BasePermission]]] = [AllowAny]

    @extend_schema(
        auth=[],
        summary="获取服务者资料标签",
        responses={200: ProviderTagResponseSerializer(many=True)},
    )
    def get(self, request: Request) -> Response:
        return Response(provider_tag_payloads())


class ProviderServiceListCreateView(APIView):
    """服务者服务列表和创建接口。"""

    authentication_classes: ClassVar[list[type[BaseAuthentication]]] = [BearerTokenAuthentication]
    permission_classes: ClassVar[list[type[BasePermission]]] = [IsAuthenticated]

    @extend_schema(
        summary="获取当前服务者服务列表",
        operation_id="listProviderServices",
        parameters=[
            OpenApiParameter("status", type=str, required=False, description="服务状态筛选"),
            OpenApiParameter("page", type=int, required=False, description="页码，从 1 开始"),
            OpenApiParameter(
                "page_size", type=int, required=False, description="每页数量，最大 100"
            ),
        ],
        responses={200: ServiceListResponseSerializer},
    )
    def get(self, request: Request) -> Response:
        page = _integer_query(request, "page", 1, 1, 10_000)
        page_size = _integer_query(request, "page_size", 20, 1, 100)
        return Response(
            list_service_payloads(
                user=request.user,
                status=request.query_params.get("status"),
                page=page,
                page_size=page_size,
                request=request,
            )
        )

    @extend_schema(
        summary="创建服务草稿",
        operation_id="createProviderService",
        request=ServiceCreateRequestSerializer,
        responses={201: ServiceResponseSerializer},
        parameters=[
            OpenApiParameter(
                "Idempotency-Key",
                location=OpenApiParameter.HEADER,
                type=str,
                required=False,
                description="创建服务重复请求幂等键",
            )
        ],
    )
    def post(self, request: Request) -> Response:
        serializer = ServiceCreateRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        result = create_service(
            user=request.user,
            payload=serializer.validated_data,
            idempotency_key=request.headers.get("Idempotency-Key"),
        )
        return Response(
            service_payload(result.service, request),
            status=200 if result.reused else 201,
        )


class PublicServiceDetailView(APIView):
    """普通用户公开查询服务详情接口。"""

    authentication_classes: ClassVar[list[type[BaseAuthentication]]] = []
    permission_classes: ClassVar[list[type[BasePermission]]] = [AllowAny]

    @extend_schema(
        auth=[],
        summary="获取公开服务详情",
        operation_id="retrievePublicService",
        responses={200: ServiceResponseSerializer},
    )
    def get(self, request: Request, service_id: str) -> Response:
        return Response(get_public_service_payload(service_id, request))


class ProviderServiceDetailView(APIView):
    """服务查询、编辑和删除接口。"""

    authentication_classes: ClassVar[list[type[BaseAuthentication]]] = [BearerTokenAuthentication]
    permission_classes: ClassVar[list[type[BasePermission]]] = [IsAuthenticated]

    @extend_schema(
        summary="查询服务详情",
        operation_id="retrieveProviderService",
        responses={200: ServiceResponseSerializer},
    )
    def get(self, request: Request, service_id: str) -> Response:
        return Response(get_service_payload(request.user, service_id, request))

    @extend_schema(
        summary="修改服务草稿",
        operation_id="updateProviderService",
        request=ServiceUpdateRequestSerializer,
        responses={200: ServiceResponseSerializer},
    )
    def patch(self, request: Request, service_id: str) -> Response:
        serializer = ServiceUpdateRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        payload = dict(serializer.validated_data)
        expected_version = payload.pop("expected_version")
        result = update_service(
            user=request.user,
            service_id=service_id,
            payload=payload,
            expected_version=expected_version,
        )
        return Response(service_payload(result.service, request))

    @extend_schema(
        summary="删除服务草稿或被拒绝服务",
        operation_id="deleteProviderService",
        request=ExpectedVersionSerializer,
        responses={200: dict},
    )
    def delete(self, request: Request, service_id: str) -> Response:
        serializer = ExpectedVersionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        delete_service(
            user=request.user,
            service_id=service_id,
            expected_version=serializer.validated_data["expected_version"],
        )
        return Response({"deleted": True})


class ProviderServiceSubmitReviewView(APIView):
    """提交服务审核接口。"""

    authentication_classes: ClassVar[list[type[BaseAuthentication]]] = [BearerTokenAuthentication]
    permission_classes: ClassVar[list[type[BasePermission]]] = [IsAuthenticated]

    @extend_schema(
        summary="提交服务审核",
        operation_id="submitProviderServiceReview",
        request=ExpectedVersionSerializer,
        responses={200: ServiceResponseSerializer},
    )
    def post(self, request: Request, service_id: str) -> Response:
        serializer = ExpectedVersionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        service = submit_service_for_review(
            user=request.user,
            service_id=service_id,
            expected_version=serializer.validated_data["expected_version"],
        )
        return Response(service_payload(service, request))


class ProviderServiceOnlineView(APIView):
    """服务上架接口。"""

    authentication_classes: ClassVar[list[type[BaseAuthentication]]] = [BearerTokenAuthentication]
    permission_classes: ClassVar[list[type[BasePermission]]] = [IsAuthenticated]

    @extend_schema(
        summary="上架服务",
        operation_id="onlineProviderService",
        request=ExpectedVersionSerializer,
        responses={200: ServiceResponseSerializer},
    )
    def post(self, request: Request, service_id: str) -> Response:
        serializer = ExpectedVersionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        service = change_service_visibility(
            user=request.user,
            service_id=service_id,
            expected_version=serializer.validated_data["expected_version"],
            online=True,
        )
        return Response(service_payload(service, request))


class ProviderServiceOfflineView(APIView):
    """服务下架接口。"""

    authentication_classes: ClassVar[list[type[BaseAuthentication]]] = [BearerTokenAuthentication]
    permission_classes: ClassVar[list[type[BasePermission]]] = [IsAuthenticated]

    @extend_schema(
        summary="下架服务",
        operation_id="offlineProviderService",
        request=ExpectedVersionSerializer,
        responses={200: ServiceResponseSerializer},
    )
    def post(self, request: Request, service_id: str) -> Response:
        serializer = ExpectedVersionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        service = change_service_visibility(
            user=request.user,
            service_id=service_id,
            expected_version=serializer.validated_data["expected_version"],
            online=False,
        )
        return Response(service_payload(service, request))


class AdminProviderServiceListView(APIView):
    """管理员查看全平台服务列表。"""

    authentication_classes: ClassVar[list[type[BaseAuthentication]]] = [BearerTokenAuthentication]
    permission_classes: ClassVar[list[type[BasePermission]]] = [IsAdminUser]

    @extend_schema(
        summary="查看服务管理列表",
        operation_id="listAdminProviderServices",
        parameters=[
            OpenApiParameter("status", type=str, required=False, description="服务状态筛选"),
            OpenApiParameter(
                "provider_public_id",
                type=str,
                required=False,
                description="服务者对外用户 UUID",
            ),
            OpenApiParameter("category_code", type=str, required=False, description="服务类目代码"),
            OpenApiParameter(
                "keyword", type=str, required=False, description="服务名称或服务者昵称"
            ),
            OpenApiParameter("page", type=int, required=False, description="页码，从 1 开始"),
            OpenApiParameter(
                "page_size", type=int, required=False, description="每页数量，最大 100"
            ),
        ],
        responses={200: AdminServiceListResponseSerializer},
    )
    def get(self, request: Request) -> Response:
        page = _integer_query(request, "page", 1, 1, 10_000)
        page_size = _integer_query(request, "page_size", 20, 1, 100)
        keyword = request.query_params.get("keyword", "").strip()
        if len(keyword) > 100:
            raise ApiError(
                ErrorCode.SERVICE_INVALID,
                ERROR_MESSAGES[ErrorCode.SERVICE_INVALID],
                status_code=400,
                details={"keyword": "搜索词不能超过 100 个字符"},
            )
        return Response(
            list_admin_service_payloads(
                status=request.query_params.get("status"),
                provider_public_id=request.query_params.get("provider_public_id"),
                category_code=request.query_params.get("category_code"),
                keyword=keyword or None,
                page=page,
                page_size=page_size,
                request=request,
            )
        )


class AdminProviderServiceDetailView(APIView):
    """管理员查看服务详情接口。"""

    authentication_classes: ClassVar[list[type[BaseAuthentication]]] = [BearerTokenAuthentication]
    permission_classes: ClassVar[list[type[BasePermission]]] = [IsAdminUser]

    @extend_schema(summary="查看服务审核详情", responses={200: ServiceResponseSerializer})
    def get(self, request: Request, service_id: str) -> Response:
        service = (
            ProviderService.objects.select_related("category")
            .filter(public_id=service_id, deleted_at__isnull=True)
            .first()
        )
        if service is None:
            raise ApiError(
                ErrorCode.SERVICE_NOT_FOUND,
                ERROR_MESSAGES[ErrorCode.SERVICE_NOT_FOUND],
                status_code=404,
            )
        return Response(service_payload(service, request))


class AdminProviderServiceApproveView(APIView):
    """管理员审核通过服务接口。"""

    authentication_classes: ClassVar[list[type[BaseAuthentication]]] = [BearerTokenAuthentication]
    permission_classes: ClassVar[list[type[BasePermission]]] = [IsAdminUser]

    @extend_schema(
        summary="审核通过服务",
        request=ServiceReviewRequestSerializer,
        responses={200: ServiceResponseSerializer},
    )
    def post(self, request: Request, service_id: str) -> Response:
        serializer = ServiceReviewRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        service = review_service(
            service_id=service_id,
            approve=True,
            reviewer=request.user,
            expected_version=serializer.validated_data["expected_version"],
        )
        return Response(service_payload(service, request))


class AdminProviderServiceRejectView(APIView):
    """管理员审核拒绝服务接口。"""

    authentication_classes: ClassVar[list[type[BaseAuthentication]]] = [BearerTokenAuthentication]
    permission_classes: ClassVar[list[type[BasePermission]]] = [IsAdminUser]

    @extend_schema(
        summary="审核拒绝服务",
        request=ServiceReviewRequestSerializer,
        responses={200: ServiceResponseSerializer},
    )
    def post(self, request: Request, service_id: str) -> Response:
        serializer = ServiceReviewRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        service = review_service(
            service_id=service_id,
            approve=False,
            reviewer=request.user,
            expected_version=serializer.validated_data["expected_version"],
            reason=serializer.validated_data.get("reason", ""),
        )
        return Response(service_payload(service, request))
