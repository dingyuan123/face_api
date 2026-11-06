"""服务者资料查询、修改和媒体引用业务服务。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from django.db import IntegrityError, transaction
from django.db.models.functions import Lower
from django.http import HttpRequest

from backend.accounts.models import User
from backend.catalog.models import ProviderTag, ServiceCategory
from backend.common.errors import ERROR_MESSAGES, ErrorCode
from backend.common.exceptions import ApiError
from backend.media.services import (
    PROVIDER_APPLICATION_AVATAR,
    PROVIDER_APPLICATION_LIFE_PHOTO,
    PROVIDER_PROFILE_AVATAR,
    PROVIDER_PROFILE_PHOTO,
    get_available_media_for_purposes,
    get_media_payloads,
    mark_media_referenced,
)
from backend.providers.models import (
    ProviderApplication,
    ProviderProfile,
    ProviderProfileCategory,
    ProviderProfileMedia,
    ProviderProfileTag,
)


def get_provider_avatar_media_id(user: User) -> str | None:
    """返回服务者资料头像，资料未填写时回退最近申请头像。"""

    profile = ProviderProfile.objects.filter(user=user).first()
    if profile and profile.avatar_media_id:
        return profile.avatar_media_id
    application = ProviderApplication.objects.filter(user=user).order_by("-submitted_at").first()
    return application.avatar_media_id if application else None


@dataclass(frozen=True)
class ProviderProfileUpdateResult:
    """服务者资料修改结果。"""

    profile: ProviderProfile
    changed: bool


def _invalid(field: str, message: str) -> ApiError:
    return ApiError(
        ErrorCode.PROVIDER_PROFILE_INVALID,
        ERROR_MESSAGES[ErrorCode.PROVIDER_PROFILE_INVALID],
        status_code=400,
        details={field: message},
    )


def require_provider_enabled(user: User) -> None:
    """校验当前用户已开通服务者业务权限。"""

    if not user.provider_enabled or user.provider_status != User.ProviderStatus.APPROVED:
        raise ApiError(
            ErrorCode.PROVIDER_NOT_ENABLED,
            ERROR_MESSAGES[ErrorCode.PROVIDER_NOT_ENABLED],
            status_code=403,
        )


def validate_provider_profile_payload(
    user: User,
    payload: dict[str, Any],
) -> dict[str, Any]:
    """校验服务者资料、类目、标签和媒体引用。"""

    normalized = dict(payload)
    if "nickname" in normalized:
        nickname = str(normalized["nickname"]).strip()
        if not 1 <= len(nickname) <= 20:
            raise _invalid("nickname", "昵称长度必须在 1 到 20 之间")
        if (
            ProviderProfile.objects.annotate(lower_nickname=Lower("nickname"))
            .filter(lower_nickname=nickname.lower())
            .exclude(user=user)
            .exists()
        ):
            raise _invalid("nickname", "服务者昵称已被使用")
        normalized["nickname"] = nickname
    if "signature" in normalized:
        signature = str(normalized["signature"]).strip()
        if len(signature) > 100:
            raise _invalid("signature", "个性签名不能超过 100 个字符")
        normalized["signature"] = signature
    if "introduction" in normalized:
        introduction = str(normalized["introduction"]).strip()
        if not 20 <= len(introduction) <= 200:
            raise _invalid("introduction", "个人介绍必须为 20 到 200 个字符")
        normalized["introduction"] = introduction
    if normalized.get("avatar_media_id"):
        get_available_media_for_purposes(
            user=user,
            purposes={
                PROVIDER_PROFILE_AVATAR,
                PROVIDER_APPLICATION_AVATAR,
            },
            media_ids=[str(normalized["avatar_media_id"])],
        )
    if "photo_media_ids" in normalized:
        photo_ids = normalized["photo_media_ids"]
        if not isinstance(photo_ids, list):
            raise _invalid("photo_media_ids", "照片墙必须是媒体 ID 列表")
        normalized_photos = [str(item).strip() for item in photo_ids]
        if not 3 <= len(normalized_photos) <= 6:
            raise _invalid("photo_media_ids", "照片墙必须为 3 到 6 张")
        if len(set(normalized_photos)) != len(normalized_photos):
            raise _invalid("photo_media_ids", "照片墙媒体不能重复")
        get_available_media_for_purposes(
            user=user,
            purposes={
                PROVIDER_PROFILE_PHOTO,
                PROVIDER_APPLICATION_LIFE_PHOTO,
            },
            media_ids=normalized_photos,
        )
        normalized["photo_media_ids"] = normalized_photos
    if "category_codes" in normalized:
        category_codes = normalized["category_codes"]
        if not isinstance(category_codes, list) or not category_codes:
            raise _invalid("category_codes", "至少选择一个服务类目")
        normalized_categories = [str(code).strip() for code in category_codes]
        if len(set(normalized_categories)) != len(normalized_categories):
            raise _invalid("category_codes", "服务类目不能重复")
        if ServiceCategory.objects.filter(
            code__in=normalized_categories,
            is_active=True,
        ).count() != len(normalized_categories):
            raise _invalid("category_codes", "服务类目不存在或已停用")
        normalized["category_codes"] = normalized_categories
    if "tag_codes" in normalized:
        tag_codes = normalized["tag_codes"]
        if not isinstance(tag_codes, list):
            raise _invalid("tag_codes", "服务者标签必须是代码列表")
        normalized_tags = [str(code).strip() for code in tag_codes]
        if len(normalized_tags) > 8:
            raise _invalid("tag_codes", "最多选择 8 个服务者标签")
        if len(set(normalized_tags)) != len(normalized_tags):
            raise _invalid("tag_codes", "服务者标签不能重复")
        if ProviderTag.objects.filter(code__in=normalized_tags, is_active=True).count() != len(
            normalized_tags
        ):
            raise _invalid("tag_codes", "服务者标签不存在或已停用")
        normalized["tag_codes"] = normalized_tags
    return normalized


def _category_codes(profile: ProviderProfile) -> list[str]:
    return [link.category_code for link in profile.category_links.all().order_by("id")]


def _tag_codes(profile: ProviderProfile) -> list[str]:
    return [link.tag_code for link in profile.tag_links.all().order_by("sort_order", "id")]


def provider_profile_payload(
    user: User,
    request: HttpRequest | None = None,
) -> dict[str, Any]:
    """返回当前服务者资料安全摘要。"""

    require_provider_enabled(user)
    profile = (
        ProviderProfile.objects.filter(user=user)
        .prefetch_related("category_links", "tag_links", "photo_links")
        .first()
    )
    if profile is None:
        application_avatar_id = (
            ProviderApplication.objects.filter(user=user)
            .order_by("-submitted_at")
            .values_list("avatar_media_id", flat=True)
            .first()
        )
        avatar_media = (
            get_media_payloads([application_avatar_id], request) if application_avatar_id else []
        )
        return {
            "version": 0,
            "nickname": None,
            "signature": "",
            "introduction": "",
            "avatar_media": avatar_media[0] if avatar_media else None,
            "photo_media": [],
            "category_codes": [],
            "tag_codes": [],
            "updated_at": None,
        }
    avatar_media_id = profile.avatar_media_id
    if not avatar_media_id:
        avatar_media_id = (
            ProviderApplication.objects.filter(user=user)
            .order_by("-submitted_at")
            .values_list("avatar_media_id", flat=True)
            .first()
        )
    avatar_media = get_media_payloads([avatar_media_id], request) if avatar_media_id else []
    photo_ids = [link.media_id for link in profile.photo_links.all().order_by("position", "id")]
    return {
        "version": profile.version,
        "nickname": profile.nickname,
        "signature": profile.signature,
        "introduction": profile.introduction,
        "avatar_media": avatar_media[0] if avatar_media else None,
        "photo_media": get_media_payloads(photo_ids, request),
        "category_codes": _category_codes(profile),
        "tag_codes": _tag_codes(profile),
        "updated_at": profile.updated_at,
    }


def update_provider_profile(
    *,
    user: User,
    payload: dict[str, Any],
    expected_version: int,
) -> ProviderProfileUpdateResult:
    """使用乐观锁创建或更新服务者资料。"""

    require_provider_enabled(user)
    payload = validate_provider_profile_payload(user, payload)
    try:
        with transaction.atomic():
            profile = ProviderProfile.objects.select_for_update().filter(user=user).first()
            current_version = profile.version if profile else 0
            if current_version != expected_version:
                raise ApiError(
                    ErrorCode.PROVIDER_PROFILE_VERSION_CONFLICT,
                    ERROR_MESSAGES[ErrorCode.PROVIDER_PROFILE_VERSION_CONFLICT],
                    status_code=409,
                )
            changed_fields = {
                key: value
                for key, value in payload.items()
                if key not in {"category_codes", "tag_codes", "photo_media_ids"}
                and (profile is None or getattr(profile, key) != value)
            }
            relation_changed = any(
                key in payload for key in {"category_codes", "tag_codes", "photo_media_ids"}
            )
            if profile is None:
                required = {
                    "nickname",
                    "introduction",
                    "category_codes",
                    "photo_media_ids",
                }
                missing = sorted(required - payload.keys())
                if missing:
                    raise _invalid(
                        "required_fields",
                        f"首次创建服务者资料必须提供: {', '.join(missing)}",
                    )
                profile = ProviderProfile.objects.create(
                    user=user,
                    nickname=payload.get("nickname", ""),
                    signature=payload.get("signature", ""),
                    introduction=payload.get("introduction", ""),
                    avatar_media_id=payload.get("avatar_media_id"),
                )
                changed = True
            else:
                changed = bool(changed_fields or relation_changed)
                if changed:
                    for field_name, value in changed_fields.items():
                        setattr(profile, field_name, value)
                    profile.version += 1
                    profile.save()

            if "category_codes" in payload:
                profile.category_links.all().delete()
                ProviderProfileCategory.objects.bulk_create(
                    [
                        ProviderProfileCategory(profile=profile, category_code=code)
                        for code in payload["category_codes"]
                    ]
                )
            if "tag_codes" in payload:
                profile.tag_links.all().delete()
                ProviderProfileTag.objects.bulk_create(
                    [
                        ProviderProfileTag(profile=profile, tag_code=code, sort_order=order)
                        for order, code in enumerate(payload["tag_codes"])
                    ]
                )
            if "photo_media_ids" in payload:
                profile.photo_links.all().delete()
                ProviderProfileMedia.objects.bulk_create(
                    [
                        ProviderProfileMedia(profile=profile, media_id=media_id, position=order)
                        for order, media_id in enumerate(payload["photo_media_ids"])
                    ]
                )
                mark_media_referenced(payload["photo_media_ids"])
            if payload.get("avatar_media_id"):
                mark_media_referenced([payload["avatar_media_id"]])
            return ProviderProfileUpdateResult(profile=profile, changed=changed)
    except IntegrityError as exc:
        raise _invalid("nickname", "服务者昵称已被使用") from exc


def get_provider_profile(user: User) -> ProviderProfile:
    """返回已存在的服务者资料，服务创建时必须先完成资料。"""

    profile = ProviderProfile.objects.filter(user=user).first()
    if profile is None:
        raise ApiError(
            ErrorCode.PROVIDER_PROFILE_NOT_FOUND,
            ERROR_MESSAGES[ErrorCode.PROVIDER_PROFILE_NOT_FOUND],
            status_code=404,
        )
    return profile
