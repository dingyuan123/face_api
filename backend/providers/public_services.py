"""服务者公开资料页聚合查询业务服务。"""

from __future__ import annotations

from typing import Any

from django.db.models import Q
from django.http import HttpRequest

from backend.accounts.models import User
from backend.catalog.models import ProviderService
from backend.catalog.services import service_payload
from backend.common.errors import ERROR_MESSAGES, ErrorCode
from backend.common.exceptions import ApiError
from backend.content.models import Moment
from backend.content.services import moment_payload
from backend.media.services import get_media_payloads
from backend.providers.models import ProviderProfile
from backend.reviews.models import ProviderRatingStat
from backend.social.models import Favorite, UserFollow


def provider_search_queryset(*, keyword: str):
    """构建公开服务者关键词查询，搜索资料、在线服务、类目和标签但不泄露私有数据。"""

    search = keyword.strip()
    return (
        ProviderProfile.objects.select_related("user", "user__profile")
        .prefetch_related(
            "photo_links",
            "category_links",
            "user__provider_applications",
            "user__identity_verifications",
            "user__provider_services__gallery_links",
            "user__provider_services__tag_links__tag",
            "user__moments__media_links",
        )
        .filter(
            user__provider_enabled=True,
            user__provider_status=User.ProviderStatus.APPROVED,
        )
        .filter(
            Q(nickname__icontains=search)
            | Q(signature__icontains=search)
            | Q(introduction__icontains=search)
            | Q(category_links__category_code__icontains=search)
            | Q(tag_links__tag_code__icontains=search)
            | Q(
                user__provider_services__title__icontains=search,
                user__provider_services__status=ProviderService.Status.ONLINE,
                user__provider_services__deleted_at__isnull=True,
            )
            | Q(
                user__provider_services__introduction__icontains=search,
                user__provider_services__status=ProviderService.Status.ONLINE,
                user__provider_services__deleted_at__isnull=True,
            )
            | Q(
                user__provider_services__category__name__icontains=search,
                user__provider_services__status=ProviderService.Status.ONLINE,
                user__provider_services__deleted_at__isnull=True,
            )
            | Q(
                user__provider_services__tag_links__tag__name__icontains=search,
                user__provider_services__status=ProviderService.Status.ONLINE,
                user__provider_services__deleted_at__isnull=True,
            )
        )
        .distinct()
        .order_by("-updated_at", "-id")
    )


def provider_public_payload(
    *,
    provider_public_id: str,
    viewer: User | None = None,
    request: HttpRequest | None = None,
) -> dict[str, Any]:
    """返回公开服务者资料、已上架服务和已发布动态。"""

    profile = (
        ProviderProfile.objects.select_related("user", "user__profile")
        .filter(
            user__public_id=provider_public_id,
            user__provider_enabled=True,
            user__provider_status=User.ProviderStatus.APPROVED,
        )
        .first()
    )
    if profile is None:
        raise ApiError(
            ErrorCode.PROVIDER_PROFILE_NOT_FOUND,
            ERROR_MESSAGES[ErrorCode.PROVIDER_PROFILE_NOT_FOUND],
            status_code=404,
        )
    user_profile = getattr(profile.user, "profile", None)
    photo_ids = [link.media_id for link in profile.photo_links.all().order_by("position", "id")]
    services = [
        service_payload(item, request)
        for item in ProviderService.objects.filter(
            provider_user=profile.user,
            status=ProviderService.Status.ONLINE,
            deleted_at__isnull=True,
        ).select_related("category")
    ]
    moments = [
        moment_payload(item, request, viewer)
        for item in Moment.objects.filter(
            provider_user=profile.user,
            status=Moment.Status.PUBLISHED,
            visibility=Moment.Visibility.PUBLIC,
            deleted_at__isnull=True,
        ).order_by("-published_at", "-id")[:10]
    ]
    avatar_media = (
        get_media_payloads([profile.avatar_media_id], request) if profile.avatar_media_id else []
    )
    follower_count = UserFollow.objects.filter(followed=profile.user).count()
    favorite_count = Favorite.objects.filter(
        target_type=Favorite.TargetType.PROVIDER,
        target_id=profile.user.public_id,
    ).count()
    rating_stat = ProviderRatingStat.objects.filter(provider_user=profile.user).first()
    return {
        "provider": {
            "public_id": str(profile.user.public_id),
            "nickname": profile.nickname,
            "gender": user_profile.gender if user_profile else None,
            "age": user_profile.age if user_profile else None,
            "city_code": user_profile.city_code if user_profile else None,
            "signature": profile.signature,
            "introduction": profile.introduction,
            "avatar_media": avatar_media[0] if avatar_media else None,
        },
        "category_codes": [link.category_code for link in profile.category_links.all()],
        "tag_codes": [link.tag_code for link in profile.tag_links.all()],
        "photo_media": get_media_payloads(photo_ids, request),
        "services": services,
        "moments": moments,
        "statistics": {
            "favorite_count": favorite_count,
            "follower_count": follower_count,
            "rating": float(rating_stat.rating_average) if rating_stat else None,
            "review_count": rating_stat.review_count if rating_stat else 0,
        },
        "viewer_state": {
            "is_following": viewer is not None
            and UserFollow.objects.filter(follower=viewer, followed=profile.user).exists(),
            "is_favorited": viewer is not None
            and Favorite.objects.filter(
                user=viewer,
                target_type=Favorite.TargetType.PROVIDER,
                target_id=profile.user.public_id,
            ).exists(),
        },
    }
