"""服务类目配置、服务草稿和审核状态管理业务服务。"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from django.conf import settings
from django.db import IntegrityError, transaction
from django.db.models import Count, Q, Sum
from django.http import HttpRequest
from django.utils import timezone

from backend.accounts.models import User
from backend.catalog.models import (
    ProviderService,
    ProviderServiceEvent,
    ProviderServiceGalleryMedia,
    ProviderServiceTag,
    ProviderTag,
    ServiceCategory,
    ServiceTag,
)
from backend.common.context import current_trace_id
from backend.common.crypto import sensitive_fingerprint
from backend.common.errors import ERROR_MESSAGES, ErrorCode
from backend.common.exceptions import ApiError
from backend.media.services import (
    PROVIDER_SERVICE_COVER,
    PROVIDER_SERVICE_GALLERY,
    get_available_media,
    get_media_payloads,
    mark_media_referenced,
)
from backend.providers.profile_services import get_provider_profile, require_provider_enabled


@dataclass(frozen=True)
class ServiceUpdateResult:
    """服务创建或修改结果。"""

    service: ProviderService
    changed: bool
    reused: bool = False


def _invalid(field: str, message: str) -> ApiError:
    return ApiError(
        ErrorCode.SERVICE_INVALID,
        ERROR_MESSAGES[ErrorCode.SERVICE_INVALID],
        status_code=400,
        details={field: message},
    )


def format_price_amount(amount_minor: int, currency: str) -> str:
    """格式化最小货币单位金额，不使用浮点数参与计算。"""

    amount = Decimal(amount_minor) / Decimal(100)
    return f"{amount.quantize(Decimal('0.00'), rounding=ROUND_HALF_UP):.2f}"


def _normalize_idempotency_key(value: str | None) -> str | None:
    if value is None:
        return None
    key = value.strip()
    if not key or len(key) > 128:
        raise ApiError(
            ErrorCode.SERVICE_IDEMPOTENCY_CONFLICT,
            "Idempotency-Key 长度必须在 1 到 128 之间",
            status_code=400,
        )
    return key


def validate_service_payload(user: User, payload: dict[str, Any]) -> dict[str, Any]:
    """校验服务参数、配置代码和媒体所有权。"""

    normalized = dict(payload)
    title = str(normalized.get("title", "")).strip()
    if not 1 <= len(title) <= settings.SERVICE_TITLE_MAX_LENGTH:
        raise _invalid(
            "title",
            f"服务名称必须为 1 到 {settings.SERVICE_TITLE_MAX_LENGTH} 个字符",
        )
    normalized["title"] = title
    category_code = str(normalized.get("category_code", "")).strip()
    if not ServiceCategory.objects.filter(code=category_code, is_active=True).exists():
        raise ApiError(
            ErrorCode.SERVICE_OPTION_UNAVAILABLE,
            ERROR_MESSAGES[ErrorCode.SERVICE_OPTION_UNAVAILABLE],
            status_code=400,
            details={"category_code": "服务类目不存在或已停用"},
        )
    normalized["category_code"] = category_code
    if normalized.get("currency", "CNY") != "CNY":
        raise _invalid("currency", "当前仅支持 CNY")
    normalized["currency"] = "CNY"
    price_amount_minor = normalized.get("price_amount_minor")
    if not isinstance(price_amount_minor, int) or price_amount_minor <= 0:
        raise _invalid("price_amount_minor", "价格必须大于 0，单位为分")
    duration_minutes = normalized.get("duration_minutes")
    if not isinstance(duration_minutes, int) or duration_minutes <= 0:
        raise _invalid("duration_minutes", "服务时长必须大于 0")
    introduction = str(normalized.get("introduction", "")).strip()
    if not (
        settings.SERVICE_INTRODUCTION_MIN_LENGTH
        <= len(introduction)
        <= settings.SERVICE_INTRODUCTION_MAX_LENGTH
    ):
        raise _invalid(
            "introduction",
            f"服务介绍必须为 {settings.SERVICE_INTRODUCTION_MIN_LENGTH} 到 "
            f"{settings.SERVICE_INTRODUCTION_MAX_LENGTH} 个字符",
        )
    normalized["introduction"] = introduction
    cover_media_id = str(normalized.get("cover_media_id", "")).strip()
    get_available_media(
        user=user,
        purpose=PROVIDER_SERVICE_COVER,
        media_ids=[cover_media_id],
    )
    normalized["cover_media_id"] = cover_media_id
    gallery_ids = normalized.get("gallery_media_ids", [])
    if not isinstance(gallery_ids, list):
        raise _invalid("gallery_media_ids", "图集必须是媒体 ID 列表")
    normalized_gallery = [str(item).strip() for item in gallery_ids]
    if not (
        settings.SERVICE_GALLERY_MIN_COUNT
        <= len(normalized_gallery)
        <= settings.SERVICE_GALLERY_MAX_COUNT
    ):
        raise _invalid(
            "gallery_media_ids",
            f"图集必须为 {settings.SERVICE_GALLERY_MIN_COUNT} 到 "
            f"{settings.SERVICE_GALLERY_MAX_COUNT} 张",
        )
    if len(set(normalized_gallery)) != len(normalized_gallery):
        raise _invalid("gallery_media_ids", "图集媒体不能重复")
    get_available_media(
        user=user,
        purpose=PROVIDER_SERVICE_GALLERY,
        media_ids=normalized_gallery,
    )
    normalized["gallery_media_ids"] = normalized_gallery
    tag_codes = normalized.get("tag_codes", [])
    if not isinstance(tag_codes, list):
        raise _invalid("tag_codes", "服务标签必须是代码列表")
    normalized_tags = [str(code).strip() for code in tag_codes]
    if len(normalized_tags) > settings.SERVICE_TAG_MAX_COUNT:
        raise _invalid("tag_codes", f"最多选择 {settings.SERVICE_TAG_MAX_COUNT} 个服务标签")
    if len(set(normalized_tags)) != len(normalized_tags):
        raise _invalid("tag_codes", "服务标签不能重复")
    if ServiceTag.objects.filter(code__in=normalized_tags, is_active=True).count() != len(
        normalized_tags
    ):
        raise ApiError(
            ErrorCode.SERVICE_OPTION_UNAVAILABLE,
            ERROR_MESSAGES[ErrorCode.SERVICE_OPTION_UNAVAILABLE],
            status_code=400,
            details={"tag_codes": "服务标签不存在或已停用"},
        )
    normalized["tag_codes"] = normalized_tags
    if normalized.get("location_type", "PUBLIC_PLACE") != "PUBLIC_PLACE":
        raise _invalid("location_type", "当前仅支持公共场所")
    normalized["location_type"] = "PUBLIC_PLACE"
    return normalized


def _service_payload(
    service: ProviderService, request: HttpRequest | None = None
) -> dict[str, Any]:
    gallery_ids = [link.media_id for link in service.gallery_links.all().order_by("position", "id")]
    cover_media = get_media_payloads([service.cover_media_id], request)
    return {
        "id": str(service.public_id),
        "version": service.version,
        "title": service.title,
        "category_code": service.category.code,
        "pricing_unit": "HOUR",
        "price": {
            "currency": service.currency,
            "amount_minor": service.price_amount_minor,
        },
        "price_display": format_price_amount(
            service.price_amount_minor,
            service.currency,
        ),
        "duration_minutes": service.duration_minutes,
        "introduction": service.introduction,
        "cover_media": cover_media[0] if cover_media else None,
        "gallery_media": get_media_payloads(gallery_ids, request),
        "tag_codes": [link.tag.code for link in service.tag_links.all().order_by("position", "id")],
        "location_type": service.location_type,
        "status": service.status,
        "reject_reason": service.reject_reason,
        "sold_count": service.sold_count,
        "updated_at": service.updated_at,
    }


def service_payload(service: ProviderService, request: HttpRequest | None = None) -> dict[str, Any]:
    """返回服务安全摘要，金额使用最小单位并提供只读展示字符串。"""

    return _service_payload(service, request)


def service_schedule_summary(service: ProviderService) -> dict[str, Any]:
    """返回排期和预约所需的最小服务摘要，不暴露审核和运营字段。"""

    return {
        "id": str(service.public_id),
        "title": service.title,
        "duration_minutes": service.duration_minutes,
        "pricing_unit": "HOUR",
        "price": {
            "currency": service.currency,
            "amount_minor": service.price_amount_minor,
        },
        "price_display": format_price_amount(
            service.price_amount_minor,
            service.currency,
        ),
    }


def _record_event(
    *,
    service: ProviderService,
    event_type: str,
    from_status: str,
    actor_user_id: int | None,
    reason: str = "",
) -> None:
    ProviderServiceEvent.objects.create(
        service=service,
        event_type=event_type,
        from_status=from_status,
        to_status=service.status,
        actor_user_id=actor_user_id,
        reason=reason,
        trace_id=current_trace_id(),
    )


def _service_fingerprint(payload: dict[str, Any]) -> str:
    return sensitive_fingerprint(payload)


def create_service(
    *,
    user: User,
    payload: dict[str, Any],
    idempotency_key: str | None = None,
) -> ServiceUpdateResult:
    """创建服务草稿并处理创建幂等。"""

    require_provider_enabled(user)
    get_provider_profile(user)
    payload = validate_service_payload(user, payload)
    normalized_key = _normalize_idempotency_key(idempotency_key)
    fingerprint = _service_fingerprint(payload)
    try:
        with transaction.atomic():
            if normalized_key:
                existing = ProviderService.objects.filter(
                    provider_user=user,
                    idempotency_key=normalized_key,
                    deleted_at__isnull=True,
                ).first()
                if existing:
                    if existing.request_fingerprint != fingerprint:
                        raise ApiError(
                            ErrorCode.SERVICE_IDEMPOTENCY_CONFLICT,
                            ERROR_MESSAGES[ErrorCode.SERVICE_IDEMPOTENCY_CONFLICT],
                            status_code=409,
                        )
                    return ServiceUpdateResult(existing, changed=False, reused=True)
            service = ProviderService.objects.create(
                provider_user=user,
                category_id=payload["category_code"],
                title=payload["title"],
                currency=payload["currency"],
                price_amount_minor=payload["price_amount_minor"],
                duration_minutes=payload["duration_minutes"],
                introduction=payload["introduction"],
                cover_media_id=payload["cover_media_id"],
                location_type=payload["location_type"],
                idempotency_key=normalized_key,
                request_fingerprint=fingerprint,
            )
            ProviderServiceGalleryMedia.objects.bulk_create(
                [
                    ProviderServiceGalleryMedia(
                        service=service,
                        media_id=media_id,
                        position=position,
                    )
                    for position, media_id in enumerate(payload["gallery_media_ids"])
                ]
            )
            ProviderServiceTag.objects.bulk_create(
                [
                    ProviderServiceTag(
                        service=service,
                        tag_id=code,
                        position=position,
                    )
                    for position, code in enumerate(payload["tag_codes"])
                ]
            )
            _record_event(
                service=service,
                event_type=ProviderServiceEvent.EventType.CREATED,
                from_status="",
                actor_user_id=user.id,
            )
            mark_media_referenced([payload["cover_media_id"], *payload["gallery_media_ids"]])
            return ServiceUpdateResult(service, changed=True)
    except IntegrityError as exc:
        if normalized_key:
            existing = ProviderService.objects.filter(
                provider_user=user,
                idempotency_key=normalized_key,
                deleted_at__isnull=True,
            ).first()
            if existing and existing.request_fingerprint == fingerprint:
                return ServiceUpdateResult(existing, changed=False, reused=True)
        raise ApiError(
            ErrorCode.SERVICE_IDEMPOTENCY_CONFLICT,
            ERROR_MESSAGES[ErrorCode.SERVICE_IDEMPOTENCY_CONFLICT],
            status_code=409,
        ) from exc


def _get_owned_service(*, user: User, service_id: str) -> ProviderService:
    service = (
        ProviderService.objects.select_related("category")
        .filter(public_id=service_id, provider_user=user, deleted_at__isnull=True)
        .first()
    )
    if service is None:
        raise ApiError(
            ErrorCode.SERVICE_NOT_FOUND,
            ERROR_MESSAGES[ErrorCode.SERVICE_NOT_FOUND],
            status_code=404,
        )
    return service


def update_service(
    *,
    user: User,
    service_id: str,
    payload: dict[str, Any],
    expected_version: int,
) -> ServiceUpdateResult:
    """修改草稿或被拒绝服务，不允许覆盖并发修改。"""

    require_provider_enabled(user)
    get_provider_profile(user)
    payload = validate_service_payload(user, payload)
    with transaction.atomic():
        service = (
            ProviderService.objects.select_for_update()
            .select_related("category")
            .filter(public_id=service_id, provider_user=user, deleted_at__isnull=True)
            .first()
        )
        if service is None:
            raise ApiError(
                ErrorCode.SERVICE_NOT_FOUND,
                ERROR_MESSAGES[ErrorCode.SERVICE_NOT_FOUND],
                status_code=404,
            )
        if service.status not in {
            ProviderService.Status.DRAFT,
            ProviderService.Status.REJECTED,
        }:
            raise ApiError(
                ErrorCode.SERVICE_STATE_INVALID,
                ERROR_MESSAGES[ErrorCode.SERVICE_STATE_INVALID],
                status_code=409,
            )
        if service.version != expected_version:
            raise ApiError(
                ErrorCode.SERVICE_VERSION_CONFLICT,
                ERROR_MESSAGES[ErrorCode.SERVICE_VERSION_CONFLICT],
                status_code=409,
            )
        previous_status = service.status
        service.category_id = payload["category_code"]
        service.title = payload["title"]
        service.currency = payload["currency"]
        service.price_amount_minor = payload["price_amount_minor"]
        service.duration_minutes = payload["duration_minutes"]
        service.introduction = payload["introduction"]
        service.cover_media_id = payload["cover_media_id"]
        service.location_type = payload["location_type"]
        service.version += 1
        service.save()
        service.gallery_links.all().delete()
        ProviderServiceGalleryMedia.objects.bulk_create(
            [
                ProviderServiceGalleryMedia(
                    service=service,
                    media_id=media_id,
                    position=position,
                )
                for position, media_id in enumerate(payload["gallery_media_ids"])
            ]
        )
        service.tag_links.all().delete()
        ProviderServiceTag.objects.bulk_create(
            [
                ProviderServiceTag(
                    service=service,
                    tag_id=code,
                    position=position,
                )
                for position, code in enumerate(payload["tag_codes"])
            ]
        )
        _record_event(
            service=service,
            event_type=ProviderServiceEvent.EventType.UPDATED,
            from_status=previous_status,
            actor_user_id=user.id,
        )
        mark_media_referenced([payload["cover_media_id"], *payload["gallery_media_ids"]])
        return ServiceUpdateResult(service, changed=True)


def _transition_service(
    *,
    user: User,
    service_id: str,
    expected_version: int,
    allowed_statuses: set[str],
    new_status: str,
    event_type: str,
    actor_user_id: int | None = None,
    reason: str = "",
) -> ProviderService:
    with transaction.atomic():
        service = (
            ProviderService.objects.select_for_update()
            .select_related("category")
            .filter(public_id=service_id, provider_user=user, deleted_at__isnull=True)
            .first()
        )
        if service is None:
            raise ApiError(
                ErrorCode.SERVICE_NOT_FOUND,
                ERROR_MESSAGES[ErrorCode.SERVICE_NOT_FOUND],
                status_code=404,
            )
        if service.status not in allowed_statuses:
            raise ApiError(
                ErrorCode.SERVICE_STATE_INVALID,
                ERROR_MESSAGES[ErrorCode.SERVICE_STATE_INVALID],
                status_code=409,
            )
        if service.version != expected_version:
            raise ApiError(
                ErrorCode.SERVICE_VERSION_CONFLICT,
                ERROR_MESSAGES[ErrorCode.SERVICE_VERSION_CONFLICT],
                status_code=409,
            )
        previous_status = service.status
        service.status = new_status
        service.version += 1
        service.save(update_fields=["status", "version", "updated_at"])
        _record_event(
            service=service,
            event_type=event_type,
            from_status=previous_status,
            actor_user_id=actor_user_id or user.id,
            reason=reason,
        )
        return service


def submit_service_for_review(
    *,
    user: User,
    service_id: str,
    expected_version: int,
) -> ProviderService:
    """将草稿或被拒绝服务提交审核。"""

    require_provider_enabled(user)
    get_provider_profile(user)
    return _transition_service(
        user=user,
        service_id=service_id,
        expected_version=expected_version,
        allowed_statuses={ProviderService.Status.DRAFT, ProviderService.Status.REJECTED},
        new_status=ProviderService.Status.PENDING,
        event_type=ProviderServiceEvent.EventType.SUBMITTED,
    )


def review_service(
    *,
    service_id: str,
    approve: bool,
    reviewer: User,
    expected_version: int,
    reason: str = "",
) -> ProviderService:
    """管理员审核服务并记录不可变状态事件。"""

    normalized_reason = reason.strip()
    if not approve and len(normalized_reason) < 2:
        raise _invalid("reason", "拒绝原因至少需要 2 个字符")
    with transaction.atomic():
        service = (
            ProviderService.objects.select_for_update()
            .select_related("category")
            .filter(public_id=service_id, deleted_at__isnull=True)
            .first()
        )
        if service is None:
            raise ApiError(
                ErrorCode.SERVICE_NOT_FOUND,
                ERROR_MESSAGES[ErrorCode.SERVICE_NOT_FOUND],
                status_code=404,
            )
        if service.status != ProviderService.Status.PENDING:
            raise ApiError(
                ErrorCode.SERVICE_STATE_INVALID,
                ERROR_MESSAGES[ErrorCode.SERVICE_STATE_INVALID],
                status_code=409,
            )
        if service.version != expected_version:
            raise ApiError(
                ErrorCode.SERVICE_VERSION_CONFLICT,
                ERROR_MESSAGES[ErrorCode.SERVICE_VERSION_CONFLICT],
                status_code=409,
            )
        previous_status = service.status
        service.status = (
            ProviderService.Status.APPROVED if approve else ProviderService.Status.REJECTED
        )
        service.reject_reason = "" if approve else normalized_reason
        service.reviewer_id = reviewer.id
        service.reviewed_at = timezone.now()
        service.version += 1
        service.save()
        _record_event(
            service=service,
            event_type=(
                ProviderServiceEvent.EventType.APPROVED
                if approve
                else ProviderServiceEvent.EventType.REJECTED
            ),
            from_status=previous_status,
            actor_user_id=reviewer.id,
            reason=normalized_reason,
        )
        return service


def change_service_visibility(
    *,
    user: User,
    service_id: str,
    expected_version: int,
    online: bool,
) -> ProviderService:
    """上架或下架服务。"""

    require_provider_enabled(user)
    get_provider_profile(user)
    return _transition_service(
        user=user,
        service_id=service_id,
        expected_version=expected_version,
        allowed_statuses=(
            {ProviderService.Status.APPROVED, ProviderService.Status.OFFLINE}
            if online
            else {ProviderService.Status.ONLINE}
        ),
        new_status=(ProviderService.Status.ONLINE if online else ProviderService.Status.OFFLINE),
        event_type=(
            ProviderServiceEvent.EventType.ONLINE
            if online
            else ProviderServiceEvent.EventType.OFFLINE
        ),
    )


def delete_service(*, user: User, service_id: str, expected_version: int) -> None:
    """逻辑删除草稿或被拒绝服务，保留服务事件记录。"""

    require_provider_enabled(user)
    get_provider_profile(user)
    with transaction.atomic():
        service = (
            ProviderService.objects.select_for_update()
            .filter(public_id=service_id, provider_user=user, deleted_at__isnull=True)
            .first()
        )
        if service is None:
            raise ApiError(
                ErrorCode.SERVICE_NOT_FOUND,
                ERROR_MESSAGES[ErrorCode.SERVICE_NOT_FOUND],
                status_code=404,
            )
        if service.status not in {
            ProviderService.Status.DRAFT,
            ProviderService.Status.REJECTED,
        }:
            raise ApiError(
                ErrorCode.SERVICE_STATE_INVALID,
                ERROR_MESSAGES[ErrorCode.SERVICE_STATE_INVALID],
                status_code=409,
            )
        if service.version != expected_version:
            raise ApiError(
                ErrorCode.SERVICE_VERSION_CONFLICT,
                ERROR_MESSAGES[ErrorCode.SERVICE_VERSION_CONFLICT],
                status_code=409,
            )
        previous_status = service.status
        service.deleted_at = timezone.now()
        service.version += 1
        service.save(update_fields=["deleted_at", "version", "updated_at"])
        _record_event(
            service=service,
            event_type=ProviderServiceEvent.EventType.DELETED,
            from_status=previous_status,
            actor_user_id=user.id,
        )


def get_service_payload(
    user: User,
    service_id: str,
    request: HttpRequest | None = None,
) -> dict[str, Any]:
    """返回服务者本人可读的单个服务安全摘要。"""

    require_provider_enabled(user)
    get_provider_profile(user)
    return service_payload(_get_owned_service(user=user, service_id=service_id), request)


def get_public_service_payload(
    service_id: str,
    request: HttpRequest | None = None,
) -> dict[str, Any]:
    """返回公开可见的已上架服务详情。"""

    service = (
        ProviderService.objects.select_related("category", "provider_user")
        .filter(
            public_id=service_id,
            status=ProviderService.Status.ONLINE,
            deleted_at__isnull=True,
        )
        .first()
    )
    if service is None:
        raise ApiError(
            ErrorCode.NOT_FOUND,
            ERROR_MESSAGES[ErrorCode.NOT_FOUND],
            status_code=404,
            details={"service_id": "服务不存在或不可见"},
        )
    return service_payload(service, request)


def list_service_payloads(
    *,
    user: User,
    status: str | None,
    page: int,
    page_size: int,
    request: HttpRequest | None = None,
) -> dict[str, Any]:
    """返回服务者后台服务列表、汇总和页码信息。"""

    require_provider_enabled(user)
    get_provider_profile(user)
    base_queryset = ProviderService.objects.select_related("category").filter(
        provider_user=user,
        deleted_at__isnull=True,
    )
    queryset = base_queryset
    if status:
        if status not in ProviderService.Status.values:
            raise _invalid("status", "服务状态不存在")
        queryset = queryset.filter(status=status)
    total = queryset.count()
    summary = base_queryset.aggregate(
        total=Count("id"),
        online=Count("id", filter=Q(status=ProviderService.Status.ONLINE)),
        pending=Count("id", filter=Q(status=ProviderService.Status.PENDING)),
        sold_count=Sum("sold_count"),
    )
    start = (page - 1) * page_size
    items = [
        service_payload(service, request)
        for service in queryset.order_by("-updated_at", "-id")[start : start + page_size]
    ]
    return {
        "items": items,
        "total": total,
        "page": page,
        "page_size": page_size,
        "summary": {
            "total": summary["total"] or 0,
            "online": summary["online"] or 0,
            "pending": summary["pending"] or 0,
            "sold_count": summary["sold_count"] or 0,
        },
    }


def admin_service_payload(
    service: ProviderService,
    request: HttpRequest | None = None,
) -> dict[str, Any]:
    """返回管理员查看服务所需的安全服务和归属摘要。"""

    profile = getattr(service.provider_user, "provider_profile", None)
    return {
        **service_payload(service, request),
        "provider": {
            "user_public_id": str(service.provider_user.public_id),
            "nickname": profile.nickname if profile else None,
            "phone_masked": service.provider_user.phone_masked,
        },
    }


def list_admin_service_payloads(
    *,
    status: str | None,
    provider_public_id: str | None,
    category_code: str | None,
    keyword: str | None,
    page: int,
    page_size: int,
    request: HttpRequest | None = None,
) -> dict[str, Any]:
    """返回全平台服务管理列表和状态汇总。"""

    queryset = ProviderService.objects.select_related(
        "category",
        "provider_user",
        "provider_user__provider_profile",
    ).filter(deleted_at__isnull=True)
    if status:
        if status not in ProviderService.Status.values:
            raise _invalid("status", "服务状态不存在")
        queryset = queryset.filter(status=status)
    if provider_public_id:
        queryset = queryset.filter(provider_user__public_id=provider_public_id)
    if category_code:
        queryset = queryset.filter(category_id=category_code)
    if keyword:
        search = keyword.strip()
        queryset = queryset.filter(
            Q(title__icontains=search)
            | Q(provider_user__provider_profile__nickname__icontains=search)
        )
    total = queryset.count()
    summary = ProviderService.objects.filter(deleted_at__isnull=True).aggregate(
        total=Count("id"),
        draft=Count("id", filter=Q(status=ProviderService.Status.DRAFT)),
        pending=Count("id", filter=Q(status=ProviderService.Status.PENDING)),
        approved=Count("id", filter=Q(status=ProviderService.Status.APPROVED)),
        online=Count("id", filter=Q(status=ProviderService.Status.ONLINE)),
        offline=Count("id", filter=Q(status=ProviderService.Status.OFFLINE)),
        rejected=Count("id", filter=Q(status=ProviderService.Status.REJECTED)),
        sold_count=Sum("sold_count"),
    )
    start = (page - 1) * page_size
    items = [
        admin_service_payload(service, request)
        for service in queryset.order_by("-updated_at", "-id")[start : start + page_size]
    ]
    return {
        "items": items,
        "total": total,
        "page": page,
        "page_size": page_size,
        "summary": {
            "total": summary["total"] or 0,
            "draft": summary["draft"] or 0,
            "pending": summary["pending"] or 0,
            "approved": summary["approved"] or 0,
            "online": summary["online"] or 0,
            "offline": summary["offline"] or 0,
            "rejected": summary["rejected"] or 0,
            "sold_count": summary["sold_count"] or 0,
        },
    }


def service_category_payloads() -> list[dict[str, Any]]:
    """返回启用中的服务类目配置。"""

    return [
        {"code": item.code, "name": item.name, "sort_order": item.sort_order}
        for item in ServiceCategory.objects.filter(is_active=True)
    ]


def service_tag_payloads() -> list[dict[str, Any]]:
    """返回启用中的服务标签配置。"""

    return [
        {
            "code": item.code,
            "name": item.name,
            "category": item.category,
            "sort_order": item.sort_order,
        }
        for item in ServiceTag.objects.filter(is_active=True)
    ]


def provider_tag_payloads() -> list[dict[str, Any]]:
    """返回启用中的服务者资料标签配置。"""

    return [
        {
            "code": item.code,
            "name": item.name,
            "category": item.category,
            "sort_order": item.sort_order,
        }
        for item in ProviderTag.objects.filter(is_active=True)
    ]
