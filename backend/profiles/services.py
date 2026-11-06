"""个人资料、兴趣标签和城市选项的查询与修改业务服务。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from django.conf import settings
from django.db import IntegrityError, transaction
from django.db.models.functions import Lower
from django.http import HttpRequest

from backend.accounts.models import User
from backend.common.errors import ERROR_MESSAGES, ErrorCode
from backend.common.exceptions import ApiError
from backend.media.services import (
    USER_PROFILE_AVATAR,
    get_available_media,
    get_media_payloads,
    mark_media_referenced,
)
from backend.orders.services import order_summary
from backend.profiles.models import (
    InterestTag,
    ProfileCityOption,
    UserProfile,
    UserProfileInterest,
)
from backend.social.services import social_counts


@dataclass(frozen=True)
class ProfileUpdateResult:
    """个人资料更新结果，区分实际变化和无变化重放。"""

    profile: UserProfile
    changed: bool


def _invalid(field: str, message: str) -> ApiError:
    return ApiError(
        ErrorCode.PROFILE_INVALID,
        ERROR_MESSAGES[ErrorCode.PROFILE_INVALID],
        status_code=400,
        details={field: message},
    )


def validate_profile_payload(user: User, payload: dict[str, Any]) -> dict[str, Any]:
    """校验并规范化个人资料修改参数。"""

    normalized = dict(payload)
    if "nickname" in normalized:
        if normalized["nickname"] is None:
            raise _invalid("nickname", "昵称不能为空")
        nickname = str(normalized["nickname"]).strip()
        if not 1 <= len(nickname) <= settings.PROFILE_NICKNAME_MAX_LENGTH:
            raise _invalid(
                "nickname",
                f"昵称长度必须在 1 到 {settings.PROFILE_NICKNAME_MAX_LENGTH} 之间",
            )
        if (
            UserProfile.objects.annotate(lower_nickname=Lower("nickname"))
            .filter(lower_nickname=nickname.lower())
            .exclude(user=user)
            .exists()
        ):
            raise ApiError(
                ErrorCode.PROFILE_NICKNAME_CONFLICT,
                ERROR_MESSAGES[ErrorCode.PROFILE_NICKNAME_CONFLICT],
                status_code=409,
            )
        normalized["nickname"] = nickname
    if "gender" in normalized and normalized["gender"] not in {None, "MALE", "FEMALE"}:
        raise _invalid("gender", "性别只能是 MALE 或 FEMALE")
    if "age" in normalized and normalized["age"] is not None:
        age = normalized["age"]
        if not 18 <= age <= 40:
            raise _invalid("age", "年龄必须在 18 到 40 之间")
    if "signature" in normalized:
        signature = str(normalized["signature"]).strip()
        if len(signature) > settings.PROFILE_SIGNATURE_MAX_LENGTH:
            raise _invalid(
                "signature",
                f"个性签名不能超过 {settings.PROFILE_SIGNATURE_MAX_LENGTH} 个字符",
            )
        normalized["signature"] = signature
    if "city_code" in normalized:
        city_code = str(normalized["city_code"]).strip()
        if not ProfileCityOption.objects.filter(code=city_code, is_active=True).exists():
            raise ApiError(
                ErrorCode.PROFILE_OPTION_UNAVAILABLE,
                ERROR_MESSAGES[ErrorCode.PROFILE_OPTION_UNAVAILABLE],
                status_code=400,
                details={"city_code": "城市选项不存在或已停用"},
            )
        normalized["city_code"] = city_code
    if "avatar_media_id" in normalized and normalized["avatar_media_id"] is not None:
        get_available_media(
            user=user,
            purpose=USER_PROFILE_AVATAR,
            media_ids=[str(normalized["avatar_media_id"])],
        )
    if "interest_tag_codes" in normalized:
        tag_codes = normalized["interest_tag_codes"]
        if not isinstance(tag_codes, list):
            raise _invalid("interest_tag_codes", "兴趣标签必须是代码列表")
        normalized_tags = [str(code).strip() for code in tag_codes]
        if len(normalized_tags) > settings.PROFILE_INTEREST_TAG_MAX_COUNT:
            raise _invalid(
                "interest_tag_codes",
                f"最多选择 {settings.PROFILE_INTEREST_TAG_MAX_COUNT} 个兴趣标签",
            )
        if len(set(normalized_tags)) != len(normalized_tags):
            raise _invalid("interest_tag_codes", "兴趣标签不能重复")
        available_tags = {
            tag.code: tag
            for tag in InterestTag.objects.filter(
                code__in=normalized_tags,
                is_active=True,
            )
        }
        if len(available_tags) != len(normalized_tags):
            raise ApiError(
                ErrorCode.PROFILE_OPTION_UNAVAILABLE,
                ERROR_MESSAGES[ErrorCode.PROFILE_OPTION_UNAVAILABLE],
                status_code=400,
                details={"interest_tag_codes": "兴趣标签不存在或已停用"},
            )
        normalized["interest_tag_codes"] = normalized_tags
    return normalized


def _current_tag_codes(profile: UserProfile) -> list[str]:
    return [
        link.tag.code
        for link in profile.interest_links.select_related("tag").order_by("sort_order", "id")
    ]


def _profile_completeness(profile: UserProfile | None, tag_count: int) -> int:
    if profile is None:
        return 0
    checks = [
        bool(profile.nickname),
        bool(profile.avatar_media_id),
        profile.gender is not None,
        profile.age is not None,
        bool(profile.city_code),
        bool(profile.signature),
        tag_count > 0,
    ]
    return round(sum(checks) / len(checks) * 100)


def profile_payload(
    user: User,
    request: HttpRequest | None = None,
) -> dict[str, Any]:
    """返回当前用户安全的个人资料摘要。"""

    profile = UserProfile.objects.filter(user=user).prefetch_related("interest_links__tag").first()
    tag_links = (
        list(profile.interest_links.select_related("tag").order_by("sort_order", "id"))
        if profile
        else []
    )
    tag_payload = [
        {
            "code": link.tag.code,
            "name": link.tag.name,
            "category": link.tag.category,
            "sort_order": link.sort_order,
        }
        for link in tag_links
    ]
    avatar_media = (
        get_media_payloads([profile.avatar_media_id], request)
        if profile and profile.avatar_media_id
        else []
    )
    city = (
        ProfileCityOption.objects.filter(code=profile.city_code).first()
        if profile
        else ProfileCityOption.objects.filter(code=settings.PROFILE_DEFAULT_CITY_CODE).first()
    )
    return {
        "version": profile.version if profile else 0,
        "nickname": profile.nickname if profile else None,
        "avatar_media": avatar_media[0] if avatar_media else None,
        "gender": profile.gender if profile else None,
        "age": profile.age if profile else None,
        "city_code": profile.city_code if profile else settings.PROFILE_DEFAULT_CITY_CODE,
        "city_name": city.name if city else None,
        "signature": profile.signature if profile else "",
        "interest_tags": tag_payload,
        "trust_level": {
            "code": profile.trust_level_code if profile else "UNSET",
            "name": profile.trust_level_name if profile else "",
            "updated_at": profile.trust_level_updated_at if profile else None,
        },
        "profile_completeness": _profile_completeness(profile, len(tag_links)),
        "updated_at": profile.updated_at if profile else None,
    }


def profile_summary(user: User) -> dict[str, Any]:
    """返回我的页面订单、收藏和关注数量。"""

    user_orders = order_summary(user=user, role="USER")
    provider_orders = order_summary(user=user, role="PROVIDER")
    social = social_counts(user)
    return {
        "order_count": user_orders["total"],
        "provider_order_count": provider_orders["total"],
        "favorite_count": social["favorite_count"],
        "following_count": social["following_count"],
        "follower_count": social["follower_count"],
        "order_status_counts": user_orders["status_counts"],
        "provider_order_status_counts": provider_orders["status_counts"],
    }


def update_profile(
    *,
    user: User,
    payload: dict[str, Any],
    expected_version: int,
) -> ProfileUpdateResult:
    """使用乐观锁更新个人资料；相同内容重复提交不会增加版本。"""

    payload = validate_profile_payload(user, payload)
    try:
        with transaction.atomic():
            profile = UserProfile.objects.select_for_update().filter(user=user).first()
            current_version = profile.version if profile else 0
            if current_version != expected_version:
                raise ApiError(
                    ErrorCode.PROFILE_VERSION_CONFLICT,
                    ERROR_MESSAGES[ErrorCode.PROFILE_VERSION_CONFLICT],
                    status_code=409,
                )

            changed_fields = {
                key: value
                for key, value in payload.items()
                if key != "interest_tag_codes"
                and (profile is None or getattr(profile, key) != value)
            }
            next_tag_codes = payload.get("interest_tag_codes")
            tag_changed = next_tag_codes is not None and (
                profile is None or _current_tag_codes(profile) != next_tag_codes
            )
            if profile is None:
                defaults = {
                    "city_code": settings.PROFILE_DEFAULT_CITY_CODE,
                    "signature": "",
                    **changed_fields,
                }
                profile = UserProfile.objects.create(user=user, **defaults)
                changed = True
            else:
                changed = bool(changed_fields or tag_changed)
                if changed:
                    for field_name, value in changed_fields.items():
                        setattr(profile, field_name, value)
                    profile.version += 1
                    profile.save()

            if tag_changed:
                profile.interest_links.all().delete()
                if next_tag_codes:
                    tags = {
                        tag.code: tag for tag in InterestTag.objects.filter(code__in=next_tag_codes)
                    }
                    UserProfileInterest.objects.bulk_create(
                        [
                            UserProfileInterest(
                                profile=profile,
                                tag=tags[code],
                                sort_order=order,
                            )
                            for order, code in enumerate(next_tag_codes)
                        ]
                    )
                if not changed:
                    profile.version += 1
                    profile.save(update_fields=["version", "updated_at"])

            if payload.get("avatar_media_id"):
                mark_media_referenced([str(payload["avatar_media_id"])])
            return ProfileUpdateResult(profile=profile, changed=changed or tag_changed)
    except IntegrityError as exc:
        raise ApiError(
            ErrorCode.PROFILE_NICKNAME_CONFLICT,
            ERROR_MESSAGES[ErrorCode.PROFILE_NICKNAME_CONFLICT],
            status_code=409,
        ) from exc


def interest_tag_payloads() -> list[dict[str, Any]]:
    """返回启用中的兴趣标签配置。"""

    return [
        {
            "code": tag.code,
            "name": tag.name,
            "category": tag.category,
            "sort_order": tag.sort_order,
        }
        for tag in InterestTag.objects.filter(is_active=True)
    ]


def city_payloads() -> list[dict[str, Any]]:
    """返回启用中的城市代码配置。"""

    return [
        {"code": city.code, "name": city.name, "sort_order": city.sort_order}
        for city in ProfileCityOption.objects.filter(is_active=True)
    ]
