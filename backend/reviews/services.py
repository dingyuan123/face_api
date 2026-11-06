"""订单评价、评价标签、服务者评价管理和评分聚合业务服务。"""

from __future__ import annotations

from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from django.db import IntegrityError, transaction
from django.db.models import Q, QuerySet
from django.http import HttpRequest
from django.utils import timezone

from backend.accounts.models import User
from backend.catalog.services import format_price_amount
from backend.common.errors import ERROR_MESSAGES, ErrorCode
from backend.common.exceptions import ApiError
from backend.media.services import get_media_payloads
from backend.orders.models import Order
from backend.providers.models import ProviderApplication
from backend.reviews.models import (
    ProviderRatingStat,
    Review,
    ReviewReply,
    ReviewTag,
    ReviewTagLink,
)


def _invalid(field: str, message: str) -> ApiError:
    """构造统一的评价参数错误。"""

    return ApiError(
        ErrorCode.REVIEW_INVALID,
        ERROR_MESSAGES[ErrorCode.REVIEW_INVALID],
        status_code=400,
        details={field: message},
    )


def provider_rating_summary(provider_user: User) -> dict[str, Any]:
    """返回服务者评分聚合的对外展示值。"""

    stat = ProviderRatingStat.objects.filter(provider_user=provider_user).first()
    return {
        "rating_average": f"{stat.rating_average:.2f}" if stat else "0.00",
        "review_count": stat.review_count if stat else 0,
    }


def _service_summary(
    order: Order | None,
    media_payloads: dict[str, dict[str, Any]],
) -> dict[str, Any] | None:
    """根据订单历史快照返回评价关联服务的完整安全摘要。

    服务可能被删除或下架，因此价格、时长和介绍均读取下单时快照，不依赖当前服务状态。
    """

    if order is None:
        return None
    snapshot = order.service_snapshot or {}
    cover_media_id = snapshot.get("cover_media_id")
    return {
        "id": snapshot.get("id") or snapshot.get("service_id"),
        "title": snapshot.get("title") or "历史服务",
        "category_code": snapshot.get("category_code"),
        "price": {
            "currency": snapshot.get("currency") or "CNY",
            "amount_minor": snapshot.get("hourly_amount_minor") or 0,
            "display": format_price_amount(
                int(snapshot.get("hourly_amount_minor") or 0),
                snapshot.get("currency") or "CNY",
            ),
        },
        "duration_minutes": snapshot.get("duration_minutes"),
        "introduction": snapshot.get("introduction") or "",
        "cover_media": media_payloads.get(str(cover_media_id)) if cover_media_id else None,
    }


def _provider_summary(
    provider_user: User,
    media_payloads: dict[str, dict[str, Any]],
    request: HttpRequest | None = None,
) -> dict[str, Any]:
    """返回服务者资料、认证状态和履约评分摘要。"""

    provider_profile = getattr(provider_user, "provider_profile", None)
    avatar_media_id = getattr(provider_profile, "avatar_media_id", None)
    if not avatar_media_id:
        avatar_media_id = (
            ProviderApplication.objects.filter(user=provider_user)
            .order_by("-submitted_at")
            .values_list("avatar_media_id", flat=True)
            .first()
        )
    if avatar_media_id and str(avatar_media_id) not in media_payloads:
        media_payloads.update(
            {
                payload["media_id"]: payload
                for payload in get_media_payloads([avatar_media_id], request)
            }
        )
    application = (
        ProviderApplication.objects.filter(user=provider_user)
        .order_by("-submitted_at")
        .only("real_name_status", "face_status")
        .first()
    )
    return {
        "public_id": str(provider_user.public_id),
        "nickname": getattr(provider_profile, "nickname", None),
        "avatar_media": media_payloads.get(str(avatar_media_id)) if avatar_media_id else None,
        "verification": {
            "real_name_status": (application.real_name_status if application else "NOT_SUBMITTED"),
            "face_status": application.face_status if application else "NOT_SUBMITTED",
        },
        "rating": provider_rating_summary(provider_user),
        "completed_order_count": Order.objects.filter(
            provider_user=provider_user,
            status=Order.Status.COMPLETED,
        ).count(),
    }


def review_payload(
    review: Review,
    request: HttpRequest | None = None,
) -> dict[str, Any]:
    """返回评价安全摘要；匿名评价不返回评价用户昵称和头像。"""

    order = Order.objects.filter(order_no=review.order_no).select_related("service").first()
    reviewer_profile = getattr(review.user, "profile", None)
    reviewer_avatar_id = getattr(reviewer_profile, "avatar_media_id", None)
    provider_avatar_id = getattr(
        getattr(review.provider_user, "provider_profile", None),
        "avatar_media_id",
        None,
    )
    service_cover_id = (order.service_snapshot or {}).get("cover_media_id") if order else None
    media_ids = [
        media_id
        for media_id in {reviewer_avatar_id, provider_avatar_id, service_cover_id}
        if media_id
    ]
    media_payloads = {
        payload["media_id"]: payload for payload in get_media_payloads(media_ids, request)
    }
    latest_reply = review.replies.order_by("-created_at", "-id").first()
    reviewer = None
    if not review.is_anonymous:
        reviewer = {
            "public_id": str(review.user.public_id),
            "nickname": getattr(reviewer_profile, "nickname", None),
            "avatar_media": media_payloads.get(str(reviewer_avatar_id))
            if reviewer_avatar_id
            else None,
        }
    return {
        "id": str(review.public_id),
        "order_no": str(review.order_no),
        "rating": review.rating,
        "content": review.content,
        "is_anonymous": review.is_anonymous,
        "tag_codes": [link.tag.code for link in review.tag_links.all()],
        "service": _service_summary(order, media_payloads),
        "provider": _provider_summary(review.provider_user, media_payloads, request),
        "provider_public_id": str(review.provider_user.public_id),
        "user_public_id": None if review.is_anonymous else str(review.user.public_id),
        "user": reviewer,
        "reply": {
            "id": latest_reply.id,
            "content": latest_reply.content,
            "created_at": latest_reply.created_at,
        }
        if latest_reply
        else None,
        "has_reply": latest_reply is not None,
        "review_expires_at": review.review_expires_at,
        "created_at": review.created_at,
        "updated_at": review.updated_at,
    }


def _request_matches_review(
    review: Review,
    *,
    rating: int,
    content: str,
    tag_codes: list[str],
    is_anonymous: bool,
) -> bool:
    """判断重复评价请求是否与首次请求一致。"""

    current_tags = [link.tag.code for link in review.tag_links.all()]
    return (
        review.rating == rating
        and review.content == content
        and set(current_tags) == set(tag_codes)
        and review.is_anonymous == is_anonymous
    )


def create_review(
    *,
    user: User,
    order_no: str,
    rating: int,
    content: str,
    tag_codes: list[str],
    is_anonymous: bool,
    request: HttpRequest | None = None,
) -> dict[str, Any]:
    """为已完成订单创建用户评价，并安全返回重复请求结果。"""

    if not 1 <= rating <= 5:
        raise _invalid("rating", "评分必须在 1 到 5 之间")
    text = content.strip()
    if len(text) > 1000:
        raise _invalid("content", "评价内容不能超过 1000 个字符")
    normalized_tags = [str(code).strip() for code in tag_codes]
    if len(normalized_tags) > 5:
        raise _invalid("tag_codes", "最多选择 5 个评价标签")
    if len(set(normalized_tags)) != len(normalized_tags):
        raise _invalid("tag_codes", "评价标签不能重复")
    with transaction.atomic():
        order = (
            Order.objects.select_for_update()
            .select_related("user", "provider_user")
            .filter(order_no=order_no, user=user)
            .first()
        )
        if order is None:
            raise ApiError(
                ErrorCode.ORDER_NOT_FOUND,
                ERROR_MESSAGES[ErrorCode.ORDER_NOT_FOUND],
                status_code=404,
            )
        if order.status != Order.Status.COMPLETED or order.completed_at is None:
            raise ApiError(
                ErrorCode.REVIEW_STATE_INVALID,
                ERROR_MESSAGES[ErrorCode.REVIEW_STATE_INVALID],
                status_code=409,
            )
        if order.review_expires_at and timezone.now() > order.review_expires_at:
            raise ApiError(
                ErrorCode.REVIEW_WINDOW_EXPIRED,
                ERROR_MESSAGES[ErrorCode.REVIEW_WINDOW_EXPIRED],
                status_code=410,
            )
        existing = Review.objects.filter(order_no=order.order_no).first()
        if existing:
            if _request_matches_review(
                existing,
                rating=rating,
                content=text,
                tag_codes=normalized_tags,
                is_anonymous=is_anonymous,
            ):
                return review_payload(existing, request)
            raise _invalid("order_no", "该订单已经评价，且本次评价内容与原请求不一致")
        active_tags = {}
        if normalized_tags:
            active_tags = {
                tag.code: tag
                for tag in ReviewTag.objects.filter(code__in=normalized_tags, is_active=True)
            }
            if len(active_tags) != len(normalized_tags):
                raise _invalid("tag_codes", "评价标签不存在或已停用")
        review = Review.objects.create(
            order_no=order.order_no,
            user=user,
            provider_user=order.provider_user,
            rating=rating,
            content=text,
            is_anonymous=is_anonymous,
            review_expires_at=order.review_expires_at,
        )
        if normalized_tags:
            ReviewTagLink.objects.bulk_create(
                [ReviewTagLink(review=review, tag=active_tags[code]) for code in normalized_tags]
            )
        stat, _ = ProviderRatingStat.objects.get_or_create(provider_user=order.provider_user)
        stat.review_count += 1
        stat.rating_sum += rating
        stat.rating_average = (Decimal(stat.rating_sum) / Decimal(stat.review_count)).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )
        stat.save(update_fields=["review_count", "rating_sum", "rating_average", "updated_at"])
        return review_payload(review, request)
    return review_payload(existing, request)


def get_order_review(
    *,
    user: User,
    order_no: str,
    request: HttpRequest | None = None,
) -> dict[str, Any] | None:
    """返回当前用户指定订单的评价。"""

    review = Review.objects.filter(order_no=order_no, user=user).first()
    return review_payload(review, request) if review else None


def _order_service_summary(
    order: Order,
    request: HttpRequest | None = None,
) -> dict[str, Any]:
    """返回订单历史服务完整摘要和封面短期地址。"""

    snapshot = order.service_snapshot or {}
    cover_media_id = snapshot.get("cover_media_id")
    media_payloads = {
        payload["media_id"]: payload
        for payload in get_media_payloads([cover_media_id] if cover_media_id else [], request)
    }
    return _service_summary(order, media_payloads)


def list_my_reviews(
    *,
    user: User,
    status: str = "ALL",
    page: int = 1,
    page_size: int = 20,
    request: HttpRequest | None = None,
) -> dict[str, Any]:
    """返回当前用户待评价订单和历史评价，供“我的评价”页面使用。"""

    if status not in {"ALL", "PENDING", "REVIEWED"}:
        raise _invalid("status", "状态只支持 ALL、PENDING 或 REVIEWED")
    review_orders = {
        str(review.order_no)
        for review in Review.objects.filter(user=user, status=Review.Status.VISIBLE)
    }
    order_queryset = Order.objects.filter(
        user=user,
        status=Order.Status.COMPLETED,
        completed_at__isnull=False,
    ).select_related("service")
    items = []
    if status in {"ALL", "PENDING"}:
        for order in order_queryset.exclude(order_no__in=review_orders).filter(
            Q(review_expires_at__isnull=True) | Q(review_expires_at__gt=timezone.now())
        ):
            items.append(
                {
                    "item_type": "PENDING_REVIEW",
                    "status": "PENDING",
                    "order_no": str(order.order_no),
                    "service": _order_service_summary(order, request),
                    "provider": _provider_summary(
                        order.provider_user,
                        {},
                        request,
                    ),
                    "review": None,
                    "review_deadline": order.review_expires_at,
                    "created_at": order.completed_at,
                }
            )
    if status in {"ALL", "REVIEWED"}:
        reviews = (
            Review.objects.filter(user=user, status=Review.Status.VISIBLE)
            .select_related("user", "provider_user")
            .prefetch_related("tag_links__tag", "replies")
            .order_by("-created_at", "-id")
        )
        for review in reviews:
            payload = review_payload(review, request)
            items.append(
                {
                    "item_type": "REVIEWED",
                    "status": "REVIEWED",
                    "order_no": str(review.order_no),
                    "service": payload.get("service"),
                    "provider": payload.get("provider"),
                    "review": payload,
                    "review_deadline": review.review_expires_at,
                    "created_at": review.created_at,
                }
            )
    items.sort(key=lambda item: item["created_at"] or timezone.now(), reverse=True)
    start = max(0, (page - 1) * page_size)
    return {
        "items": items[start : start + page_size],
        "total": len(items),
        "page": page,
        "page_size": page_size,
        "summary": {
            "pending_count": sum(item["item_type"] == "PENDING_REVIEW" for item in items),
            "reviewed_count": sum(item["item_type"] == "REVIEWED" for item in items),
        },
    }


def _parse_review_date(value: str | None, field: str) -> datetime | None:
    """解析评价筛选日期，支持日期或 ISO 时间。"""

    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise _invalid(field, "日期格式不正确") from exc
    return timezone.make_aware(parsed) if parsed.tzinfo is None else parsed


def _provider_review_queryset(provider_user: User) -> QuerySet[Review]:
    return (
        Review.objects.filter(provider_user=provider_user, status=Review.Status.VISIBLE)
        .select_related("user", "provider_user")
        .prefetch_related("tag_links__tag", "replies")
    )


def list_provider_review_management(
    *,
    provider_user: User,
    rating: int | None = None,
    has_reply: bool | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    page: int = 1,
    page_size: int = 20,
    request: HttpRequest | None = None,
) -> dict[str, Any]:
    """返回服务者评价管理列表、筛选和评分汇总。"""

    if not provider_user.provider_enabled:
        raise ApiError(
            ErrorCode.PROVIDER_NOT_ENABLED,
            ERROR_MESSAGES[ErrorCode.PROVIDER_NOT_ENABLED],
            status_code=403,
        )
    if rating is not None and not 1 <= rating <= 5:
        raise _invalid("rating", "评分必须在 1 到 5 之间")
    queryset = _provider_review_queryset(provider_user)
    if rating is not None:
        queryset = queryset.filter(rating=rating)
    from_date = _parse_review_date(date_from, "date_from")
    to_date = _parse_review_date(date_to, "date_to")
    if from_date:
        queryset = queryset.filter(created_at__gte=from_date)
    if to_date:
        queryset = queryset.filter(created_at__lte=to_date)
    if has_reply is not None:
        queryset = queryset.filter(replies__isnull=not has_reply)
    queryset = queryset.order_by("-created_at", "-id")
    all_reviews = list(queryset)
    distribution = {str(value): 0 for value in range(1, 6)}
    total_rating = 0
    reply_count = 0
    for review in all_reviews:
        distribution[str(review.rating)] += 1
        total_rating += review.rating
        if review.replies.exists():
            reply_count += 1
    start = max(0, (page - 1) * page_size)
    return {
        "items": [review_payload(item, request) for item in all_reviews[start : start + page_size]],
        "total": len(all_reviews),
        "page": page,
        "page_size": page_size,
        "summary": {
            "average_rating": f"{Decimal(total_rating) / Decimal(len(all_reviews)):.2f}"
            if all_reviews
            else "0.00",
            "review_count": len(all_reviews),
            "reply_count": reply_count,
            "reply_rate": f"{Decimal(reply_count) / Decimal(len(all_reviews)):.2f}"
            if all_reviews
            else "0.00",
            "rating_distribution": distribution,
        },
    }


def get_provider_review_detail(
    *,
    provider_user: User,
    review_id: str,
    request: HttpRequest | None = None,
) -> dict[str, Any]:
    """返回服务者本人收到的单条评价详情。"""

    review = _provider_review_queryset(provider_user).filter(public_id=review_id).first()
    if review is None:
        raise _invalid("review_id", "评价不存在或不可查看")
    return review_payload(review, request)


def list_provider_reviews(
    *,
    provider_public_id: str,
    request: HttpRequest | None = None,
) -> list[dict[str, Any]]:
    """返回公开服务者评价列表，保持公开接口兼容。"""

    reviews = (
        Review.objects.select_related("provider_user")
        .filter(
            provider_user__public_id=provider_public_id,
            status=Review.Status.VISIBLE,
        )
        .order_by("-created_at", "-id")
    )
    return [review_payload(review, request) for review in reviews]


def review_tag_payloads() -> list[dict[str, Any]]:
    """返回启用中的评价标签配置。"""

    return [
        {
            "code": tag.code,
            "name": tag.name,
            "category": tag.category,
            "sort_order": tag.sort_order,
        }
        for tag in ReviewTag.objects.filter(is_active=True)
    ]


def reply_review(
    *,
    provider_user: User,
    review_id: str,
    content: str,
    request: HttpRequest | None = None,
) -> dict[str, Any]:
    """服务者回复本人收到的评价；同一评价只保留一条回复。"""

    if not provider_user.provider_enabled:
        raise ApiError(
            ErrorCode.PROVIDER_NOT_ENABLED,
            ERROR_MESSAGES[ErrorCode.PROVIDER_NOT_ENABLED],
            status_code=403,
        )
    text = content.strip()
    if not 1 <= len(text) <= 500:
        raise _invalid("content", "回复必须为 1 到 500 个字符")
    with transaction.atomic():
        review = (
            Review.objects.select_for_update()
            .filter(
                public_id=review_id,
                provider_user=provider_user,
                status=Review.Status.VISIBLE,
            )
            .first()
        )
        if review is None:
            raise _invalid("review_id", "评价不存在或不可回复")
        existing = review.replies.order_by("-created_at", "-id").first()
        if existing:
            if existing.content == text:
                return review_payload(review, request)
            raise _invalid("content", "该评价已经回复，不能重复修改")
        try:
            ReviewReply.objects.create(review=review, user=provider_user, content=text)
        except IntegrityError as exc:
            raise _invalid("content", "该评价已经回复") from exc
        return review_payload(review, request)
