from __future__ import annotations

from typing import ClassVar

from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework.authentication import BaseAuthentication
from rest_framework.permissions import AllowAny, BasePermission, IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from backend.accounts.authentication import BearerTokenAuthentication
from backend.common.errors import ERROR_MESSAGES, ErrorCode
from backend.common.exceptions import ApiError
from backend.reviews.api.serializers import (
    MyReviewListResponseSerializer,
    ProviderReviewListResponseSerializer,
    ReviewReplyRequestSerializer,
    ReviewReplyResponseSerializer,
    ReviewRequestSerializer,
    ReviewResponseSerializer,
    ReviewTagResponseSerializer,
)
from backend.reviews.services import (
    create_review,
    get_order_review,
    get_provider_review_detail,
    list_my_reviews,
    list_provider_review_management,
    list_provider_reviews,
    reply_review,
    review_tag_payloads,
)


class OrderReviewView(APIView):
    """订单评价查询和创建。"""

    authentication_classes: ClassVar[list[type[BaseAuthentication]]] = [BearerTokenAuthentication]
    permission_classes: ClassVar[list[type[BasePermission]]] = [IsAuthenticated]

    @extend_schema(summary="查询订单评价", responses={200: ReviewResponseSerializer})
    def get(self, request: Request, order_no: str) -> Response:
        return Response(get_order_review(user=request.user, order_no=order_no, request=request))

    @extend_schema(
        summary="提交订单评价",
        request=ReviewRequestSerializer,
        responses={201: ReviewResponseSerializer},
    )
    def post(self, request: Request, order_no: str) -> Response:
        serializer = ReviewRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return Response(
            create_review(
                user=request.user,
                order_no=order_no,
                rating=serializer.validated_data["rating"],
                content=serializer.validated_data.get("content", ""),
                tag_codes=serializer.validated_data.get("tag_codes", []),
                is_anonymous=serializer.validated_data.get("is_anonymous", False),
                request=request,
            ),
            status=201,
        )


class ProviderReviewsView(APIView):
    """公开服务者评价列表。"""

    authentication_classes: ClassVar[list[type[BaseAuthentication]]] = []
    permission_classes: ClassVar[list[type[BasePermission]]] = [AllowAny]

    @extend_schema(
        auth=[],
        summary="查看服务者评价",
        responses={200: ReviewResponseSerializer(many=True)},
    )
    def get(self, request: Request, provider_public_id: str) -> Response:
        return Response(
            list_provider_reviews(provider_public_id=provider_public_id, request=request)
        )


class MyReviewsView(APIView):
    """当前用户待评价订单和历史评价列表。"""

    authentication_classes: ClassVar[list[type[BaseAuthentication]]] = [BearerTokenAuthentication]
    permission_classes: ClassVar[list[type[BasePermission]]] = [IsAuthenticated]

    @extend_schema(
        summary="查询我的评价",
        parameters=[
            OpenApiParameter(
                "status",
                type=str,
                required=False,
                description="ALL、PENDING 或 REVIEWED，默认 ALL",
            ),
            OpenApiParameter("page", type=int, required=False, description="页码"),
            OpenApiParameter("page_size", type=int, required=False, description="每页数量"),
        ],
        responses={200: MyReviewListResponseSerializer},
    )
    def get(self, request: Request) -> Response:
        page, page_size = _page_params(request)
        return Response(
            list_my_reviews(
                user=request.user,
                status=request.query_params.get("status", "ALL"),
                page=page,
                page_size=page_size,
                request=request,
            )
        )


class ProviderReviewManagementListView(APIView):
    """服务者收到的评价管理列表。"""

    authentication_classes: ClassVar[list[type[BaseAuthentication]]] = [BearerTokenAuthentication]
    permission_classes: ClassVar[list[type[BasePermission]]] = [IsAuthenticated]

    @extend_schema(
        operation_id="listProviderReviewManagement",
        summary="查询服务者评价管理列表",
        parameters=[
            OpenApiParameter("rating", type=int, required=False, description="1 到 5 星筛选"),
            OpenApiParameter(
                "has_reply",
                type=bool,
                required=False,
                description="是否已回复筛选",
            ),
            OpenApiParameter(
                "date_from",
                type=str,
                required=False,
                description="评价创建时间下限，ISO 日期或时间",
            ),
            OpenApiParameter(
                "date_to",
                type=str,
                required=False,
                description="评价创建时间上限，ISO 日期或时间",
            ),
            OpenApiParameter("page", type=int, required=False, description="页码"),
            OpenApiParameter("page_size", type=int, required=False, description="每页数量"),
        ],
        responses={200: ProviderReviewListResponseSerializer},
    )
    def get(self, request: Request) -> Response:
        page, page_size = _page_params(request)
        rating_value = request.query_params.get("rating")
        try:
            rating = int(rating_value) if rating_value else None
        except ValueError as exc:
            raise ApiError(
                ErrorCode.REVIEW_INVALID,
                ERROR_MESSAGES[ErrorCode.REVIEW_INVALID],
                status_code=400,
                details={"rating": "评分必须是整数"},
            ) from exc
        has_reply = _optional_bool(request.query_params.get("has_reply"))
        return Response(
            list_provider_review_management(
                provider_user=request.user,
                rating=rating,
                has_reply=has_reply,
                date_from=request.query_params.get("date_from"),
                date_to=request.query_params.get("date_to"),
                page=page,
                page_size=page_size,
                request=request,
            )
        )


class ProviderReviewDetailView(APIView):
    """服务者查看本人收到的评价详情。"""

    authentication_classes: ClassVar[list[type[BaseAuthentication]]] = [BearerTokenAuthentication]
    permission_classes: ClassVar[list[type[BasePermission]]] = [IsAuthenticated]

    @extend_schema(
        operation_id="retrieveProviderReview",
        summary="查询服务者评价详情",
        responses={200: ReviewResponseSerializer},
    )
    def get(self, request: Request, review_id: str) -> Response:
        return Response(
            get_provider_review_detail(
                provider_user=request.user,
                review_id=review_id,
                request=request,
            )
        )


class ProviderReviewReplyView(APIView):
    """服务者回复本人收到的评价。"""

    authentication_classes: ClassVar[list[type[BaseAuthentication]]] = [BearerTokenAuthentication]
    permission_classes: ClassVar[list[type[BasePermission]]] = [IsAuthenticated]

    @extend_schema(
        summary="服务者回复评价",
        request=ReviewReplyRequestSerializer,
        responses={200: ReviewResponseSerializer, 201: ReviewResponseSerializer},
    )
    def post(self, request: Request, review_id: str) -> Response:
        serializer = ReviewReplyRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return Response(
            reply_review(
                provider_user=request.user,
                review_id=review_id,
                content=serializer.validated_data["content"],
                request=request,
            )
        )


class ReviewReplyView(APIView):
    """服务者回复评价。"""

    authentication_classes: ClassVar[list[type[BaseAuthentication]]] = [BearerTokenAuthentication]
    permission_classes: ClassVar[list[type[BasePermission]]] = [IsAuthenticated]

    @extend_schema(
        summary="回复服务评价",
        request=ReviewReplyRequestSerializer,
        responses={201: ReviewReplyResponseSerializer},
    )
    def post(self, request: Request, review_id: str) -> Response:
        serializer = ReviewReplyRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return Response(
            reply_review(
                provider_user=request.user,
                review_id=review_id,
                content=serializer.validated_data["content"],
                request=request,
            ),
            status=201,
        )


class ReviewTagOptionsView(APIView):
    """评价标签配置查询。"""

    authentication_classes: ClassVar[list[type[BaseAuthentication]]] = []
    permission_classes: ClassVar[list[type[BasePermission]]] = [AllowAny]

    @extend_schema(
        auth=[],
        summary="获取评价标签",
        responses={200: ReviewTagResponseSerializer(many=True)},
    )
    def get(self, request: Request) -> Response:
        return Response(review_tag_payloads())


def _page_params(request: Request) -> tuple[int, int]:
    """解析评价列表页码和每页数量。"""

    try:
        page = max(1, int(request.query_params.get("page", 1)))
        page_size = min(100, max(1, int(request.query_params.get("page_size", 20))))
    except ValueError as exc:
        raise ApiError(
            ErrorCode.REVIEW_INVALID,
            ERROR_MESSAGES[ErrorCode.REVIEW_INVALID],
            status_code=400,
            details={"page": "分页参数必须是整数"},
        ) from exc
    return page, page_size


def _optional_bool(value: str | None) -> bool | None:
    """解析可选布尔筛选参数。"""

    if value is None:
        return None
    normalized = value.strip().lower()
    if normalized in {"true", "1", "yes"}:
        return True
    if normalized in {"false", "0", "no"}:
        return False
    raise ApiError(
        ErrorCode.REVIEW_INVALID,
        ERROR_MESSAGES[ErrorCode.REVIEW_INVALID],
        status_code=400,
        details={"has_reply": "布尔参数只能是 true 或 false"},
    )
