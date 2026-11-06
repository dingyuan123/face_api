from __future__ import annotations

from typing import ClassVar

from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework.authentication import BaseAuthentication
from rest_framework.permissions import AllowAny, BasePermission, IsAdminUser, IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from backend.accounts.authentication import BearerTokenAuthentication
from backend.catalog.services import list_service_payloads
from backend.common.errors import ERROR_MESSAGES, ErrorCode
from backend.common.exceptions import ApiError
from backend.common.pagination import ApiCursorPagination
from backend.common.renderers import build_success_envelope
from backend.content.api.serializers import (
    AdminMomentListResponseSerializer,
    MomentCategoryResponseSerializer,
    MomentExpectedVersionSerializer,
    MomentInputSerializer,
    MomentListResponseSerializer,
    MomentNeighborsResponseSerializer,
    MomentResponseSerializer,
    MomentReviewRequestSerializer,
    MomentUpdateRequestSerializer,
    MountableServiceSerializer,
)
from backend.content.services import (
    create_moment,
    delete_moment,
    get_admin_moment_payload,
    get_owned_moment_payload,
    get_public_moment_neighbors,
    get_public_moment_payload,
    list_admin_moment_payloads,
    list_owned_moment_payloads,
    moment_category_payloads,
    moment_payload,
    moment_payloads,
    public_moment_queryset,
    publish_moment,
    review_moment,
    update_moment,
)


def _integer_query(
    request: Request,
    name: str,
    default: int,
    minimum: int,
    maximum: int,
) -> int:
    value = request.query_params.get(name)
    if value is None:
        return default
    try:
        parsed = int(value)
    except ValueError:
        raise ApiError(
            ErrorCode.MOMENT_INVALID,
            ERROR_MESSAGES[ErrorCode.MOMENT_INVALID],
            status_code=400,
            details={name: "必须是整数"},
        ) from None
    if not minimum <= parsed <= maximum:
        raise ApiError(
            ErrorCode.MOMENT_INVALID,
            ERROR_MESSAGES[ErrorCode.MOMENT_INVALID],
            status_code=400,
            details={name: f"必须在 {minimum} 到 {maximum} 之间"},
        )
    return parsed


class MomentCursorPagination(ApiCursorPagination):
    """公开动态游标分页。"""

    ordering = ("-published_at", "-id")
    page_size_query_param = "limit"
    max_page_size = 20


class ProviderMomentListCreateView(APIView):
    """服务者动态管理列表和创建接口。"""

    authentication_classes: ClassVar[list[type[BaseAuthentication]]] = [BearerTokenAuthentication]
    permission_classes: ClassVar[list[type[BasePermission]]] = [IsAuthenticated]

    @extend_schema(
        summary="获取当前服务者动态列表",
        operation_id="listProviderMoments",
        parameters=[
            OpenApiParameter("status", type=str, required=False, description="动态状态筛选"),
            OpenApiParameter("page", type=int, required=False, description="页码"),
            OpenApiParameter("page_size", type=int, required=False, description="每页数量"),
        ],
        responses={200: MomentListResponseSerializer},
    )
    def get(self, request: Request) -> Response:
        return Response(
            list_owned_moment_payloads(
                user=request.user,
                status=request.query_params.get("status"),
                page=_integer_query(request, "page", 1, 1, 10_000),
                page_size=_integer_query(request, "page_size", 20, 1, 100),
                request=request,
            )
        )

    @extend_schema(
        summary="创建服务者动态草稿",
        operation_id="createProviderMoment",
        request=MomentInputSerializer,
        responses={201: MomentResponseSerializer},
        parameters=[
            OpenApiParameter(
                "Idempotency-Key",
                location=OpenApiParameter.HEADER,
                type=str,
                required=False,
                description="创建动态重复请求幂等键",
            )
        ],
    )
    def post(self, request: Request) -> Response:
        serializer = MomentInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        result = create_moment(
            user=request.user,
            payload=serializer.validated_data,
            idempotency_key=request.headers.get("Idempotency-Key"),
        )
        return Response(
            moment_payload(result.moment, request, request.user),
            status=200 if result.reused else 201,
        )


class ProviderMomentDetailView(APIView):
    """服务者动态详情、修改和删除接口。"""

    authentication_classes: ClassVar[list[type[BaseAuthentication]]] = [BearerTokenAuthentication]
    permission_classes: ClassVar[list[type[BasePermission]]] = [IsAuthenticated]

    @extend_schema(
        summary="查询服务者动态详情",
        operation_id="retrieveProviderMoment",
        responses={200: MomentResponseSerializer},
    )
    def get(self, request: Request, moment_id: str) -> Response:
        return Response(get_owned_moment_payload(request.user, moment_id, request, request.user))

    @extend_schema(
        summary="修改服务者动态",
        operation_id="updateProviderMoment",
        request=MomentUpdateRequestSerializer,
        responses={200: MomentResponseSerializer},
    )
    def patch(self, request: Request, moment_id: str) -> Response:
        serializer = MomentUpdateRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        payload = dict(serializer.validated_data)
        expected_version = payload.pop("expected_version")
        result = update_moment(
            user=request.user,
            moment_id=moment_id,
            payload=payload,
            expected_version=expected_version,
        )
        return Response(moment_payload(result.moment, request, request.user))

    @extend_schema(
        summary="删除服务者动态",
        operation_id="deleteProviderMoment",
        request=MomentExpectedVersionSerializer,
        responses={200: dict},
    )
    def delete(self, request: Request, moment_id: str) -> Response:
        serializer = MomentExpectedVersionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        delete_moment(
            user=request.user,
            moment_id=moment_id,
            expected_version=serializer.validated_data["expected_version"],
        )
        return Response({"deleted": True})


class ProviderMomentPublishView(APIView):
    """发布动态接口；当前发布策略为直接通过。"""

    authentication_classes: ClassVar[list[type[BaseAuthentication]]] = [BearerTokenAuthentication]
    permission_classes: ClassVar[list[type[BasePermission]]] = [IsAuthenticated]

    @extend_schema(
        summary="发布服务者动态",
        operation_id="publishProviderMoment",
        request=MomentExpectedVersionSerializer,
        responses={200: MomentResponseSerializer},
    )
    def post(self, request: Request, moment_id: str) -> Response:
        serializer = MomentExpectedVersionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        moment = publish_moment(
            user=request.user,
            moment_id=moment_id,
            expected_version=serializer.validated_data["expected_version"],
        )
        return Response(moment_payload(moment, request, request.user))


class MountableServicesView(APIView):
    """返回动态可挂载的服务者服务。"""

    authentication_classes: ClassVar[list[type[BaseAuthentication]]] = [BearerTokenAuthentication]
    permission_classes: ClassVar[list[type[BasePermission]]] = [IsAuthenticated]

    @extend_schema(
        summary="获取动态可挂载服务",
        operation_id="listMomentMountableServices",
        responses={200: MountableServiceSerializer(many=True)},
    )
    def get(self, request: Request) -> Response:
        data = list_service_payloads(
            user=request.user,
            status="ONLINE",
            page=1,
            page_size=100,
            request=request,
        )
        return Response(data["items"])


class PublicMomentListView(APIView):
    """公开已发布动态列表。"""

    authentication_classes: ClassVar[list[type[BaseAuthentication]]] = [BearerTokenAuthentication]
    permission_classes: ClassVar[list[type[BasePermission]]] = [AllowAny]
    pagination_class = MomentCursorPagination

    @extend_schema(
        auth=[],
        summary="获取公开动态",
        operation_id="listPublicMoments",
        parameters=[
            OpenApiParameter("keyword", type=str, required=False, description="动态关键词"),
            OpenApiParameter("category_code", type=str, required=False, description="类目代码"),
            OpenApiParameter(
                "tab",
                type=str,
                required=False,
                description="RECOMMENDED/FOLLOWING/NEARBY",
            ),
            OpenApiParameter("city_code", type=str, required=False, description="同城动态城市代码"),
            OpenApiParameter("cursor", type=str, required=False, description="下一页游标"),
            OpenApiParameter("limit", type=int, required=False, description="每页数量"),
        ],
        responses={200: MomentResponseSerializer(many=True)},
    )
    def get(self, request: Request) -> Response:
        tab = request.query_params.get("tab", "RECOMMENDED")
        if tab not in {"RECOMMENDED", "FOLLOWING", "NEARBY"}:
            raise ApiError(
                ErrorCode.MOMENT_INVALID,
                ERROR_MESSAGES[ErrorCode.MOMENT_INVALID],
                status_code=400,
                details={"tab": "动态筛选标签不存在"},
            )
        if tab == "FOLLOWING":
            return Response(
                build_success_envelope(
                    [],
                    {
                        "tab": tab,
                        "strategy": "FOLLOWING",
                        "category_code": request.query_params.get("category_code", ""),
                        "city_code": request.query_params.get("city_code", ""),
                        "location_mode": None,
                        "available": False,
                        "next_cursor": None,
                        "has_more": False,
                    },
                )
            )
        paginator = self.pagination_class()
        queryset = public_moment_queryset(
            keyword=request.query_params.get("keyword"),
            category_code=request.query_params.get("category_code"),
            tab=tab,
            city_code=request.query_params.get("city_code"),
        )
        page = paginator.paginate_queryset(queryset, request, view=self)
        response = paginator.get_paginated_response(
            moment_payloads(page or [], request, request.user)
        )
        response.data["meta"].update(
            {
                "tab": tab,
                "strategy": "NEWEST",
                "category_code": request.query_params.get("category_code", ""),
                "city_code": request.query_params.get("city_code", ""),
                "location_mode": "CITY" if tab == "NEARBY" else None,
                "available": True,
            }
        )
        return response


class PublicMomentDetailView(APIView):
    """公开动态详情。"""

    authentication_classes: ClassVar[list[type[BaseAuthentication]]] = [BearerTokenAuthentication]
    permission_classes: ClassVar[list[type[BasePermission]]] = [AllowAny]

    @extend_schema(auth=[], summary="获取公开动态详情", responses={200: MomentResponseSerializer})
    def get(self, request: Request, moment_id: str) -> Response:
        return Response(get_public_moment_payload(moment_id, request, request.user))


class PublicMomentNeighborsView(APIView):
    """返回当前公开动态的前后相邻动态。"""

    authentication_classes: ClassVar[list[type[BaseAuthentication]]] = [BearerTokenAuthentication]
    permission_classes: ClassVar[list[type[BasePermission]]] = [AllowAny]

    @extend_schema(
        auth=[],
        summary="获取动态上下滑动相邻内容",
        operation_id="getPublicMomentNeighbors",
        parameters=[
            OpenApiParameter("keyword", type=str, required=False, description="动态关键词"),
            OpenApiParameter("category_code", type=str, required=False, description="类目代码"),
            OpenApiParameter(
                "tab",
                type=str,
                required=False,
                description="RECOMMENDED/FOLLOWING/NEARBY",
            ),
            OpenApiParameter("city_code", type=str, required=False, description="同城动态城市代码"),
            OpenApiParameter(
                "sort",
                type=str,
                required=False,
                description="排序方式，当前支持 NEWEST",
            ),
        ],
        responses={200: MomentNeighborsResponseSerializer},
    )
    def get(self, request: Request, moment_id: str) -> Response:
        sort = request.query_params.get("sort", "NEWEST")
        if sort != "NEWEST":
            raise ApiError(
                ErrorCode.MOMENT_INVALID,
                ERROR_MESSAGES[ErrorCode.MOMENT_INVALID],
                status_code=400,
                details={"sort": "当前仅支持 NEWEST"},
            )
        return Response(
            get_public_moment_neighbors(
                moment_id=moment_id,
                keyword=request.query_params.get("keyword"),
                category_code=request.query_params.get("category_code"),
                tab=request.query_params.get("tab", "RECOMMENDED"),
                city_code=request.query_params.get("city_code"),
                request=request,
                viewer=request.user,
            )
        )


class MomentCategoryOptionsView(APIView):
    """动态内容类目配置查询接口。"""

    authentication_classes: ClassVar[list[type[BaseAuthentication]]] = []
    permission_classes: ClassVar[list[type[BasePermission]]] = [AllowAny]

    @extend_schema(
        auth=[],
        summary="获取动态内容类目",
        operation_id="listMomentCategories",
        responses={200: MomentCategoryResponseSerializer(many=True)},
    )
    def get(self, request: Request) -> Response:
        return Response(moment_category_payloads())


class AdminMomentListView(APIView):
    """管理员动态列表。"""

    authentication_classes: ClassVar[list[type[BaseAuthentication]]] = [BearerTokenAuthentication]
    permission_classes: ClassVar[list[type[BasePermission]]] = [IsAdminUser]

    @extend_schema(
        summary="查看动态管理列表",
        operation_id="listAdminMoments",
        parameters=[
            OpenApiParameter("status", type=str, required=False, description="动态状态"),
            OpenApiParameter(
                "provider_public_id", type=str, required=False, description="服务者公开 ID"
            ),
            OpenApiParameter(
                "keyword", type=str, required=False, description="动态关键词或服务者昵称"
            ),
            OpenApiParameter("page", type=int, required=False, description="页码"),
            OpenApiParameter("page_size", type=int, required=False, description="每页数量"),
        ],
        responses={200: AdminMomentListResponseSerializer},
    )
    def get(self, request: Request) -> Response:
        return Response(
            list_admin_moment_payloads(
                status=request.query_params.get("status"),
                provider_public_id=request.query_params.get("provider_public_id"),
                keyword=request.query_params.get("keyword"),
                page=_integer_query(request, "page", 1, 1, 10_000),
                page_size=_integer_query(request, "page_size", 20, 1, 100),
                request=request,
            )
        )


class AdminMomentDetailView(APIView):
    """管理员动态详情。"""

    authentication_classes: ClassVar[list[type[BaseAuthentication]]] = [BearerTokenAuthentication]
    permission_classes: ClassVar[list[type[BasePermission]]] = [IsAdminUser]

    @extend_schema(
        summary="查看动态审核详情",
        operation_id="retrieveAdminMoment",
        responses={200: MomentResponseSerializer},
    )
    def get(self, request: Request, moment_id: str) -> Response:
        return Response(get_admin_moment_payload(moment_id, request, request.user))


class AdminMomentApproveView(APIView):
    """管理员审核通过动态。"""

    authentication_classes: ClassVar[list[type[BaseAuthentication]]] = [BearerTokenAuthentication]
    permission_classes: ClassVar[list[type[BasePermission]]] = [IsAdminUser]

    @extend_schema(
        summary="审核通过动态",
        operation_id="approveAdminMoment",
        request=MomentReviewRequestSerializer,
        responses={200: MomentResponseSerializer},
    )
    def post(self, request: Request, moment_id: str) -> Response:
        serializer = MomentReviewRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        moment = review_moment(
            moment_id=moment_id,
            approve=True,
            reviewer=request.user,
            expected_version=serializer.validated_data["expected_version"],
        )
        return Response(moment_payload(moment, request, request.user))


class AdminMomentRejectView(APIView):
    """管理员拒绝动态。"""

    authentication_classes: ClassVar[list[type[BaseAuthentication]]] = [BearerTokenAuthentication]
    permission_classes: ClassVar[list[type[BasePermission]]] = [IsAdminUser]

    @extend_schema(
        summary="审核拒绝动态",
        operation_id="rejectAdminMoment",
        request=MomentReviewRequestSerializer,
        responses={200: MomentResponseSerializer},
    )
    def post(self, request: Request, moment_id: str) -> Response:
        serializer = MomentReviewRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        moment = review_moment(
            moment_id=moment_id,
            approve=False,
            reviewer=request.user,
            expected_version=serializer.validated_data["expected_version"],
            reason=serializer.validated_data.get("reason", ""),
        )
        return Response(moment_payload(moment, request, request.user))
