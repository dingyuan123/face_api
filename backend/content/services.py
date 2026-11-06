"""服务者动态创建、发布、审核和公开查询业务服务。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from django.conf import settings
from django.db import IntegrityError, transaction
from django.db.models import Count, Q
from django.http import HttpRequest
from django.utils import timezone

from backend.accounts.models import User
from backend.catalog.models import ProviderService
from backend.catalog.services import service_payload
from backend.common.context import current_trace_id
from backend.common.crypto import sensitive_fingerprint
from backend.common.errors import ERROR_MESSAGES, ErrorCode
from backend.common.exceptions import ApiError
from backend.content.models import (
    Moment,
    MomentCategory,
    MomentEvent,
    MomentMedia,
    MomentTag,
    MomentTagLink,
)
from backend.identity.models import IdentityVerification
from backend.media.services import (
    MOMENT_IMAGE,
    get_available_media_for_purposes,
    get_media_payloads,
    mark_media_referenced,
)
from backend.providers.profile_services import (
    get_provider_avatar_media_id,
    get_provider_profile,
    require_provider_enabled,
)
from backend.social.models import Favorite, MomentLike, UserFollow


@dataclass(frozen=True)
class MomentUpdateResult:
    """动态创建或修改结果。"""

    moment: Moment
    changed: bool
    reused: bool = False


def _invalid(field: str, message: str) -> ApiError:
    return ApiError(
        ErrorCode.MOMENT_INVALID,
        ERROR_MESSAGES[ErrorCode.MOMENT_INVALID],
        status_code=400,
        details={field: message},
    )


def _normalize_idempotency_key(value: str | None) -> str | None:
    if value is None:
        return None
    key = value.strip()
    if not key or len(key) > 128:
        raise ApiError(
            ErrorCode.MOMENT_IDEMPOTENCY_CONFLICT,
            "Idempotency-Key 长度必须在 1 到 128 之间",
            status_code=400,
        )
    return key


def validate_moment_payload(user: User, payload: dict[str, Any]) -> dict[str, Any]:
    """校验动态文案、媒体、标签和可选挂载服务。"""

    normalized = dict(payload)
    if normalized.get("type", "IMAGE_TEXT") != "IMAGE_TEXT":
        raise _invalid("type", "当前仅支持图文动态")
    normalized["type"] = "IMAGE_TEXT"
    content = str(normalized.get("content", "")).strip()
    if not 1 <= len(content) <= settings.MOMENT_CONTENT_MAX_LENGTH:
        raise _invalid(
            "content",
            f"动态文案必须为 1 到 {settings.MOMENT_CONTENT_MAX_LENGTH} 个字符",
        )
    normalized["content"] = content
    category_code = str(normalized.get("category_code", "")).strip()
    if not MomentCategory.objects.filter(code=category_code, is_active=True).exists():
        raise ApiError(
            ErrorCode.MOMENT_OPTION_UNAVAILABLE,
            ERROR_MESSAGES[ErrorCode.MOMENT_OPTION_UNAVAILABLE],
            status_code=400,
            details={"category_code": "动态类目不存在或已停用"},
        )
    normalized["category_code"] = category_code
    media_ids = normalized.get("media_ids", [])
    if not isinstance(media_ids, list):
        raise _invalid("media_ids", "动态媒体必须是媒体 ID 列表")
    normalized_media_ids = [str(item).strip() for item in media_ids]
    if not (
        settings.MOMENT_IMAGE_MIN_COUNT
        <= len(normalized_media_ids)
        <= settings.MOMENT_IMAGE_MAX_COUNT
    ):
        raise _invalid(
            "media_ids",
            f"动态图片必须为 {settings.MOMENT_IMAGE_MIN_COUNT} 到 "
            f"{settings.MOMENT_IMAGE_MAX_COUNT} 张",
        )
    if len(set(normalized_media_ids)) != len(normalized_media_ids):
        raise _invalid("media_ids", "动态媒体不能重复")
    get_available_media_for_purposes(
        user=user,
        purposes={MOMENT_IMAGE},
        media_ids=normalized_media_ids,
    )
    normalized["media_ids"] = normalized_media_ids
    cover_media_id = str(normalized.get("cover_media_id") or normalized_media_ids[0]).strip()
    if cover_media_id not in normalized_media_ids:
        raise _invalid("cover_media_id", "封面必须是当前动态图片")
    normalized["cover_media_id"] = cover_media_id
    if normalized.get("visibility", "PUBLIC") != "PUBLIC":
        raise _invalid("visibility", "当前仅支持公开动态")
    normalized["visibility"] = "PUBLIC"
    normalized["allow_recommend"] = bool(normalized.get("allow_recommend", True))
    attached_service_id = normalized.get("attached_service_id")
    if attached_service_id:
        service = ProviderService.objects.filter(
            public_id=attached_service_id,
            provider_user=user,
            deleted_at__isnull=True,
            status=ProviderService.Status.ONLINE,
        ).first()
        if service is None:
            raise _invalid("attached_service_id", "挂载服务不存在或不是当前服务者的已上架服务")
        normalized["attached_service_id"] = str(service.public_id)
    else:
        normalized["attached_service_id"] = None
    tag_codes = normalized.get("tag_codes", [])
    if not isinstance(tag_codes, list):
        raise _invalid("tag_codes", "动态标签必须是代码列表")
    normalized_tags = [str(code).strip() for code in tag_codes]
    if len(normalized_tags) > settings.MOMENT_TAG_MAX_COUNT:
        raise _invalid("tag_codes", f"最多选择 {settings.MOMENT_TAG_MAX_COUNT} 个动态标签")
    if len(set(normalized_tags)) != len(normalized_tags):
        raise _invalid("tag_codes", "动态标签不能重复")
    if MomentTag.objects.filter(code__in=normalized_tags, is_active=True).count() != len(
        normalized_tags
    ):
        raise ApiError(
            ErrorCode.MOMENT_OPTION_UNAVAILABLE,
            ERROR_MESSAGES[ErrorCode.MOMENT_OPTION_UNAVAILABLE],
            status_code=400,
            details={"tag_codes": "动态标签不存在或已停用"},
        )
    normalized["tag_codes"] = normalized_tags
    return normalized


def _viewer_state(moment: Moment, viewer: User | None) -> dict[str, Any]:
    return _viewer_states([moment], viewer)[str(moment.public_id)]


def _viewer_states(
    moments: list[Moment],
    viewer: User | None,
) -> dict[str, dict[str, bool]]:
    """批量计算访问者对动态的点赞、收藏和作者关注状态。"""

    empty_state = {
        "is_liked": False,
        "is_favorited": False,
        "is_following": False,
    }
    states = {str(moment.public_id): empty_state.copy() for moment in moments}
    if not moments or viewer is None or not viewer.is_authenticated:
        return states

    liked_ids = {
        str(item)
        for item in MomentLike.objects.filter(
            user=viewer,
            moment__in=moments,
        ).values_list("moment__public_id", flat=True)
    }
    favorite_ids = {
        str(item)
        for item in Favorite.objects.filter(
            user=viewer,
            target_type=Favorite.TargetType.MOMENT,
            target_id__in=[moment.public_id for moment in moments],
        ).values_list("target_id", flat=True)
    }
    followed_user_ids = set(
        UserFollow.objects.filter(
            follower=viewer,
            followed_id__in={moment.provider_user_id for moment in moments},
        ).values_list("followed_id", flat=True)
    )
    for moment in moments:
        states[str(moment.public_id)] = {
            "is_liked": str(moment.public_id) in liked_ids,
            "is_favorited": str(moment.public_id) in favorite_ids,
            "is_following": moment.provider_user_id in followed_user_ids,
        }
    return states


def _moment_payload(
    moment: Moment,
    request: HttpRequest | None = None,
    viewer: User | None = None,
    viewer_state: dict[str, bool] | None = None,
) -> dict[str, Any]:
    media_ids = [link.media_id for link in moment.media_links.all().order_by("position", "id")]
    provider_profile = getattr(moment.provider_user, "provider_profile", None)
    avatar_media_id = get_provider_avatar_media_id(moment.provider_user)
    avatar_media = get_media_payloads([avatar_media_id], request) if avatar_media_id else []
    verification = {
        "real_name_status": "NOT_SUBMITTED",
        "face_status": "NOT_SUBMITTED",
    }
    for item in moment.provider_user.identity_verifications.all():
        if item.verification_type == IdentityVerification.Type.REAL_NAME:
            verification["real_name_status"] = item.status
        if item.verification_type == IdentityVerification.Type.FACE:
            verification["face_status"] = item.status
    attached_service = (
        service_payload(moment.attached_service, request) if moment.attached_service else None
    )
    return {
        "id": str(moment.public_id),
        "type": moment.type,
        "category_code": moment.category.code if moment.category else None,
        "content": moment.content,
        "cover_media": get_media_payloads([moment.cover_media_id], request)[0]
        if moment.cover_media_id
        else None,
        "media": get_media_payloads(media_ids, request),
        "visibility": moment.visibility,
        "allow_recommend": moment.allow_recommend,
        "status": moment.status,
        "reject_reason": moment.reject_reason,
        "provider": {
            "user_public_id": str(moment.provider_user.public_id),
            "nickname": provider_profile.nickname if provider_profile else None,
            "avatar_media": avatar_media[0] if avatar_media else None,
            "verification": verification,
        },
        "viewer_state": viewer_state if viewer_state is not None else _viewer_state(moment, viewer),
        "attached_service": attached_service,
        "tag_codes": [link.tag.code for link in moment.tag_links.all().order_by("position", "id")],
        "like_count": moment.like_count,
        "comment_count": moment.comment_count,
        "share_count": moment.share_count,
        "view_count": moment.view_count,
        "version": moment.version,
        "published_at": moment.published_at,
        "updated_at": moment.updated_at,
    }


def moment_payload(
    moment: Moment,
    request: HttpRequest | None = None,
    viewer: User | None = None,
) -> dict[str, Any]:
    """返回动态安全摘要和临时媒体展示地址。"""

    return _moment_payload(moment, request, viewer)


def moment_payloads(
    moments: list[Moment],
    request: HttpRequest | None = None,
    viewer: User | None = None,
) -> list[dict[str, Any]]:
    """批量返回动态摘要，批量填充当前访问者互动状态。"""

    if not moments:
        return []
    states = _viewer_states(moments, viewer)
    return [
        _moment_payload(
            moment,
            request,
            viewer,
            viewer_state=states[str(moment.public_id)],
        )
        for moment in moments
    ]


def _record_event(
    *,
    moment: Moment,
    event_type: str,
    from_status: str,
    actor_user_id: int | None,
    reason: str = "",
) -> None:
    MomentEvent.objects.create(
        moment=moment,
        event_type=event_type,
        from_status=from_status,
        to_status=moment.status,
        actor_user_id=actor_user_id,
        reason=reason,
        trace_id=current_trace_id(),
    )


def _moment_fingerprint(payload: dict[str, Any]) -> str:
    return sensitive_fingerprint(payload)


def create_moment(
    *,
    user: User,
    payload: dict[str, Any],
    idempotency_key: str | None = None,
) -> MomentUpdateResult:
    """创建动态草稿并处理创建幂等。"""

    require_provider_enabled(user)
    get_provider_profile(user)
    payload = validate_moment_payload(user, payload)
    normalized_key = _normalize_idempotency_key(idempotency_key)
    fingerprint = _moment_fingerprint(payload)
    try:
        with transaction.atomic():
            if normalized_key:
                existing = Moment.objects.filter(
                    provider_user=user,
                    idempotency_key=normalized_key,
                    deleted_at__isnull=True,
                ).first()
                if existing:
                    if existing.request_fingerprint != fingerprint:
                        raise ApiError(
                            ErrorCode.MOMENT_IDEMPOTENCY_CONFLICT,
                            ERROR_MESSAGES[ErrorCode.MOMENT_IDEMPOTENCY_CONFLICT],
                            status_code=409,
                        )
                    return MomentUpdateResult(existing, changed=False, reused=True)
            moment = Moment.objects.create(
                provider_user=user,
                type=payload["type"],
                category_id=payload["category_code"],
                content=payload["content"],
                cover_media_id=payload["cover_media_id"],
                visibility=payload["visibility"],
                allow_recommend=payload["allow_recommend"],
                attached_service_id=payload["attached_service_id"],
                idempotency_key=normalized_key,
                request_fingerprint=fingerprint,
            )
            MomentMedia.objects.bulk_create(
                [
                    MomentMedia(moment=moment, media_id=media_id, position=position)
                    for position, media_id in enumerate(payload["media_ids"])
                ]
            )
            tags = {
                tag.code: tag for tag in MomentTag.objects.filter(code__in=payload["tag_codes"])
            }
            MomentTagLink.objects.bulk_create(
                [
                    MomentTagLink(moment=moment, tag=tags[code], position=position)
                    for position, code in enumerate(payload["tag_codes"])
                ]
            )
            _record_event(
                moment=moment,
                event_type=MomentEvent.EventType.CREATED,
                from_status="",
                actor_user_id=user.id,
            )
            mark_media_referenced(payload["media_ids"])
            return MomentUpdateResult(moment, changed=True)
    except IntegrityError as exc:
        if normalized_key:
            existing = Moment.objects.filter(
                provider_user=user,
                idempotency_key=normalized_key,
                deleted_at__isnull=True,
            ).first()
            if existing and existing.request_fingerprint == fingerprint:
                return MomentUpdateResult(existing, changed=False, reused=True)
        raise ApiError(
            ErrorCode.MOMENT_IDEMPOTENCY_CONFLICT,
            ERROR_MESSAGES[ErrorCode.MOMENT_IDEMPOTENCY_CONFLICT],
            status_code=409,
        ) from exc


def _get_owned_moment(*, user: User, moment_id: str) -> Moment:
    moment = Moment.objects.filter(
        public_id=moment_id,
        provider_user=user,
        deleted_at__isnull=True,
    ).first()
    if moment is None:
        raise ApiError(
            ErrorCode.MOMENT_NOT_FOUND,
            ERROR_MESSAGES[ErrorCode.MOMENT_NOT_FOUND],
            status_code=404,
        )
    return moment


def update_moment(
    *,
    user: User,
    moment_id: str,
    payload: dict[str, Any],
    expected_version: int,
) -> MomentUpdateResult:
    """修改草稿或被拒绝动态。"""

    require_provider_enabled(user)
    get_provider_profile(user)
    with transaction.atomic():
        moment = (
            Moment.objects.select_for_update()
            .filter(public_id=moment_id, provider_user=user, deleted_at__isnull=True)
            .first()
        )
        if moment is None:
            raise ApiError(
                ErrorCode.MOMENT_NOT_FOUND,
                ERROR_MESSAGES[ErrorCode.MOMENT_NOT_FOUND],
                status_code=404,
            )
        if moment.status not in {Moment.Status.DRAFT, Moment.Status.REJECTED}:
            raise ApiError(
                ErrorCode.MOMENT_STATE_INVALID,
                ERROR_MESSAGES[ErrorCode.MOMENT_STATE_INVALID],
                status_code=409,
            )
        if moment.version != expected_version:
            raise ApiError(
                ErrorCode.MOMENT_VERSION_CONFLICT,
                ERROR_MESSAGES[ErrorCode.MOMENT_VERSION_CONFLICT],
                status_code=409,
            )
        merged_payload = {
            "type": payload.get("type", moment.type),
            "category_code": payload.get(
                "category_code",
                moment.category.code if moment.category else "",
            ),
            "content": payload.get("content", moment.content),
            "cover_media_id": payload.get("cover_media_id", moment.cover_media_id),
            "media_ids": payload.get(
                "media_ids",
                [link.media_id for link in moment.media_links.all().order_by("position", "id")],
            ),
            "visibility": payload.get("visibility", moment.visibility),
            "allow_recommend": payload.get("allow_recommend", moment.allow_recommend),
            "attached_service_id": payload.get(
                "attached_service_id",
                str(moment.attached_service_id) if moment.attached_service_id else None,
            ),
            "tag_codes": payload.get(
                "tag_codes",
                [link.tag.code for link in moment.tag_links.all().order_by("position", "id")],
            ),
        }
        payload = validate_moment_payload(user, merged_payload)
        previous_status = moment.status
        moment.type = payload["type"]
        moment.category_id = payload["category_code"]
        moment.content = payload["content"]
        moment.cover_media_id = payload["cover_media_id"]
        moment.visibility = payload["visibility"]
        moment.allow_recommend = payload["allow_recommend"]
        moment.attached_service_id = payload["attached_service_id"]
        moment.version += 1
        moment.save()
        moment.media_links.all().delete()
        MomentMedia.objects.bulk_create(
            [
                MomentMedia(moment=moment, media_id=media_id, position=position)
                for position, media_id in enumerate(payload["media_ids"])
            ]
        )
        moment.tag_links.all().delete()
        tags = {tag.code: tag for tag in MomentTag.objects.filter(code__in=payload["tag_codes"])}
        MomentTagLink.objects.bulk_create(
            [
                MomentTagLink(moment=moment, tag=tags[code], position=position)
                for position, code in enumerate(payload["tag_codes"])
            ]
        )
        _record_event(
            moment=moment,
            event_type=MomentEvent.EventType.UPDATED,
            from_status=previous_status,
            actor_user_id=user.id,
        )
        mark_media_referenced(payload["media_ids"])
        return MomentUpdateResult(moment, changed=True)


def publish_moment(
    *,
    user: User,
    moment_id: str,
    expected_version: int,
) -> Moment:
    """发布动态；当前 IMMEDIATE 模式直接进入 PUBLISHED，未来审核模式进入 PENDING。"""

    require_provider_enabled(user)
    get_provider_profile(user)
    with transaction.atomic():
        moment = (
            Moment.objects.select_for_update()
            .filter(public_id=moment_id, provider_user=user, deleted_at__isnull=True)
            .first()
        )
        if moment is None:
            raise ApiError(
                ErrorCode.MOMENT_NOT_FOUND,
                ERROR_MESSAGES[ErrorCode.MOMENT_NOT_FOUND],
                status_code=404,
            )
        if moment.status not in {Moment.Status.DRAFT, Moment.Status.REJECTED}:
            raise ApiError(
                ErrorCode.MOMENT_STATE_INVALID,
                ERROR_MESSAGES[ErrorCode.MOMENT_STATE_INVALID],
                status_code=409,
            )
        if moment.version != expected_version:
            raise ApiError(
                ErrorCode.MOMENT_VERSION_CONFLICT,
                ERROR_MESSAGES[ErrorCode.MOMENT_VERSION_CONFLICT],
                status_code=409,
            )
        previous_status = moment.status
        if settings.MOMENT_REVIEW_MODE == "IMMEDIATE":
            moment.status = Moment.Status.PUBLISHED
            moment.published_at = timezone.now()
            event_type = MomentEvent.EventType.PUBLISHED
        else:
            moment.status = Moment.Status.PENDING
            event_type = MomentEvent.EventType.SUBMITTED
        moment.version += 1
        moment.save()
        _record_event(
            moment=moment,
            event_type=event_type,
            from_status=previous_status,
            actor_user_id=user.id,
        )
        return moment


def delete_moment(*, user: User, moment_id: str, expected_version: int) -> None:
    """逻辑删除动态，保留动态内容和事件。"""

    with transaction.atomic():
        moment = (
            Moment.objects.select_for_update()
            .filter(public_id=moment_id, provider_user=user, deleted_at__isnull=True)
            .first()
        )
        if moment is None:
            raise ApiError(
                ErrorCode.MOMENT_NOT_FOUND,
                ERROR_MESSAGES[ErrorCode.MOMENT_NOT_FOUND],
                status_code=404,
            )
        if moment.status not in {
            Moment.Status.DRAFT,
            Moment.Status.REJECTED,
            Moment.Status.PUBLISHED,
        }:
            raise ApiError(
                ErrorCode.MOMENT_STATE_INVALID,
                ERROR_MESSAGES[ErrorCode.MOMENT_STATE_INVALID],
                status_code=409,
            )
        if moment.version != expected_version:
            raise ApiError(
                ErrorCode.MOMENT_VERSION_CONFLICT,
                ERROR_MESSAGES[ErrorCode.MOMENT_VERSION_CONFLICT],
                status_code=409,
            )
        previous_status = moment.status
        moment.deleted_at = timezone.now()
        moment.status = Moment.Status.DELETED
        moment.version += 1
        moment.save(update_fields=["deleted_at", "status", "version", "updated_at"])
        _record_event(
            moment=moment,
            event_type=MomentEvent.EventType.DELETED,
            from_status=previous_status,
            actor_user_id=user.id,
        )


def get_owned_moment_payload(
    user: User,
    moment_id: str,
    request: HttpRequest | None = None,
    viewer: User | None = None,
) -> dict[str, Any]:
    """返回服务者本人动态摘要。"""

    return moment_payload(
        _get_owned_moment(user=user, moment_id=moment_id),
        request,
        viewer or user,
    )


def list_owned_moment_payloads(
    *,
    user: User,
    status: str | None,
    page: int,
    page_size: int,
    request: HttpRequest | None = None,
    viewer: User | None = None,
) -> dict[str, Any]:
    """返回服务者动态管理列表。"""

    queryset = Moment.objects.filter(provider_user=user, deleted_at__isnull=True)
    if status:
        if status not in Moment.Status.values:
            raise _invalid("status", "动态状态不存在")
        queryset = queryset.filter(status=status)
    total = queryset.count()
    start = (page - 1) * page_size
    moments = list(queryset.order_by("-updated_at", "-id")[start : start + page_size])
    return {
        "items": moment_payloads(moments, request, viewer or user),
        "total": total,
        "page": page,
        "page_size": page_size,
    }


def _public_moment_base_queryset(
    *,
    keyword: str | None = None,
    category_code: str | None = None,
    tab: str = "RECOMMENDED",
    city_code: str | None = None,
):
    if tab not in {"RECOMMENDED", "FOLLOWING", "NEARBY"}:
        raise _invalid("tab", "动态筛选标签不存在")
    queryset = Moment.objects.select_related(
        "provider_user",
        "provider_user__provider_profile",
        "provider_user__profile",
        "category",
        "attached_service",
    ).filter(
        status=Moment.Status.PUBLISHED,
        visibility=Moment.Visibility.PUBLIC,
        deleted_at__isnull=True,
    )
    if keyword:
        search = keyword.strip()
        queryset = queryset.filter(
            Q(content__icontains=search)
            | Q(provider_user__provider_profile__nickname__icontains=search)
            | Q(attached_service__title__icontains=search)
            | Q(tag_links__tag__name__icontains=search)
            | Q(tag_links__tag__code__icontains=search)
        ).distinct()
    if category_code:
        queryset = queryset.filter(category_id=category_code)
    if tab == "RECOMMENDED":
        queryset = queryset.filter(allow_recommend=True)
    elif tab == "NEARBY":
        queryset = queryset.filter(
            provider_user__profile__city_code=city_code or settings.PROFILE_DEFAULT_CITY_CODE
        )
    else:
        queryset = queryset.none()
    return queryset


def public_moment_queryset(
    *,
    keyword: str | None = None,
    category_code: str | None = None,
    tab: str = "RECOMMENDED",
    city_code: str | None = None,
):
    """构建已发布公开动态查询。"""

    queryset = _public_moment_base_queryset(
        keyword=keyword,
        category_code=category_code,
        tab=tab,
        city_code=city_code,
    )
    return queryset.order_by("-published_at", "-id")


def moment_category_payloads() -> list[dict[str, Any]]:
    """返回启用中的动态内容类目配置。"""

    return [
        {"code": category.code, "name": category.name, "sort_order": category.sort_order}
        for category in MomentCategory.objects.filter(is_active=True)
    ]


def get_public_moment_payload(
    moment_id: str,
    request: HttpRequest | None = None,
    viewer: User | None = None,
) -> dict[str, Any]:
    """返回公开已发布动态摘要。"""

    moment = (
        Moment.objects.select_related(
            "provider_user",
            "provider_user__provider_profile",
            "attached_service",
        )
        .filter(
            public_id=moment_id,
            status=Moment.Status.PUBLISHED,
            visibility=Moment.Visibility.PUBLIC,
            deleted_at__isnull=True,
        )
        .first()
    )
    if moment is None:
        raise ApiError(
            ErrorCode.MOMENT_NOT_FOUND,
            ERROR_MESSAGES[ErrorCode.MOMENT_NOT_FOUND],
            status_code=404,
        )
    return moment_payload(moment, request, viewer)


def get_public_moment_neighbors(
    *,
    moment_id: str,
    keyword: str | None = None,
    category_code: str | None = None,
    tab: str = "RECOMMENDED",
    city_code: str | None = None,
    request: HttpRequest | None = None,
    viewer: User | None = None,
) -> dict[str, Any]:
    """返回同一浏览上下文中紧邻当前动态的前后动态。"""

    if tab == "FOLLOWING":
        raise ApiError(
            ErrorCode.MOMENT_OPTION_UNAVAILABLE,
            ERROR_MESSAGES[ErrorCode.MOMENT_OPTION_UNAVAILABLE],
            status_code=409,
            details={"tab": "关注动态尚未开放"},
        )
    queryset = _public_moment_base_queryset(
        keyword=keyword,
        category_code=category_code,
        tab=tab,
        city_code=city_code,
    )
    current = queryset.filter(public_id=moment_id).first()
    if current is None:
        raise ApiError(
            ErrorCode.MOMENT_NOT_FOUND,
            ERROR_MESSAGES[ErrorCode.MOMENT_NOT_FOUND],
            status_code=404,
        )
    previous = (
        queryset.filter(
            Q(published_at__gt=current.published_at)
            | Q(published_at=current.published_at, id__gt=current.id)
        )
        .order_by("published_at", "id")
        .first()
    )
    next_moment = (
        queryset.filter(
            Q(published_at__lt=current.published_at)
            | Q(published_at=current.published_at, id__lt=current.id)
        )
        .order_by("-published_at", "-id")
        .first()
    )
    neighbors = [moment for moment in (current, previous, next_moment) if moment]
    states = _viewer_states(neighbors, viewer)
    return {
        "current": _moment_payload(
            current,
            request,
            viewer_state=states[str(current.public_id)],
        ),
        "previous": _moment_payload(
            previous,
            request,
            viewer_state=states[str(previous.public_id)],
        )
        if previous
        else None,
        "next": _moment_payload(
            next_moment,
            request,
            viewer_state=states[str(next_moment.public_id)],
        )
        if next_moment
        else None,
        "has_previous": previous is not None,
        "has_next": next_moment is not None,
        "feed_context": {
            "tab": tab,
            "keyword": keyword or "",
            "category_code": category_code or "",
            "city_code": city_code or settings.PROFILE_DEFAULT_CITY_CODE,
            "sort": "NEWEST",
            "strategy": "NEWEST",
            "location_mode": "CITY" if tab == "NEARBY" else None,
        },
    }


def get_admin_moment_payload(
    moment_id: str,
    request: HttpRequest | None = None,
    viewer: User | None = None,
) -> dict[str, Any]:
    """返回管理员动态审核详情。"""

    moment = (
        Moment.objects.select_related(
            "provider_user",
            "provider_user__provider_profile",
            "attached_service",
        )
        .filter(public_id=moment_id, deleted_at__isnull=True)
        .first()
    )
    if moment is None:
        raise ApiError(
            ErrorCode.MOMENT_NOT_FOUND,
            ERROR_MESSAGES[ErrorCode.MOMENT_NOT_FOUND],
            status_code=404,
        )
    return moment_payload(moment, request, viewer)


def list_admin_moment_payloads(
    *,
    status: str | None,
    provider_public_id: str | None,
    keyword: str | None,
    page: int,
    page_size: int,
    request: HttpRequest | None = None,
    viewer: User | None = None,
) -> dict[str, Any]:
    """返回管理员动态列表和状态汇总。"""

    base_queryset = Moment.objects.select_related(
        "provider_user",
        "provider_user__provider_profile",
        "attached_service",
    ).filter(deleted_at__isnull=True)
    queryset = base_queryset
    if status:
        if status not in Moment.Status.values:
            raise _invalid("status", "动态状态不存在")
        queryset = queryset.filter(status=status)
    if provider_public_id:
        queryset = queryset.filter(provider_user__public_id=provider_public_id)
    if keyword:
        search = keyword.strip()
        queryset = queryset.filter(
            Q(content__icontains=search)
            | Q(provider_user__provider_profile__nickname__icontains=search)
        )
    total = queryset.count()
    summary = {
        item["status"]: item["total"]
        for item in base_queryset.values("status").annotate(total=Count("id"))
    }
    start = (page - 1) * page_size
    moments = list(queryset.order_by("-updated_at", "-id")[start : start + page_size])
    return {
        "items": moment_payloads(moments, request, viewer),
        "total": total,
        "page": page,
        "page_size": page_size,
        "summary": {
            "total": sum(summary.values()),
            "draft": summary.get(Moment.Status.DRAFT, 0),
            "pending": summary.get(Moment.Status.PENDING, 0),
            "published": summary.get(Moment.Status.PUBLISHED, 0),
            "rejected": summary.get(Moment.Status.REJECTED, 0),
            "deleted": summary.get(Moment.Status.DELETED, 0),
        },
    }


def review_moment(
    *,
    moment_id: str,
    approve: bool,
    reviewer: User,
    expected_version: int,
    reason: str = "",
) -> Moment:
    """管理员审核动态；供后续 REVIEW_REQUIRED 模式使用。"""

    normalized_reason = reason.strip()
    if not approve and len(normalized_reason) < 2:
        raise _invalid("reason", "拒绝原因至少需要 2 个字符")
    with transaction.atomic():
        moment = (
            Moment.objects.select_for_update()
            .filter(public_id=moment_id, deleted_at__isnull=True)
            .first()
        )
        if moment is None:
            raise ApiError(
                ErrorCode.MOMENT_NOT_FOUND,
                ERROR_MESSAGES[ErrorCode.MOMENT_NOT_FOUND],
                status_code=404,
            )
        if moment.status != Moment.Status.PENDING:
            raise ApiError(
                ErrorCode.MOMENT_STATE_INVALID,
                ERROR_MESSAGES[ErrorCode.MOMENT_STATE_INVALID],
                status_code=409,
            )
        if moment.version != expected_version:
            raise ApiError(
                ErrorCode.MOMENT_VERSION_CONFLICT,
                ERROR_MESSAGES[ErrorCode.MOMENT_VERSION_CONFLICT],
                status_code=409,
            )
        previous_status = moment.status
        if approve:
            moment.status = Moment.Status.PUBLISHED
            moment.published_at = timezone.now()
            moment.reject_reason = ""
            event_type = MomentEvent.EventType.APPROVED
        else:
            moment.status = Moment.Status.REJECTED
            moment.reject_reason = normalized_reason
            event_type = MomentEvent.EventType.REJECTED
        moment.version += 1
        moment.save()
        _record_event(
            moment=moment,
            event_type=event_type,
            from_status=previous_status,
            actor_user_id=reviewer.id,
            reason=normalized_reason,
        )
        return moment
