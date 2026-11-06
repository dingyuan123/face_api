"""关注、收藏、动态点赞和动态评论业务服务。"""

from __future__ import annotations

from typing import Any

from django.db import IntegrityError, transaction
from django.db.models import F
from django.http import HttpRequest
from django.utils import timezone

from backend.accounts.models import User
from backend.catalog.models import ProviderService
from backend.common.context import current_trace_id
from backend.common.errors import ERROR_MESSAGES, ErrorCode
from backend.common.exceptions import ApiError
from backend.content.models import Moment
from backend.media.services import get_media_payloads
from backend.social.models import (
    Comment,
    CommentEvent,
    Favorite,
    MomentLike,
    UserFollow,
)


def _invalid(field: str, message: str) -> ApiError:
    return ApiError(
        ErrorCode.SOCIAL_INVALID,
        ERROR_MESSAGES[ErrorCode.SOCIAL_INVALID],
        status_code=400,
        details={field: message},
    )


def social_counts(user: User) -> dict[str, int]:
    """返回当前用户收藏、关注和被关注数量。"""

    return {
        "favorite_count": Favorite.objects.filter(user=user).count(),
        "following_count": UserFollow.objects.filter(follower=user).count(),
        "follower_count": UserFollow.objects.filter(followed=user).count(),
    }


def _get_target_user(public_id: str) -> User:
    user = User.objects.filter(public_id=public_id).first()
    if user is None:
        raise _invalid("user_public_id", "用户不存在")
    return user


def follow_user(*, follower: User, followed_public_id: str) -> dict[str, Any]:
    """关注服务者，重复请求返回同一关系。"""

    followed = _get_target_user(followed_public_id)
    if follower.id == followed.id:
        raise _invalid("followed_public_id", "不能关注自己")
    with transaction.atomic():
        follow, _ = UserFollow.objects.get_or_create(follower=follower, followed=followed)
        return {
            "is_following": True,
            "followed_user_public_id": str(followed.public_id),
            "created_at": follow.created_at,
        }


def unfollow_user(*, follower: User, followed_public_id: str) -> dict[str, Any]:
    """取消关注，重复请求返回稳定结果。"""

    followed = _get_target_user(followed_public_id)
    UserFollow.objects.filter(follower=follower, followed=followed).delete()
    return {
        "is_following": False,
        "followed_user_public_id": str(followed.public_id),
    }


def _validate_favorite_target(target_type: str, target_id: str) -> None:
    if target_type not in Favorite.TargetType.values:
        raise _invalid("target_type", "收藏目标类型不正确")
    if target_type == Favorite.TargetType.PROVIDER:
        exists = User.objects.filter(public_id=target_id, provider_enabled=True).exists()
    elif target_type == Favorite.TargetType.SERVICE:
        exists = ProviderService.objects.filter(
            public_id=target_id,
            deleted_at__isnull=True,
            status=ProviderService.Status.ONLINE,
        ).exists()
    elif target_type == Favorite.TargetType.MOMENT:
        exists = Moment.objects.filter(
            public_id=target_id,
            status=Moment.Status.PUBLISHED,
            visibility=Moment.Visibility.PUBLIC,
            deleted_at__isnull=True,
        ).exists()
    else:
        from backend.content.news_services import favorite_news_exists

        exists = favorite_news_exists(target_id)
    if not exists:
        raise _invalid("target_id", "收藏目标不存在或不可见")


def create_favorite(*, user: User, target_type: str, target_id: str) -> dict[str, Any]:
    """收藏服务者、服务、动态或资讯。"""

    _validate_favorite_target(target_type, target_id)
    favorite, _ = Favorite.objects.get_or_create(
        user=user,
        target_type=target_type,
        target_id=target_id,
    )
    return {
        "is_favorited": True,
        "target_type": favorite.target_type,
        "target_id": str(favorite.target_id),
        "created_at": favorite.created_at,
    }


def remove_favorite(*, user: User, target_type: str, target_id: str) -> dict[str, Any]:
    """取消收藏。"""

    _validate_favorite_target(target_type, target_id)
    Favorite.objects.filter(
        user=user,
        target_type=target_type,
        target_id=target_id,
    ).delete()
    return {
        "is_favorited": False,
        "target_type": target_type,
        "target_id": target_id,
    }


def like_moment(*, user: User, moment_id: str) -> dict[str, Any]:
    """点赞已发布公开动态。"""

    moment = Moment.objects.filter(
        public_id=moment_id,
        status=Moment.Status.PUBLISHED,
        visibility=Moment.Visibility.PUBLIC,
        deleted_at__isnull=True,
    ).first()
    if moment is None:
        raise _invalid("moment_id", "动态不存在或不可见")
    with transaction.atomic():
        _like, created = MomentLike.objects.get_or_create(user=user, moment=moment)
        if created:
            Moment.objects.filter(pk=moment.pk).update(like_count=F("like_count") + 1)
        return {
            "is_liked": True,
            "moment_id": str(moment.public_id),
            "like_count": moment.like_count + int(created),
        }


def unlike_moment(*, user: User, moment_id: str) -> dict[str, Any]:
    """取消点赞动态。"""

    moment = Moment.objects.filter(public_id=moment_id, deleted_at__isnull=True).first()
    if moment is None:
        raise _invalid("moment_id", "动态不存在")
    with transaction.atomic():
        deleted, _ = MomentLike.objects.filter(user=user, moment=moment).delete()
        if deleted:
            Moment.objects.filter(pk=moment.pk).update(like_count=F("like_count") - 1)
        return {
            "is_liked": False,
            "moment_id": str(moment.public_id),
            "like_count": max(0, moment.like_count - int(deleted)),
        }


def create_comment(
    *,
    user: User,
    moment_id: str,
    content: str,
    request: HttpRequest | None = None,
) -> dict[str, Any]:
    """创建动态一级评论。"""

    moment = Moment.objects.filter(
        public_id=moment_id,
        status=Moment.Status.PUBLISHED,
        visibility=Moment.Visibility.PUBLIC,
        deleted_at__isnull=True,
    ).first()
    if moment is None:
        raise _invalid("moment_id", "动态不存在或不可见")
    text = content.strip()
    if not 1 <= len(text) <= 1000:
        raise _invalid("content", "评论必须为 1 到 1000 个字符")
    try:
        with transaction.atomic():
            comment = Comment.objects.create(moment=moment, user=user, content=text)
            CommentEvent.objects.create(
                comment=comment,
                event_type=CommentEvent.EventType.CREATED,
                actor_user_id=user.id,
                trace_id=current_trace_id(),
            )
            Moment.objects.filter(pk=moment.pk).update(comment_count=F("comment_count") + 1)
            return comment_payload(comment, request)
    except IntegrityError as exc:
        raise _invalid("content", "评论创建失败") from exc


def delete_comment(*, user: User, comment_id: str) -> None:
    """逻辑删除本人评论。"""

    with transaction.atomic():
        comment = (
            Comment.objects.select_for_update()
            .filter(
                public_id=comment_id,
                deleted_at__isnull=True,
            )
            .first()
        )
        if comment is None:
            raise _invalid("comment_id", "评论不存在")
        if comment.user_id != user.id:
            raise ApiError(
                ErrorCode.AUTH_PERMISSION_DENIED,
                ERROR_MESSAGES[ErrorCode.AUTH_PERMISSION_DENIED],
                status_code=403,
            )
        comment.status = Comment.Status.DELETED
        comment.deleted_at = timezone.now()
        comment.version += 1
        comment.save(update_fields=["status", "deleted_at", "version", "updated_at"])
        CommentEvent.objects.create(
            comment=comment,
            event_type=CommentEvent.EventType.DELETED,
            actor_user_id=user.id,
            trace_id=current_trace_id(),
        )
        Moment.objects.filter(pk=comment.moment_id).update(comment_count=F("comment_count") - 1)


def comment_payloads(
    comments: list[Comment],
    request: HttpRequest | None = None,
) -> list[dict[str, Any]]:
    """批量返回评论安全摘要和评论用户公开资料。"""

    if not comments:
        return []
    avatar_media_ids = [
        avatar_media_id
        for avatar_media_id in {
            getattr(getattr(comment.user, "profile", None), "avatar_media_id", None)
            for comment in comments
        }
        if avatar_media_id
    ]
    avatar_payloads = {
        payload["media_id"]: payload for payload in get_media_payloads(avatar_media_ids, request)
    }
    payloads = []
    for comment in comments:
        user_profile = getattr(comment.user, "profile", None)
        avatar_media_id = getattr(user_profile, "avatar_media_id", None)
        payloads.append(
            {
                "id": str(comment.public_id),
                "content": comment.content,
                "user_public_id": str(comment.user.public_id),
                "user": {
                    "public_id": str(comment.user.public_id),
                    "nickname": getattr(user_profile, "nickname", None),
                    "avatar_media": avatar_payloads.get(avatar_media_id),
                },
                "moment_id": str(comment.moment.public_id),
                "created_at": comment.created_at,
            }
        )
    return payloads


def comment_payload(comment: Comment, request: HttpRequest | None = None) -> dict[str, Any]:
    """返回单条评论安全摘要。"""

    return comment_payloads([comment], request)[0]
