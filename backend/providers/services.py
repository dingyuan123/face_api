"""服务陪伴者入驻申请、媒体引用、审核和状态事件业务服务。"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from django.conf import settings
from django.db import IntegrityError, transaction
from django.http import HttpRequest
from django.utils import timezone

from backend.accounts.models import User
from backend.common.context import current_trace_id
from backend.common.crypto import (
    decrypt_text,
    encrypt_text,
    hash_sensitive_text,
    sensitive_fingerprint,
)
from backend.common.display import enum_label
from backend.common.errors import ERROR_MESSAGES, ErrorCode
from backend.common.exceptions import ApiError
from backend.identity.models import IdentityVerification
from backend.identity.services import submit_real_name_verification
from backend.media.services import (
    IDENTITY_CARD_BACK,
    IDENTITY_CARD_FRONT,
    PROVIDER_APPLICATION_AVATAR,
    PROVIDER_APPLICATION_LIFE_PHOTO,
    get_available_media,
    get_media_payloads,
    mark_media_referenced,
)
from backend.providers.models import ProviderApplication, ProviderApplicationEvent

REAL_NAME_PATTERN = re.compile(r"^[A-Za-z\u3400-\u9fff\u00b7\s]{2,30}$")
MEDIA_ID_PATTERN = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)
ID_CARD_WEIGHTS = [7, 9, 10, 5, 8, 4, 2, 1, 6, 3, 7, 9, 10, 5, 8, 4, 2]
ID_CARD_CHECK_CODES = "10X98765432"
PHONE_PATTERN = re.compile(r"^1[3-9]\d{9}$")


@dataclass(frozen=True)
class ApplicationResult:
    """申请命令执行结果，标记是否复用已有幂等请求。"""

    application: ProviderApplication
    reused: bool


def _fingerprint(payload: dict[str, Any]) -> str:
    return sensitive_fingerprint(payload)


def validate_application_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """校验并规范化申请资料，不保存或返回真实姓名和证件明文。"""
    details: dict[str, str] = {}
    introduction = str(payload.get("introduction", "")).strip()
    real_name = str(payload.get("real_name", "")).strip()
    id_card_number = str(payload.get("id_card_number", "")).strip().upper()
    avatar_media_id = str(payload.get("avatar_media_id", "")).strip()
    id_card_front_media_id = str(payload.get("id_card_front_media_id", "")).strip()
    id_card_back_media_id = str(payload.get("id_card_back_media_id", "")).strip()
    emergency_contact_name = str(payload.get("emergency_contact_name", "")).strip()
    emergency_contact_phone = (
        str(payload.get("emergency_contact_phone", "")).strip().replace(" ", "")
    )
    life_photo_media_ids = payload.get("life_photo_media_ids", [])

    introduction_min = settings.PROVIDER_APPLICATION_INTRODUCTION_MIN_LENGTH
    introduction_max = settings.PROVIDER_APPLICATION_INTRODUCTION_MAX_LENGTH
    if not introduction_min <= len(introduction) <= introduction_max:
        details["introduction"] = f"长度必须在 {introduction_min} 到 {introduction_max} 之间"
    if not REAL_NAME_PATTERN.fullmatch(real_name) or not real_name.replace(" ", ""):
        details["real_name"] = "真实姓名格式不正确"
    if not _is_valid_id_card(id_card_number):
        details["id_card_number"] = "身份证号格式不正确"
    if not MEDIA_ID_PATTERN.fullmatch(avatar_media_id):
        details["avatar_media_id"] = "头像资源标识不正确"
    if not MEDIA_ID_PATTERN.fullmatch(id_card_front_media_id):
        details["id_card_front_media_id"] = "身份证正面照片资源标识不正确"
    if not MEDIA_ID_PATTERN.fullmatch(id_card_back_media_id):
        details["id_card_back_media_id"] = "身份证反面照片资源标识不正确"
    if not REAL_NAME_PATTERN.fullmatch(emergency_contact_name):
        details["emergency_contact_name"] = "紧急联系人姓名格式不正确"
    if not PHONE_PATTERN.fullmatch(emergency_contact_phone):
        details["emergency_contact_phone"] = "紧急联系人手机号格式不正确"

    photo_min = settings.PROVIDER_APPLICATION_MIN_LIFE_PHOTOS
    photo_max = settings.PROVIDER_APPLICATION_MAX_LIFE_PHOTOS
    if not isinstance(life_photo_media_ids, list):
        details["life_photo_media_ids"] = "生活照必须是资源标识列表"
        normalized_photos: list[str] = []
    else:
        normalized_photos = [str(item).strip() for item in life_photo_media_ids]
        if not photo_min <= len(normalized_photos) <= photo_max:
            details["life_photo_media_ids"] = f"生活照数量必须在 {photo_min} 到 {photo_max} 之间"
        if any(not MEDIA_ID_PATTERN.fullmatch(item) for item in normalized_photos):
            details["life_photo_media_ids"] = "生活照资源标识不正确"
        if len(set(normalized_photos)) != len(normalized_photos):
            details["life_photo_media_ids"] = "生活照不能重复"

    if photo_min > photo_max:
        details["life_photo_media_ids"] = "生活照数量配置无效"
    if details:
        raise ApiError(
            ErrorCode.PROVIDER_APPLICATION_INVALID,
            ERROR_MESSAGES[ErrorCode.PROVIDER_APPLICATION_INVALID],
            status_code=400,
            details=details,
        )
    return {
        "introduction": introduction,
        "real_name": real_name,
        "id_card_number": id_card_number,
        "avatar_media_id": avatar_media_id,
        "id_card_front_media_id": id_card_front_media_id,
        "id_card_back_media_id": id_card_back_media_id,
        "emergency_contact_name": emergency_contact_name,
        "emergency_contact_phone": emergency_contact_phone,
        "life_photo_media_ids": normalized_photos,
    }


def _is_valid_id_card(value: str) -> bool:
    if len(value) != 18 or not value[:17].isdigit():
        return False
    checksum = sum(
        int(character) * weight
        for character, weight in zip(value[:17], ID_CARD_WEIGHTS, strict=True)
    )
    return value[-1].upper() == ID_CARD_CHECK_CODES[checksum % 11]


def _record_event(
    *,
    application: ProviderApplication,
    event_type: str,
    from_status: str,
    actor: User | None = None,
    reason: str = "",
) -> None:
    ProviderApplicationEvent.objects.create(
        application=application,
        event_type=event_type,
        from_status=from_status,
        to_status=application.status,
        actor=actor,
        reason=reason,
        trace_id=current_trace_id(),
    )


def _validate_media_assets(user: User, payload: dict[str, Any]) -> None:
    get_available_media(
        user=user,
        purpose=PROVIDER_APPLICATION_AVATAR,
        media_ids=[payload["avatar_media_id"]],
    )
    get_available_media(
        user=user,
        purpose=PROVIDER_APPLICATION_LIFE_PHOTO,
        media_ids=payload["life_photo_media_ids"],
    )
    get_available_media(
        user=user,
        purpose=IDENTITY_CARD_FRONT,
        media_ids=[payload["id_card_front_media_id"]],
    )
    get_available_media(
        user=user,
        purpose=IDENTITY_CARD_BACK,
        media_ids=[payload["id_card_back_media_id"]],
    )


def _mark_media_referenced(payload: dict[str, Any]) -> None:
    mark_media_referenced(
        [
            payload["avatar_media_id"],
            payload["id_card_front_media_id"],
            payload["id_card_back_media_id"],
            *payload["life_photo_media_ids"],
        ]
    )


def _mask_phone(value: str) -> str:
    """返回不泄露完整号码的紧急联系人手机号展示值。"""
    return f"{value[:3]}****{value[-4:]}" if len(value) >= 7 else "****"


def submit_provider_application(
    *,
    user: User,
    payload: dict[str, Any],
    idempotency_key: str | None = None,
) -> ApplicationResult:
    """提交服务者申请，并处理幂等、单活动申请约束和媒体所有权。"""
    if not user.initial_role_selected:
        raise ApiError(
            ErrorCode.USER_INITIAL_ROLE_REQUIRED,
            ERROR_MESSAGES[ErrorCode.USER_INITIAL_ROLE_REQUIRED],
            status_code=409,
        )

    payload = validate_application_payload(payload)
    normalized_key = _normalize_idempotency_key(idempotency_key)
    fingerprint = _fingerprint(payload)
    try:
        with transaction.atomic():
            if normalized_key:
                existing = ProviderApplication.objects.filter(
                    user=user,
                    idempotency_key=normalized_key,
                ).first()
                if existing:
                    if existing.request_fingerprint != fingerprint:
                        raise ApiError(
                            ErrorCode.AUTH_IDEMPOTENCY_CONFLICT,
                            ERROR_MESSAGES[ErrorCode.AUTH_IDEMPOTENCY_CONFLICT],
                            status_code=409,
                        )
                    return ApplicationResult(existing, reused=True)

            active_exists = ProviderApplication.objects.filter(
                user=user,
                status__in=[
                    ProviderApplication.Status.PENDING,
                    ProviderApplication.Status.APPROVED,
                ],
            ).exists()
            if active_exists:
                raise ApiError(
                    ErrorCode.PROVIDER_APPLICATION_CONFLICT,
                    ERROR_MESSAGES[ErrorCode.PROVIDER_APPLICATION_CONFLICT],
                    status_code=409,
                )
            _validate_media_assets(user, payload)

            existing_identity = IdentityVerification.objects.filter(
                user=user,
                verification_type=IdentityVerification.Type.REAL_NAME,
            ).first()
            if (
                existing_identity is not None
                and existing_identity.status == IdentityVerification.Status.PASSED
            ):
                real_name_verification = existing_identity
            else:
                real_name_verification = submit_real_name_verification(
                    user=user,
                    payload=payload,
                    expected_version=existing_identity.version if existing_identity else 0,
                    idempotency_key=(
                        f"provider-real-name:{hash_sensitive_text(payload['id_card_number'])}"
                    ),
                )
            application = ProviderApplication.objects.create(
                application_no=ProviderApplication.make_application_no(),
                user=user,
                status=ProviderApplication.Status.PENDING,
                introduction=payload["introduction"],
                real_name_encrypted=encrypt_text(payload["real_name"]),
                id_card_encrypted=encrypt_text(payload["id_card_number"]),
                id_card_hash=hash_sensitive_text(payload["id_card_number"]),
                id_card_front_media_id=payload["id_card_front_media_id"],
                id_card_back_media_id=payload["id_card_back_media_id"],
                emergency_contact_name_encrypted=encrypt_text(payload["emergency_contact_name"]),
                emergency_contact_phone_encrypted=encrypt_text(payload["emergency_contact_phone"]),
                emergency_contact_phone_masked=_mask_phone(payload["emergency_contact_phone"]),
                avatar_media_id=payload["avatar_media_id"],
                life_photo_media_ids=payload["life_photo_media_ids"],
                real_name_status=real_name_verification.status,
                face_status=IdentityVerification.Status.NOT_SUBMITTED,
                idempotency_key=normalized_key,
                request_fingerprint=fingerprint,
            )
            _record_event(
                application=application,
                event_type=ProviderApplicationEvent.EventType.SUBMITTED,
                from_status="",
            )
            _mark_media_referenced(payload)
            User.objects.filter(pk=user.pk).update(
                provider_status=User.ProviderStatus.PENDING,
                updated_at=timezone.now(),
            )
            return ApplicationResult(application, reused=False)
    except IntegrityError as exc:
        if normalized_key:
            existing = ProviderApplication.objects.filter(
                user=user,
                idempotency_key=normalized_key,
            ).first()
            if existing and existing.request_fingerprint == fingerprint:
                return ApplicationResult(existing, reused=True)
        raise ApiError(
            ErrorCode.PROVIDER_APPLICATION_CONFLICT,
            ERROR_MESSAGES[ErrorCode.PROVIDER_APPLICATION_CONFLICT],
            status_code=409,
        ) from exc


def _normalize_idempotency_key(value: str | None) -> str | None:
    if value is None:
        return None
    key = value.strip()
    if not key or len(key) > 128:
        raise ApiError(
            ErrorCode.AUTH_IDEMPOTENCY_CONFLICT,
            "Idempotency-Key 长度必须在 1 到 128 之间",
            status_code=400,
        )
    return key


def get_application_for_user(user: User) -> ProviderApplication | None:
    """查询用户最近一次服务者申请。"""
    return ProviderApplication.objects.filter(user=user).order_by("-submitted_at").first()


def current_application_payload(
    user: User,
    request: HttpRequest | None = None,
) -> dict[str, Any]:
    """返回当前用户最新服务者申请的脱敏摘要。"""
    return application_payload(get_application_for_user(user), user, request)


def update_application(
    *,
    user: User,
    payload: dict[str, Any],
    expected_version: int,
) -> ApplicationResult:
    """对被拒绝或已取消申请执行乐观锁校验后重新提交。"""
    payload = validate_application_payload(payload)
    with transaction.atomic():
        application = (
            ProviderApplication.objects.select_for_update()
            .filter(user=user)
            .order_by("-submitted_at")
            .first()
        )
        if application is None:
            raise ApiError(
                ErrorCode.PROVIDER_APPLICATION_NOT_FOUND,
                ERROR_MESSAGES[ErrorCode.PROVIDER_APPLICATION_NOT_FOUND],
                status_code=404,
            )
        if application.status not in {
            ProviderApplication.Status.REJECTED,
            ProviderApplication.Status.CANCELLED,
        }:
            raise ApiError(
                ErrorCode.PROVIDER_APPLICATION_STATE_INVALID,
                ERROR_MESSAGES[ErrorCode.PROVIDER_APPLICATION_STATE_INVALID],
                status_code=409,
            )
        if application.version != expected_version:
            raise ApiError(
                ErrorCode.PROVIDER_APPLICATION_VERSION_CONFLICT,
                ERROR_MESSAGES[ErrorCode.PROVIDER_APPLICATION_VERSION_CONFLICT],
                status_code=409,
            )
        _validate_media_assets(user, payload)

        existing_identity = IdentityVerification.objects.filter(
            user=user,
            verification_type=IdentityVerification.Type.REAL_NAME,
        ).first()
        if (
            existing_identity is not None
            and existing_identity.status == IdentityVerification.Status.PASSED
        ):
            real_name_verification = existing_identity
        else:
            real_name_verification = submit_real_name_verification(
                user=user,
                payload=payload,
                expected_version=existing_identity.version if existing_identity else 0,
                idempotency_key=(
                    f"provider-real-name:{hash_sensitive_text(payload['id_card_number'])}"
                ),
            )
        previous_status = application.status
        application.introduction = payload["introduction"]
        application.real_name_encrypted = encrypt_text(payload["real_name"])
        application.id_card_encrypted = encrypt_text(payload["id_card_number"])
        application.id_card_hash = hash_sensitive_text(payload["id_card_number"])
        application.id_card_front_media_id = payload["id_card_front_media_id"]
        application.id_card_back_media_id = payload["id_card_back_media_id"]
        application.emergency_contact_name_encrypted = encrypt_text(
            payload["emergency_contact_name"]
        )
        application.emergency_contact_phone_encrypted = encrypt_text(
            payload["emergency_contact_phone"]
        )
        application.emergency_contact_phone_masked = _mask_phone(payload["emergency_contact_phone"])
        application.avatar_media_id = payload["avatar_media_id"]
        application.life_photo_media_ids = payload["life_photo_media_ids"]
        application.real_name_status = real_name_verification.status
        application.face_status = IdentityVerification.Status.NOT_SUBMITTED
        application.status = ProviderApplication.Status.PENDING
        application.reject_reason = ""
        application.version += 1
        application.save()
        _record_event(
            application=application,
            event_type=ProviderApplicationEvent.EventType.RESUBMITTED,
            from_status=previous_status,
        )
        _mark_media_referenced(payload)
        User.objects.filter(pk=user.pk).update(
            provider_status=User.ProviderStatus.PENDING,
            updated_at=timezone.now(),
        )
        return ApplicationResult(application, reused=False)


def review_application(
    *,
    application_no: str,
    approve: bool,
    reviewer: User,
    reason: str = "",
    expected_version: int,
) -> ProviderApplication:
    """管理员审核申请，并在同一事务内更新服务者状态和审核事件。"""
    normalized_reason = reason.strip()
    if not approve and len(normalized_reason) < 2:
        raise ApiError(
            ErrorCode.PROVIDER_APPLICATION_INVALID,
            "拒绝原因至少需要 2 个字符",
            status_code=400,
            details={"reason": "拒绝原因至少需要 2 个字符"},
        )
    with transaction.atomic():
        application = (
            ProviderApplication.objects.select_for_update()
            .select_related("user")
            .filter(application_no=application_no)
            .first()
        )
        if application is None:
            raise ApiError(
                ErrorCode.PROVIDER_APPLICATION_NOT_FOUND,
                ERROR_MESSAGES[ErrorCode.PROVIDER_APPLICATION_NOT_FOUND],
                status_code=404,
            )
        if application.status != ProviderApplication.Status.PENDING:
            raise ApiError(
                ErrorCode.PROVIDER_APPLICATION_STATE_INVALID,
                ERROR_MESSAGES[ErrorCode.PROVIDER_APPLICATION_STATE_INVALID],
                status_code=409,
            )
        if application.version != expected_version:
            raise ApiError(
                ErrorCode.PROVIDER_APPLICATION_VERSION_CONFLICT,
                ERROR_MESSAGES[ErrorCode.PROVIDER_APPLICATION_VERSION_CONFLICT],
                status_code=409,
            )
        if approve:
            identity = IdentityVerification.objects.filter(
                user=application.user,
                verification_type=IdentityVerification.Type.REAL_NAME,
            ).first()
            if identity is None or identity.status != IdentityVerification.Status.PASSED:
                raise ApiError(
                    ErrorCode.PROVIDER_APPLICATION_STATE_INVALID,
                    "实名认证尚未人工审核通过，不能通过服务者申请",
                    status_code=409,
                    details={
                        "real_name_status": identity.status
                        if identity
                        else IdentityVerification.Status.NOT_SUBMITTED
                    },
                )
        previous_status = application.status
        application.status = (
            ProviderApplication.Status.APPROVED if approve else ProviderApplication.Status.REJECTED
        )
        application.reject_reason = "" if approve else normalized_reason
        application.reviewer_id = reviewer.id
        application.reviewed_at = timezone.now()
        application.version += 1
        application.save()
        _record_event(
            application=application,
            event_type=(
                ProviderApplicationEvent.EventType.APPROVED
                if approve
                else ProviderApplicationEvent.EventType.REJECTED
            ),
            from_status=previous_status,
            actor=reviewer,
            reason=normalized_reason,
        )

        if approve:
            application.user.provider_enabled = True
            application.user.provider_status = User.ProviderStatus.APPROVED
            application.user.primary_role = User.InitialRole.PROVIDER
            application.user.default_workspace = User.Workspace.PROVIDER_WORKSPACE
            application.user.save(
                update_fields=[
                    "provider_enabled",
                    "provider_status",
                    "primary_role",
                    "default_workspace",
                    "updated_at",
                ]
            )
        else:
            application.user.provider_status = User.ProviderStatus.REJECTED
            application.user.save(update_fields=["provider_status", "updated_at"])
        return application


def application_payload(
    application: ProviderApplication | None,
    user: User,
    request: HttpRequest | None = None,
) -> dict[str, Any]:
    """生成脱敏申请响应，并附带安全媒体访问信息。"""
    if application is None:
        return {
            "application_no": None,
            "status": "NOT_SUBMITTED",
            "status_text": "未提交",
            "introduction": "",
            "avatar_media_id": None,
            "id_card_front_media_id": None,
            "id_card_back_media_id": None,
            "emergency_contact_name": "",
            "emergency_contact_phone_masked": "",
            "life_photo_media_ids": [],
            "real_name_status": "NOT_SUBMITTED",
            "real_name_status_text": "未提交",
            "face_status": "NOT_SUBMITTED",
            "face_status_text": "未提交",
            "reject_reason": "",
            "submitted_at": None,
            "updated_at": None,
            "version": 0,
            "user_public_id": str(user.public_id),
            "user_phone_masked": user.phone_masked,
            "avatar_media": None,
            "id_card_front_media": None,
            "id_card_back_media": None,
            "life_photo_media": [],
        }
    avatar_media = get_media_payloads(
        [application.avatar_media_id] if application.avatar_media_id else [],
        request,
    )
    id_card_front_media = get_media_payloads(
        [application.id_card_front_media_id] if application.id_card_front_media_id else [],
        request,
    )
    id_card_back_media = get_media_payloads(
        [application.id_card_back_media_id] if application.id_card_back_media_id else [],
        request,
    )
    life_photo_media = get_media_payloads(
        [media_id for media_id in application.life_photo_media_ids if media_id],
        request,
    )
    return {
        "application_no": application.application_no,
        "status": application.status,
        "status_text": enum_label(ProviderApplication.Status, application.status),
        "introduction": application.introduction,
        "avatar_media_id": application.avatar_media_id,
        "id_card_front_media_id": application.id_card_front_media_id or None,
        "id_card_back_media_id": application.id_card_back_media_id or None,
        "emergency_contact_name": decrypt_text(application.emergency_contact_name_encrypted)
        if application.emergency_contact_name_encrypted
        else "",
        "emergency_contact_phone_masked": application.emergency_contact_phone_masked,
        "life_photo_media_ids": application.life_photo_media_ids,
        "real_name_status": application.real_name_status,
        "real_name_status_text": enum_label(
            IdentityVerification.Status,
            application.real_name_status,
        ),
        "face_status": application.face_status,
        "face_status_text": enum_label(
            IdentityVerification.Status,
            application.face_status,
        ),
        "reject_reason": application.reject_reason,
        "submitted_at": application.submitted_at,
        "updated_at": application.updated_at,
        "version": application.version,
        "user_public_id": str(user.public_id),
        "user_phone_masked": user.phone_masked,
        "avatar_media": avatar_media[0] if avatar_media else None,
        "id_card_front_media": id_card_front_media[0] if id_card_front_media else None,
        "id_card_back_media": id_card_back_media[0] if id_card_back_media else None,
        "life_photo_media": life_photo_media,
    }
