from __future__ import annotations

from typing import ClassVar

from drf_spectacular.utils import extend_schema
from rest_framework.authentication import BaseAuthentication
from rest_framework.permissions import BasePermission, IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from backend.accounts.authentication import BearerTokenAuthentication
from backend.common.errors import ERROR_MESSAGES, ErrorCode
from backend.common.exceptions import ApiError
from backend.social.api.serializers import (
    CommentRequestSerializer,
    CommentResponseSerializer,
    FavoriteRequestSerializer,
    FavoriteResponseSerializer,
    FollowResponseSerializer,
    LikeResponseSerializer,
)
from backend.social.models import Comment, Favorite, UserFollow
from backend.social.services import (
    comment_payloads,
    create_comment,
    create_favorite,
    delete_comment,
    follow_user,
    like_moment,
    remove_favorite,
    unfollow_user,
    unlike_moment,
)


class UserFollowView(APIView):
    """关注或取消关注用户。"""

    authentication_classes: ClassVar[list[type[BaseAuthentication]]] = [BearerTokenAuthentication]
    permission_classes: ClassVar[list[type[BasePermission]]] = [IsAuthenticated]

    @extend_schema(
        summary="关注用户",
        request=None,
        responses={200: FollowResponseSerializer},
    )
    def post(self, request: Request, user_public_id: str) -> Response:
        return Response(follow_user(follower=request.user, followed_public_id=user_public_id))

    @extend_schema(
        summary="取消关注用户",
        request=None,
        responses={200: FollowResponseSerializer},
    )
    def delete(self, request: Request, user_public_id: str) -> Response:
        return Response(unfollow_user(follower=request.user, followed_public_id=user_public_id))


class FavoriteView(APIView):
    """收藏或取消收藏目标。"""

    authentication_classes: ClassVar[list[type[BaseAuthentication]]] = [BearerTokenAuthentication]
    permission_classes: ClassVar[list[type[BasePermission]]] = [IsAuthenticated]

    @extend_schema(
        summary="收藏目标",
        request=FavoriteRequestSerializer,
        responses={200: FavoriteResponseSerializer},
    )
    def post(self, request: Request) -> Response:
        serializer = FavoriteRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return Response(
            create_favorite(
                user=request.user,
                target_type=serializer.validated_data["target_type"],
                target_id=str(serializer.validated_data["target_id"]),
            )
        )

    @extend_schema(
        summary="取消收藏目标",
        request=FavoriteRequestSerializer,
        responses={200: FavoriteResponseSerializer},
    )
    def delete(self, request: Request) -> Response:
        serializer = FavoriteRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return Response(
            remove_favorite(
                user=request.user,
                target_type=serializer.validated_data["target_type"],
                target_id=str(serializer.validated_data["target_id"]),
            )
        )


class MomentLikeView(APIView):
    """点赞或取消点赞动态。"""

    authentication_classes: ClassVar[list[type[BaseAuthentication]]] = [BearerTokenAuthentication]
    permission_classes: ClassVar[list[type[BasePermission]]] = [IsAuthenticated]

    @extend_schema(summary="点赞动态", request=None, responses={200: LikeResponseSerializer})
    def post(self, request: Request, moment_id: str) -> Response:
        return Response(like_moment(user=request.user, moment_id=moment_id))

    @extend_schema(summary="取消点赞动态", request=None, responses={200: LikeResponseSerializer})
    def delete(self, request: Request, moment_id: str) -> Response:
        return Response(unlike_moment(user=request.user, moment_id=moment_id))


class MomentCommentsView(APIView):
    """动态评论列表和发表。"""

    authentication_classes: ClassVar[list[type[BaseAuthentication]]] = [BearerTokenAuthentication]
    permission_classes: ClassVar[list[type[BasePermission]]] = [IsAuthenticated]

    @extend_schema(summary="获取动态评论", responses={200: CommentResponseSerializer(many=True)})
    def get(self, request: Request, moment_id: str) -> Response:
        comments = (
            Comment.objects.filter(
                moment__public_id=moment_id,
                status=Comment.Status.VISIBLE,
                deleted_at__isnull=True,
            )
            .select_related("user", "moment")
            .prefetch_related("user__profile")
            .order_by("-created_at", "-id")
        )
        return Response(comment_payloads(list(comments), request))

    @extend_schema(
        summary="发表动态评论",
        request=CommentRequestSerializer,
        responses={201: CommentResponseSerializer},
    )
    def post(self, request: Request, moment_id: str) -> Response:
        serializer = CommentRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return Response(
            create_comment(
                user=request.user,
                moment_id=moment_id,
                content=serializer.validated_data["content"],
                request=request,
            ),
            status=201,
        )


class CommentDeleteView(APIView):
    """删除本人动态评论。"""

    authentication_classes: ClassVar[list[type[BaseAuthentication]]] = [BearerTokenAuthentication]
    permission_classes: ClassVar[list[type[BasePermission]]] = [IsAuthenticated]

    @extend_schema(summary="删除动态评论", responses={200: dict})
    def delete(self, request: Request, comment_id: str) -> Response:
        delete_comment(user=request.user, comment_id=comment_id)
        return Response({"deleted": True})


class FollowingListView(APIView):
    """当前用户关注列表。"""

    authentication_classes: ClassVar[list[type[BaseAuthentication]]] = [BearerTokenAuthentication]
    permission_classes: ClassVar[list[type[BasePermission]]] = [IsAuthenticated]

    @extend_schema(summary="查看我关注的用户", responses={200: FollowResponseSerializer(many=True)})
    def get(self, request: Request) -> Response:
        return Response(
            [
                {
                    "is_following": True,
                    "followed_user_public_id": str(item.followed.public_id),
                    "created_at": item.created_at,
                }
                for item in UserFollow.objects.filter(follower=request.user).select_related(
                    "followed"
                )
            ]
        )


class FavoriteListView(APIView):
    """当前用户收藏列表。"""

    authentication_classes: ClassVar[list[type[BaseAuthentication]]] = [BearerTokenAuthentication]
    permission_classes: ClassVar[list[type[BasePermission]]] = [IsAuthenticated]

    @extend_schema(
        summary="查看我的收藏",
        parameters=[],
        responses={200: FavoriteResponseSerializer(many=True)},
    )
    def get(self, request: Request) -> Response:
        target_type = request.query_params.get("target_type")
        if target_type and target_type not in Favorite.TargetType.values:
            raise ApiError(
                ErrorCode.SOCIAL_INVALID,
                ERROR_MESSAGES[ErrorCode.SOCIAL_INVALID],
                status_code=400,
                details={"target_type": "收藏目标类型不正确"},
            )
        queryset = Favorite.objects.filter(user=request.user)
        if target_type:
            queryset = queryset.filter(target_type=target_type)
        return Response(
            [
                {
                    "is_favorited": True,
                    "target_type": item.target_type,
                    "target_id": str(item.target_id),
                    "created_at": item.created_at,
                }
                for item in queryset.order_by("-created_at")
            ]
        )
