"""当前用户分享海报数据组装、主页链接校验和展示文案读取。"""

from __future__ import annotations

from typing import Any

from django.conf import settings
from django.http import HttpRequest

from backend.accounts.models import User
from backend.media.services import get_media_payloads
from backend.profiles.models import ProfileCityOption, UserProfile
from backend.referrals.qr_services import build_referral_qr_image_url
from backend.referrals.services import (
    build_share_url,
    get_or_create_profile_share_link,
)


def profile_share_poster_payload(
    user: User,
    request: HttpRequest | None = None,
) -> dict[str, Any]:
    """返回前端绘制个人分享海报所需的非敏感数据。"""

    profile = UserProfile.objects.filter(user=user).prefetch_related("interest_links__tag").first()
    interest_names = [
        link.tag.name
        for link in (
            profile.interest_links.select_related("tag").order_by("sort_order", "id")
            if profile
            else []
        )
    ]
    city = ProfileCityOption.objects.filter(code=profile.city_code).first() if profile else None
    cover_media = (
        get_media_payloads([profile.avatar_media_id], request)
        if profile and profile.avatar_media_id
        else []
    )
    share_link = get_or_create_profile_share_link(user=user)
    profile_url = build_share_url(user=user, share_link=share_link)
    qr_image_url, qr_image_expires_at = build_referral_qr_image_url(
        user=user,
        share_link=share_link,
        request=request,
    )
    nickname = profile.nickname if profile and profile.nickname else "见面聊用户"
    return {
        "brand_name": settings.SHARE_POSTER_BRAND_NAME,
        "brand_label": settings.SHARE_POSTER_BRAND_LABEL,
        "slogan_line_1": settings.SHARE_POSTER_SLOGAN_LINE_1,
        "slogan_line_2": settings.SHARE_POSTER_SLOGAN_LINE_2,
        "slogan_subtitle": settings.SHARE_POSTER_SLOGAN_SUBTITLE,
        "cover": cover_media[0] if cover_media else None,
        "nickname": nickname,
        "age": profile.age if profile else None,
        "city": city.name if city else (profile.city_code if profile else ""),
        "signature": profile.signature if profile else "",
        "interest_tags": interest_names,
        "profile_url": profile_url,
        "qr_image_url": qr_image_url,
        "qr_image_expires_at": qr_image_expires_at,
        "card_footer": settings.SHARE_POSTER_CARD_FOOTER,
        "bottom_slogan": settings.SHARE_POSTER_BOTTOM_SLOGAN,
        "share": {
            "link_url": profile_url,
            "title": settings.SHARE_POSTER_SHARE_TITLE,
            "description": settings.SHARE_POSTER_SHARE_DESCRIPTION,
        },
    }


__all__ = ["profile_share_poster_payload"]
