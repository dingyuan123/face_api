"""地点搜索和快捷关键词管理员 HTTP 接口。"""

from __future__ import annotations

from typing import ClassVar

from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework.authentication import BaseAuthentication
from rest_framework.permissions import BasePermission, IsAdminUser, IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from backend.accounts.authentication import BearerTokenAuthentication
from backend.locations.api.serializers import (
    LocationQuickKeywordAdminListResponseSerializer,
    LocationQuickKeywordAdminResponseSerializer,
    LocationQuickKeywordCreateSerializer,
    LocationQuickKeywordDeactivateSerializer,
    LocationQuickKeywordListResponseSerializer,
    LocationQuickKeywordUpdateSerializer,
    LocationSearchQuerySerializer,
    LocationSearchResponseSerializer,
    ProviderLocationStatusResponseSerializer,
    ProviderLocationUpdateSerializer,
)
from backend.locations.services import (
    create_quick_keyword,
    deactivate_quick_keyword,
    get_provider_location_status,
    list_quick_keywords,
    revoke_provider_location,
    search_locations,
    update_provider_location,
    update_quick_keyword,
)


class LocationQuickKeywordView(APIView):
    """登录用户获取地点快捷搜索关键词接口。"""

    authentication_classes: ClassVar[list[type[BaseAuthentication]]] = [BearerTokenAuthentication]
    permission_classes: ClassVar[list[type[BasePermission]]] = [IsAuthenticated]

    @extend_schema(
        summary="获取地点快捷搜索关键词",
        operation_id="listLocationQuickKeywords",
        responses={200: LocationQuickKeywordListResponseSerializer},
    )
    def get(self, request: Request) -> Response:
        return Response(list_quick_keywords(include_disabled=False))


class LocationSearchView(APIView):
    """登录用户搜索周边符合公共场所规则的地点接口。"""

    authentication_classes: ClassVar[list[type[BaseAuthentication]]] = [BearerTokenAuthentication]
    permission_classes: ClassVar[list[type[BasePermission]]] = [IsAuthenticated]
    throttle_classes: ClassVar[list[type[ScopedRateThrottle]]] = [ScopedRateThrottle]
    throttle_scope = "location_search"

    @extend_schema(
        summary="搜索周边公共场所",
        operation_id="searchNearbyLocations",
        parameters=[
            OpenApiParameter("keyword", type=str, description="自由搜索关键词，与快捷关键词二选一"),
            OpenApiParameter(
                "quick_keyword_code",
                type=str,
                description="后台维护的快捷关键词代码，与 keyword 二选一",
            ),
            OpenApiParameter("latitude", type=float, required=True, description="前端地图中心纬度"),
            OpenApiParameter(
                "longitude", type=float, required=True, description="前端地图中心经度"
            ),
            OpenApiParameter(
                "coordinate_system",
                type=str,
                description="前端坐标系，支持 GCJ02 或 WGS84",
            ),
            OpenApiParameter("radius_m", type=int, description="搜索半径，单位为米"),
            OpenApiParameter("limit", type=int, description="返回数量，最多 20"),
        ],
        responses={200: LocationSearchResponseSerializer},
    )
    def get(self, request: Request) -> Response:
        serializer = LocationSearchQuerySerializer(data=request.query_params)
        serializer.is_valid(raise_exception=True)
        payload = serializer.validated_data
        return Response(
            search_locations(
                user=request.user,
                latitude=payload["latitude"],
                longitude=payload["longitude"],
                coordinate_system=payload["coordinate_system"],
                keyword=payload.get("keyword"),
                quick_keyword_code=payload.get("quick_keyword_code"),
                radius_m=payload.get("radius_m"),
                limit=payload.get("limit"),
            )
        )


class ProviderLocationView(APIView):
    """服务者登录后更新、查询和撤销当前模糊位置。"""

    authentication_classes: ClassVar[list[type[BaseAuthentication]]] = [BearerTokenAuthentication]
    permission_classes: ClassVar[list[type[BasePermission]]] = [IsAuthenticated]

    @extend_schema(
        summary="查询服务者位置状态",
        operation_id="getProviderLocationStatus",
        responses={200: ProviderLocationStatusResponseSerializer},
    )
    def get(self, request: Request) -> Response:
        return Response(get_provider_location_status(user=request.user))

    @extend_schema(
        summary="更新服务者当前位置",
        operation_id="updateProviderLocation",
        request=ProviderLocationUpdateSerializer,
        responses={200: ProviderLocationStatusResponseSerializer},
    )
    def put(self, request: Request) -> Response:
        serializer = ProviderLocationUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return Response(
            update_provider_location(
                user=request.user,
                latitude=serializer.validated_data["latitude"],
                longitude=serializer.validated_data["longitude"],
                coordinate_system=serializer.validated_data["coordinate_system"],
                accuracy_m=serializer.validated_data.get("accuracy_m", 0),
                source=serializer.validated_data.get("source", "LOGIN"),
                privacy_version=serializer.validated_data.get("privacy_version", ""),
            )
        )

    @extend_schema(
        summary="撤销服务者位置共享",
        operation_id="revokeProviderLocation",
        request=OpenApiTypes.NONE,
        responses={200: ProviderLocationStatusResponseSerializer},
    )
    def delete(self, request: Request) -> Response:
        return Response(revoke_provider_location(user=request.user))


class AdminLocationQuickKeywordListCreateView(APIView):
    """管理员查看和创建地点快捷关键词配置接口。"""

    authentication_classes: ClassVar[list[type[BaseAuthentication]]] = [BearerTokenAuthentication]
    permission_classes: ClassVar[list[type[BasePermission]]] = [IsAdminUser]

    @extend_schema(
        summary="管理地点快捷关键词",
        operation_id="listAdminLocationQuickKeywords",
        responses={200: LocationQuickKeywordAdminListResponseSerializer},
    )
    def get(self, request: Request) -> Response:
        return Response(list_quick_keywords(include_disabled=True))

    @extend_schema(
        summary="创建地点快捷关键词",
        operation_id="createAdminLocationQuickKeyword",
        request=LocationQuickKeywordCreateSerializer,
        responses={201: LocationQuickKeywordAdminResponseSerializer},
    )
    def post(self, request: Request) -> Response:
        serializer = LocationQuickKeywordCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return Response(
            create_quick_keyword(
                admin=request.user,
                payload=serializer.validated_data,
                idempotency_key=request.headers.get("Idempotency-Key"),
            ),
            status=201,
        )


class AdminLocationQuickKeywordDetailView(APIView):
    """管理员更新和停用地点快捷关键词配置接口。"""

    authentication_classes: ClassVar[list[type[BaseAuthentication]]] = [BearerTokenAuthentication]
    permission_classes: ClassVar[list[type[BasePermission]]] = [IsAdminUser]

    @extend_schema(
        summary="更新地点快捷关键词",
        operation_id="updateAdminLocationQuickKeyword",
        request=LocationQuickKeywordUpdateSerializer,
        responses={200: LocationQuickKeywordAdminResponseSerializer},
    )
    def patch(self, request: Request, keyword_id: str) -> Response:
        serializer = LocationQuickKeywordUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return Response(
            update_quick_keyword(
                keyword_id=keyword_id,
                payload=serializer.validated_data,
            )
        )

    @extend_schema(
        summary="停用地点快捷关键词",
        operation_id="deactivateAdminLocationQuickKeyword",
        parameters=[
            OpenApiParameter(
                "expected_version",
                type=int,
                required=True,
                description="当前配置版本号",
            )
        ],
        request=OpenApiTypes.NONE,
        responses={200: LocationQuickKeywordAdminResponseSerializer},
    )
    def delete(self, request: Request, keyword_id: str) -> Response:
        serializer = LocationQuickKeywordDeactivateSerializer(data=request.query_params)
        serializer.is_valid(raise_exception=True)
        return Response(
            deactivate_quick_keyword(
                keyword_id=keyword_id,
                expected_version=serializer.validated_data["expected_version"],
            )
        )
