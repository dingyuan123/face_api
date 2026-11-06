from __future__ import annotations

from typing import ClassVar

from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework.authentication import BaseAuthentication
from rest_framework.permissions import AllowAny, BasePermission, IsAdminUser
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from backend.accounts.authentication import BearerTokenAuthentication
from backend.common.errors import ERROR_MESSAGES, ErrorCode
from backend.common.exceptions import ApiError
from backend.common.pagination import ApiCursorPagination
from backend.discovery.api.serializers import (
    AdminTrendingCreateResponseSerializer,
    AdminTrendingCreateSerializer,
    AdminTrendingListResponseSerializer,
    AdminTrendingUpdateResponseSerializer,
    AdminTrendingUpdateSerializer,
    HomeFeedItemSerializer,
    SearchMomentListResponseSerializer,
    SearchNewsListResponseSerializer,
    SearchProviderListResponseSerializer,
    SearchResponseSerializer,
    TrendingListResponseSerializer,
)
from backend.discovery.search_services import (
    search_all_payload,
    search_moment_payload,
    search_news_payload,
    search_provider_payload,
)
from backend.discovery.services import home_feed_payloads, home_feed_queryset
from backend.discovery.trending_services import (
    create_manual_trending_keyword,
    list_admin_trending_keywords,
    list_trending_keywords,
    update_manual_trending_keyword,
)


class HomeFeedCursorPagination(ApiCursorPagination):
    """首页服务者卡片游标分页。"""

    page_size_query_param = "limit"
    max_page_size = 20

    def get_ordering(self, request: Request, queryset, view=None):
        sort = request.query_params.get("sort", "RECOMMENDED")
        return {
            "RECOMMENDED": ("-online_service_count", "-sold_count", "-updated_at", "-id"),
            "NEWEST": ("-updated_at", "-id"),
            "PRICE_ASC": ("min_price", "id"),
            "PRICE_DESC": ("-min_price", "-id"),
        }.get(sort, ("-online_service_count", "-sold_count", "-updated_at", "-id"))


class HomeFeedView(APIView):
    """首页服务者卡片流公开接口。"""

    authentication_classes: ClassVar[list[type[BaseAuthentication]]] = [BearerTokenAuthentication]
    permission_classes: ClassVar[list[type[BasePermission]]] = [AllowAny]
    pagination_class = HomeFeedCursorPagination

    @extend_schema(
        auth=[],
        summary="获取首页服务者卡片流",
        description=(
            "未登录可浏览；照片优先取服务者照片墙、申请生活照和服务相关媒体，"
            "按创建时间返回最近最多 5 张。"
        ),
        parameters=[
            OpenApiParameter("city_code", type=str, required=False, description="城市代码"),
            OpenApiParameter("category_code", type=str, required=False, description="服务类目代码"),
            OpenApiParameter(
                "sort",
                type=str,
                required=False,
                description="RECOMMENDED/NEWEST/PRICE_ASC/PRICE_DESC",
            ),
            OpenApiParameter("cursor", type=str, required=False, description="下一页游标"),
            OpenApiParameter("limit", type=int, required=False, description="每页数量"),
        ],
        responses={200: HomeFeedItemSerializer(many=True)},
    )
    def get(self, request: Request) -> Response:
        from django.conf import settings

        max_limit = (
            settings.HOME_FEED_AUTHENTICATED_LIMIT
            if request.user.is_authenticated
            else settings.HOME_FEED_GUEST_LIMIT
        )
        requested_limit = request.query_params.get("limit")
        if requested_limit is not None:
            try:
                if int(requested_limit) > max_limit:
                    raise ValueError
            except ValueError:
                raise ApiError(
                    ErrorCode.HOME_FEED_INVALID,
                    ERROR_MESSAGES[ErrorCode.HOME_FEED_INVALID],
                    status_code=400,
                    details={"limit": f"不能超过 {max_limit}"},
                ) from None
        paginator = self.pagination_class()
        paginator.page_size = max_limit
        queryset = home_feed_queryset(
            city_code=request.query_params.get(
                "city_code",
                settings.PROFILE_DEFAULT_CITY_CODE,
            ),
            category_code=request.query_params.get("category_code"),
            sort=request.query_params.get("sort", "RECOMMENDED"),
        )
        page = paginator.paginate_queryset(queryset, request, view=self)
        return paginator.get_paginated_response(home_feed_payloads(page or [], request))


def _integer_query(
    request: Request,
    name: str,
    *,
    default: int,
    minimum: int,
    maximum: int,
) -> int:
    """解析并校验搜索接口整数查询参数。"""

    raw_value = request.query_params.get(name)
    if raw_value is None:
        return default
    try:
        value = int(raw_value)
    except ValueError:
        raise ApiError(
            ErrorCode.SEARCH_INVALID,
            ERROR_MESSAGES[ErrorCode.SEARCH_INVALID],
            status_code=400,
            details={name: "必须是整数"},
        ) from None
    if not minimum <= value <= maximum:
        raise ApiError(
            ErrorCode.SEARCH_INVALID,
            ERROR_MESSAGES[ErrorCode.SEARCH_INVALID],
            status_code=400,
            details={name: f"必须在 {minimum} 到 {maximum} 之间"},
        )
    return value


class SearchAllView(APIView):
    """服务者、动态和资讯综合搜索接口。"""

    authentication_classes: ClassVar[list[type[BaseAuthentication]]] = [BearerTokenAuthentication]
    permission_classes: ClassVar[list[type[BasePermission]]] = [AllowAny]

    @extend_schema(
        auth=[],
        summary="综合搜索服务者、动态和资讯",
        operation_id="searchAll",
        description="三个分组返回预览和准确总数；分类结果可通过独立搜索接口继续分页。",
        parameters=[
            OpenApiParameter("keyword", type=str, required=True, description="搜索关键词"),
            OpenApiParameter(
                "preview_limit",
                type=int,
                required=False,
                description="每个分组预览数量，1 到 5",
            ),
        ],
        responses={200: SearchResponseSerializer},
    )
    def get(self, request: Request) -> Response:
        return Response(
            search_all_payload(
                keyword=request.query_params.get("keyword", ""),
                preview_limit=_integer_query(
                    request,
                    "preview_limit",
                    default=3,
                    minimum=1,
                    maximum=5,
                ),
                request=request,
                viewer=request.user if request.user.is_authenticated else None,
            )
        )


class SearchProvidersView(APIView):
    """公开服务者关键词搜索接口。"""

    authentication_classes: ClassVar[list[type[BaseAuthentication]]] = [BearerTokenAuthentication]
    permission_classes: ClassVar[list[type[BasePermission]]] = [AllowAny]

    @extend_schema(
        auth=[],
        summary="搜索公开服务者",
        operation_id="searchProviders",
        parameters=[
            OpenApiParameter("keyword", type=str, required=True, description="搜索关键词"),
            OpenApiParameter("cursor", type=str, required=False, description="下一页游标"),
            OpenApiParameter("limit", type=int, required=False, description="每页数量，1 到 100"),
        ],
        responses={200: SearchProviderListResponseSerializer},
    )
    def get(self, request: Request) -> Response:
        return Response(
            search_provider_payload(
                keyword=request.query_params.get("keyword", ""),
                request=request,
                http_request=request._request,
                viewer=request.user if request.user.is_authenticated else None,
                limit=_integer_query(
                    request,
                    "limit",
                    default=20,
                    minimum=1,
                    maximum=100,
                ),
                view=self,
            )
        )


class SearchMomentsView(APIView):
    """公开动态关键词搜索接口。"""

    authentication_classes: ClassVar[list[type[BaseAuthentication]]] = [BearerTokenAuthentication]
    permission_classes: ClassVar[list[type[BasePermission]]] = [AllowAny]

    @extend_schema(
        auth=[],
        summary="搜索公开动态",
        operation_id="searchMoments",
        parameters=[
            OpenApiParameter("keyword", type=str, required=True, description="搜索关键词"),
            OpenApiParameter("cursor", type=str, required=False, description="下一页游标"),
            OpenApiParameter("limit", type=int, required=False, description="每页数量，1 到 100"),
        ],
        responses={200: SearchMomentListResponseSerializer},
    )
    def get(self, request: Request) -> Response:
        return Response(
            search_moment_payload(
                keyword=request.query_params.get("keyword", ""),
                request=request,
                http_request=request._request,
                viewer=request.user if request.user.is_authenticated else None,
                limit=_integer_query(
                    request,
                    "limit",
                    default=20,
                    minimum=1,
                    maximum=100,
                ),
                view=self,
            )
        )


class SearchNewsView(APIView):
    """公开资讯关键词搜索接口。"""

    @extend_schema(
        auth=[],
        summary="搜索公开资讯",
        operation_id="searchNews",
        parameters=[
            OpenApiParameter("keyword", type=str, required=True, description="搜索关键词"),
            OpenApiParameter("page", type=int, required=False, description="页码，从 1 开始"),
            OpenApiParameter(
                "page_size", type=int, required=False, description="每页数量，1 到 100"
            ),
        ],
        responses={200: SearchNewsListResponseSerializer},
    )
    def get(self, request: Request) -> Response:
        return Response(
            search_news_payload(
                keyword=request.query_params.get("keyword", ""),
                request=request._request,
                page=_integer_query(request, "page", default=1, minimum=1, maximum=10_000),
                page_size=_integer_query(
                    request,
                    "page_size",
                    default=20,
                    minimum=1,
                    maximum=100,
                ),
            )
        )


class TrendingSearchView(APIView):
    """大家都在搜热门搜索词公开接口。"""

    @extend_schema(
        auth=[],
        summary="获取大家都在搜热门搜索词",
        operation_id="listTrendingSearch",
        parameters=[
            OpenApiParameter(
                "limit",
                type=int,
                required=False,
                description="返回数量，1 到 50",
            ),
        ],
        responses={200: TrendingListResponseSerializer},
    )
    def get(self, request: Request) -> Response:
        return Response(
            list_trending_keywords(
                limit=_integer_query(
                    request,
                    "limit",
                    default=10,
                    minimum=1,
                    maximum=50,
                )
            )
        )


class AdminTrendingListCreateView(APIView):
    """管理员查看和创建热门搜索配置接口。"""

    authentication_classes: ClassVar[list[type[BaseAuthentication]]] = [BearerTokenAuthentication]
    permission_classes: ClassVar[list[type[BasePermission]]] = [IsAdminUser]

    @extend_schema(
        summary="管理热门搜索配置",
        operation_id="listAdminTrendingSearch",
        responses={200: AdminTrendingListResponseSerializer},
    )
    def get(self, request: Request) -> Response:
        return Response(list_admin_trending_keywords())

    @extend_schema(
        summary="创建人工热门搜索",
        operation_id="createAdminTrendingSearch",
        request=AdminTrendingCreateSerializer,
        responses={201: AdminTrendingCreateResponseSerializer},
    )
    def post(self, request: Request) -> Response:
        serializer = AdminTrendingCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return Response(
            create_manual_trending_keyword(
                admin=request.user,
                display_keyword=serializer.validated_data["display_keyword"],
                display_status=serializer.validated_data["display_status"],
                manual_priority=serializer.validated_data["manual_priority"],
            ),
            status=201,
        )


class AdminTrendingUpdateView(APIView):
    """管理员更新热门搜索展示、屏蔽和置顶配置接口。"""

    authentication_classes: ClassVar[list[type[BaseAuthentication]]] = [BearerTokenAuthentication]
    permission_classes: ClassVar[list[type[BasePermission]]] = [IsAdminUser]

    @extend_schema(
        summary="更新人工热门搜索",
        operation_id="updateAdminTrendingSearch",
        request=AdminTrendingUpdateSerializer,
        responses={200: AdminTrendingUpdateResponseSerializer},
    )
    def patch(self, request: Request, trending_id: str) -> Response:
        serializer = AdminTrendingUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return Response(
            update_manual_trending_keyword(
                admin=request.user,
                trending_id=trending_id,
                payload=serializer.validated_data,
            )
        )
