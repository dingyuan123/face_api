"""首页服务者卡片聚合查询业务服务。"""

from __future__ import annotations

from typing import Any

from django.conf import settings
from django.db.models import Count, Min, Q, Sum
from django.http import HttpRequest

from backend.catalog.models import ProviderService, ServiceCategory
from backend.common.errors import ERROR_MESSAGES, ErrorCode
from backend.common.exceptions import ApiError
from backend.content.models import Moment
from backend.media.services import get_media_payloads, get_recent_media_payloads
from backend.providers.models import ProviderProfile


def _invalid(field: str, message: str) -> ApiError:
    return ApiError(
        ErrorCode.HOME_FEED_INVALID,
        ERROR_MESSAGES[ErrorCode.HOME_FEED_INVALID],
        status_code=400,
        details={field: message},
    )


def home_feed_queryset(
    *,
    city_code: str,
    category_code: str | None,
    sort: str,
):
    """构建只包含有已上架服务的服务者首页查询。"""

    allowed_sorts = {"RECOMMENDED", "NEWEST", "PRICE_ASC", "PRICE_DESC"}
    if sort not in allowed_sorts:
        raise _invalid("sort", "排序方式不存在")
    if (
        category_code
        and not ServiceCategory.objects.filter(
            code=category_code,
            is_active=True,
        ).exists()
    ):
        raise _invalid("category_code", "服务类目不存在或已停用")

    queryset = (
        ProviderProfile.objects.select_related("user", "user__profile")
        .prefetch_related(
            "photo_links",
            "category_links",
            "user__provider_applications",
            "user__identity_verifications",
            "user__provider_services__gallery_links",
            "user__moments__media_links",
        )
        .annotate(
            online_service_count=Count(
                "user__provider_services",
                filter=Q(
                    user__provider_services__status=ProviderService.Status.ONLINE,
                    user__provider_services__deleted_at__isnull=True,
                ),
                distinct=True,
            ),
            min_price=Min(
                "user__provider_services__price_amount_minor",
                filter=Q(
                    user__provider_services__status=ProviderService.Status.ONLINE,
                    user__provider_services__deleted_at__isnull=True,
                ),
            ),
            sold_count=Sum(
                "user__provider_services__sold_count",
                filter=Q(
                    user__provider_services__status=ProviderService.Status.ONLINE,
                    user__provider_services__deleted_at__isnull=True,
                ),
            ),
        )
        .filter(
            user__provider_enabled=True,
            user__provider_status="APPROVED",
            user__profile__city_code=city_code,
            online_service_count__gt=0,
        )
    )
    if category_code:
        queryset = queryset.filter(
            user__provider_services__status=ProviderService.Status.ONLINE,
            user__provider_services__deleted_at__isnull=True,
            user__provider_services__category_id=category_code,
        )
    ordering = {
        "RECOMMENDED": ("-online_service_count", "-sold_count", "-updated_at", "-id"),
        "NEWEST": ("-updated_at", "-id"),
        "PRICE_ASC": ("min_price", "id"),
        "PRICE_DESC": ("-min_price", "-id"),
    }[sort]
    return queryset.order_by(*ordering)


def _related_media_ids(profile: ProviderProfile) -> list[str]:
    media_ids = [link.media_id for link in profile.photo_links.all()]
    media_ids.extend(
        media_id
        for moment in profile.user.moments.all()
        if moment.status == Moment.Status.PUBLISHED and not moment.deleted_at
        for media_id in [
            moment.cover_media_id,
            *(link.media_id for link in moment.media_links.all()),
        ]
        if media_id
    )
    media_ids.extend(
        media_id
        for application in profile.user.provider_applications.all()
        for media_id in application.life_photo_media_ids
    )
    for service in profile.user.provider_services.all():
        if service.status != ProviderService.Status.ONLINE or service.deleted_at:
            continue
        media_ids.append(service.cover_media_id)
        media_ids.extend(link.media_id for link in service.gallery_links.all())
    if profile.avatar_media_id:
        media_ids.append(profile.avatar_media_id)
    return list(dict.fromkeys(media_ids))


def home_card_payload(
    profile: ProviderProfile,
    request: HttpRequest | None = None,
) -> dict[str, Any]:
    """生成首页服务者卡片，照片只返回最近 3 到 5 张相关媒体。"""

    user = profile.user
    user_profile = getattr(user, "profile", None)
    online_services = [
        service
        for service in user.provider_services.all()
        if service.status == ProviderService.Status.ONLINE and not service.deleted_at
    ]
    avatar_media = (
        get_media_payloads([profile.avatar_media_id], request) if profile.avatar_media_id else []
    )
    recent_media = get_recent_media_payloads(
        _related_media_ids(profile),
        request,
        limit=settings.HOME_FEED_RECENT_PHOTO_COUNT,
    )
    verification = {
        "real_name_status": "NOT_SUBMITTED",
        "face_status": "NOT_SUBMITTED",
    }
    for item in user.identity_verifications.all():
        if item.verification_type == "REAL_NAME":
            verification["real_name_status"] = item.status
        if item.verification_type == "FACE":
            verification["face_status"] = item.status
    return {
        "provider_public_id": str(user.public_id),
        "provider": {
            "nickname": profile.nickname,
            "age": user_profile.age if user_profile else None,
            "gender": user_profile.gender if user_profile else None,
            "city_code": user_profile.city_code if user_profile else None,
            "signature": profile.signature,
            "avatar_media": avatar_media[0] if avatar_media else None,
        },
        "category_codes": [link.category_code for link in profile.category_links.all()],
        "recent_photo_media": recent_media,
        "recent_photo_count": len(recent_media),
        "services": [
            {
                "id": str(service.public_id),
                "title": service.title,
                "category_code": service.category.code,
                "price": {
                    "currency": service.currency,
                    "amount_minor": service.price_amount_minor,
                },
                "duration_minutes": service.duration_minutes,
            }
            for service in online_services[: settings.HOME_FEED_SERVICE_COUNT]
        ],
        "verification": verification,
        "online_status": "UNKNOWN",
        "distance_km": None,
        "rating": None,
    }


def home_feed_payloads(
    profiles: list[ProviderProfile],
    request: HttpRequest | None = None,
) -> list[dict[str, Any]]:
    """为当前页服务者生成首页卡片。"""

    return [home_card_payload(profile, request) for profile in profiles]
