"""资讯 App 只读接口和管理员资讯、来源及同步维护接口。"""

from __future__ import annotations

from typing import ClassVar

from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework.authentication import BaseAuthentication
from rest_framework.permissions import BasePermission, IsAdminUser
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from backend.accounts.authentication import BearerTokenAuthentication
from backend.content.api.news_serializers import (
    NewsArticleInputSerializer,
    NewsArticleResponseSerializer,
    NewsCategoryResponseSerializer,
    NewsDeleteRequestSerializer,
    NewsListResponseSerializer,
    NewsReviewRequestSerializer,
    NewsShareResponseSerializer,
    NewsSourceInputSerializer,
    NewsSourceResponseSerializer,
    NewsSyncRequestSerializer,
    NewsSyncRunResponseSerializer,
    NewsUpdateRequestSerializer,
    NewsVersionRequestSerializer,
)
from backend.content.news_services import (
    create_news_article,
    create_news_source,
    create_news_sync_run,
    delete_news_article,
    get_admin_news_article,
    get_news_article,
    get_news_sync_run,
    list_admin_news,
    list_news_sources,
    list_public_news,
    news_category_payloads,
    news_share_payload,
    review_news_article,
    update_news_article,
    update_news_source,
)


def _integer_query(
    request: Request,
    name: str,
    default: int,
    minimum: int,
    maximum: int,
) -> int:
    try:
        value = int(request.query_params.get(name, default))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} 必须是整数") from exc
    return max(minimum, min(value, maximum))


class NewsCategoryListView(APIView):
    """资讯类目配置只读接口。"""

    @extend_schema(
        summary="获取资讯类目",
        operation_id="listNewsCategories",
        auth=[],
        responses={200: NewsCategoryResponseSerializer(many=True)},
    )
    def get(self, request: Request) -> Response:
        return Response(news_category_payloads())


class PublicNewsListView(APIView):
    """App 已发布资讯列表接口。"""

    @extend_schema(
        summary="获取公开资讯列表",
        operation_id="listPublicNews",
        auth=[],
        parameters=[
            OpenApiParameter("category_code", type=str, description="资讯类目代码"),
            OpenApiParameter("country_code", type=str, description="国家或地区代码"),
            OpenApiParameter("language_code", type=str, description="内容语言代码"),
            OpenApiParameter("keyword", type=str, description="标题或摘要关键词"),
            OpenApiParameter("featured", type=bool, description="只看重点资讯"),
            OpenApiParameter("page", type=int, description="页码，从 1 开始"),
            OpenApiParameter("page_size", type=int, description="每页数量，1 到 100"),
        ],
        responses={200: NewsListResponseSerializer},
    )
    def get(self, request: Request) -> Response:
        featured_value = request.query_params.get("featured")
        featured = None
        if featured_value is not None:
            featured = featured_value.lower() in {"1", "true", "yes"}
        return Response(
            list_public_news(
                category_code=request.query_params.get("category_code"),
                country_code=request.query_params.get("country_code"),
                language_code=request.query_params.get("language_code"),
                keyword=request.query_params.get("keyword"),
                featured=featured,
                page=_integer_query(request, "page", 1, 1, 10_000),
                page_size=_integer_query(request, "page_size", 20, 1, 100),
                request=request,
            )
        )


class PublicNewsDetailView(APIView):
    """App 已发布资讯详情接口。"""

    @extend_schema(
        summary="获取公开资讯详情",
        operation_id="retrievePublicNews",
        auth=[],
        responses={200: NewsArticleResponseSerializer},
    )
    def get(self, request: Request, news_id: str) -> Response:
        return Response(get_news_article(news_id, request))


class NewsShareView(APIView):
    """生成资讯公开分享链接。"""

    @extend_schema(
        summary="生成资讯分享链接",
        operation_id="sharePublicNews",
        auth=[],
        responses={200: NewsShareResponseSerializer},
    )
    def get(self, request: Request, news_id: str) -> Response:
        return Response(news_share_payload(news_id, request))


class AdminNewsListCreateView(APIView):
    """管理员资讯列表和创建草稿。"""

    authentication_classes: ClassVar[list[type[BaseAuthentication]]] = [BearerTokenAuthentication]
    permission_classes: ClassVar[list[type[BasePermission]]] = [IsAdminUser]

    @extend_schema(
        summary="管理资讯列表",
        operation_id="listAdminNews",
        parameters=[
            OpenApiParameter("status", type=str, description="资讯状态"),
            OpenApiParameter("keyword", type=str, description="标题或摘要关键词"),
            OpenApiParameter("page", type=int, description="页码"),
            OpenApiParameter("page_size", type=int, description="每页数量"),
        ],
        responses={200: NewsListResponseSerializer},
    )
    def get(self, request: Request) -> Response:
        return Response(
            list_admin_news(
                status=request.query_params.get("status"),
                keyword=request.query_params.get("keyword"),
                page=_integer_query(request, "page", 1, 1, 10_000),
                page_size=_integer_query(request, "page_size", 20, 1, 100),
                request=request,
            )
        )

    @extend_schema(
        summary="创建资讯草稿",
        operation_id="createAdminNews",
        request=NewsArticleInputSerializer,
        responses={201: NewsArticleResponseSerializer},
    )
    def post(self, request: Request) -> Response:
        serializer = NewsArticleInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return Response(
            create_news_article(
                user=request.user,
                payload=serializer.validated_data,
                request=request,
                idempotency_key=request.headers.get("Idempotency-Key"),
            ),
            status=201,
        )


class AdminNewsDetailView(APIView):
    """管理员查看、编辑和逻辑删除资讯。"""

    authentication_classes: ClassVar[list[type[BaseAuthentication]]] = [BearerTokenAuthentication]
    permission_classes: ClassVar[list[type[BasePermission]]] = [IsAdminUser]

    @extend_schema(
        summary="查看管理资讯详情",
        operation_id="retrieveAdminNews",
        responses={200: NewsArticleResponseSerializer},
    )
    def get(self, request: Request, news_id: str) -> Response:
        return Response(get_admin_news_article(news_id, request))

    @extend_schema(
        summary="编辑资讯草稿",
        operation_id="updateAdminNews",
        request=NewsUpdateRequestSerializer,
        responses={200: NewsArticleResponseSerializer},
    )
    def patch(self, request: Request, news_id: str) -> Response:
        serializer = NewsUpdateRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        payload = dict(serializer.validated_data)
        expected_version = int(payload.pop("expected_version"))
        return Response(
            update_news_article(
                user=request.user,
                news_id=news_id,
                payload=payload,
                expected_version=expected_version,
                request=request,
            )
        )

    @extend_schema(
        summary="逻辑删除资讯",
        operation_id="deleteAdminNews",
        request=NewsDeleteRequestSerializer,
        responses={200: dict},
    )
    def delete(self, request: Request, news_id: str) -> Response:
        serializer = NewsDeleteRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return Response(
            delete_news_article(
                user=request.user,
                news_id=news_id,
                expected_version=serializer.validated_data["expected_version"],
                reason=serializer.validated_data.get("reason", ""),
            )
        )


class AdminNewsPublishView(APIView):
    """管理员发布资讯。"""

    authentication_classes: ClassVar[list[type[BaseAuthentication]]] = [BearerTokenAuthentication]
    permission_classes: ClassVar[list[type[BasePermission]]] = [IsAdminUser]

    @extend_schema(
        summary="发布资讯",
        operation_id="publishAdminNews",
        request=NewsVersionRequestSerializer,
        responses={200: NewsArticleResponseSerializer},
    )
    def post(self, request: Request, news_id: str) -> Response:
        serializer = NewsVersionRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return Response(
            review_news_article(
                user=request.user,
                news_id=news_id,
                approve=True,
                expected_version=serializer.validated_data["expected_version"],
                request=request,
            )
        )


class AdminNewsRejectView(APIView):
    """管理员拒绝资讯。"""

    authentication_classes: ClassVar[list[type[BaseAuthentication]]] = [BearerTokenAuthentication]
    permission_classes: ClassVar[list[type[BasePermission]]] = [IsAdminUser]

    @extend_schema(
        summary="拒绝资讯",
        operation_id="rejectAdminNews",
        request=NewsReviewRequestSerializer,
        responses={200: NewsArticleResponseSerializer},
    )
    def post(self, request: Request, news_id: str) -> Response:
        serializer = NewsReviewRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return Response(
            review_news_article(
                user=request.user,
                news_id=news_id,
                approve=False,
                expected_version=serializer.validated_data["expected_version"],
                reason=serializer.validated_data.get("reason", ""),
                request=request,
            )
        )


class AdminNewsSourceListCreateView(APIView):
    """管理员外部资讯来源列表和创建。"""

    authentication_classes: ClassVar[list[type[BaseAuthentication]]] = [BearerTokenAuthentication]
    permission_classes: ClassVar[list[type[BasePermission]]] = [IsAdminUser]

    @extend_schema(
        summary="获取资讯来源",
        operation_id="listAdminNewsSources",
        responses={200: NewsSourceResponseSerializer(many=True)},
    )
    def get(self, request: Request) -> Response:
        return Response(list_news_sources())

    @extend_schema(
        summary="创建资讯来源",
        operation_id="createAdminNewsSource",
        request=NewsSourceInputSerializer,
        responses={201: NewsSourceResponseSerializer},
    )
    def post(self, request: Request) -> Response:
        serializer = NewsSourceInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return Response(create_news_source(payload=serializer.validated_data), status=201)


class AdminNewsSourceDetailView(APIView):
    """管理员更新外部资讯来源配置。"""

    authentication_classes: ClassVar[list[type[BaseAuthentication]]] = [BearerTokenAuthentication]
    permission_classes: ClassVar[list[type[BasePermission]]] = [IsAdminUser]

    @extend_schema(
        summary="更新资讯来源",
        operation_id="updateAdminNewsSource",
        request=NewsSourceInputSerializer,
        responses={200: NewsSourceResponseSerializer},
    )
    def patch(self, request: Request, source_code: str) -> Response:
        serializer = NewsSourceInputSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        return Response(
            update_news_source(
                source_code=source_code,
                payload=serializer.validated_data,
            )
        )


class AdminNewsSyncView(APIView):
    """管理员一键获取最新资讯。"""

    authentication_classes: ClassVar[list[type[BaseAuthentication]]] = [BearerTokenAuthentication]
    permission_classes: ClassVar[list[type[BasePermission]]] = [IsAdminUser]

    @extend_schema(
        summary="同步外部最新资讯",
        operation_id="syncAdminNews",
        request=NewsSyncRequestSerializer,
        responses={202: NewsSyncRunResponseSerializer},
    )
    def post(self, request: Request) -> Response:
        serializer = NewsSyncRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        payload = dict(serializer.validated_data)
        source_codes = list(payload.pop("source_codes", []))
        return Response(
            create_news_sync_run(
                user=request.user,
                source_codes=source_codes,
                filters=payload,
            ),
            status=202,
        )


class AdminNewsSyncDetailView(APIView):
    """查询资讯同步任务状态。"""

    authentication_classes: ClassVar[list[type[BaseAuthentication]]] = [BearerTokenAuthentication]
    permission_classes: ClassVar[list[type[BasePermission]]] = [IsAdminUser]

    @extend_schema(
        summary="查询资讯同步状态",
        operation_id="retrieveAdminNewsSync",
        responses={200: NewsSyncRunResponseSerializer},
    )
    def get(self, request: Request, run_no: str) -> Response:
        return Response(get_news_sync_run(run_no))
