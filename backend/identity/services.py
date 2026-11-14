"""实名和人脸认证适配边界；当前提供开发 Mock 实现。"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from typing import Any

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from backend.common.crypto import encrypt_text, hash_sensitive_text, sensitive_fingerprint
from backend.common.errors import ERROR_MESSAGES, ErrorCode
from backend.common.exceptions import ApiError
from backend.identity.models import IdentityVerification
from backend.media.services import (
    IDENTITY_CARD_BACK,
    IDENTITY_CARD_FRONT,
    get_available_media,
    get_media_payloads,
    mark_media_referenced,
)

REAL_NAME_PATTERN = re.compile(r"^[A-Za-z\u3400-\u9fff\u00b7\s]{2,30}$")
MEDIA_ID_PATTERN = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)
ID_CARD_WEIGHTS = [7, 9, 10, 5, 8, 4, 2, 1, 6, 3, 7, 9, 10, 5, 8, 4, 2]
ID_CARD_CHECK_CODES = "10X98765432"


@dataclass(frozen=True)
class MockVerificationResult:
    """开发期 Mock 认证结果，不包含真实证件信息。"""

    status: str
    provider_request_no: str
    result_code: str


def verify_real_name_mock(*, real_name: str, id_card_number: str) -> MockVerificationResult:
    """开发期实名 Mock；仅校验输入非空并返回 MOCK_PASSED。"""
    if not settings.IDENTITY_MOCK_ENABLED:
        raise ApiError(
            ErrorCode.IDENTITY_VERIFICATION_UNAVAILABLE,
            ERROR_MESSAGES[ErrorCode.IDENTITY_VERIFICATION_UNAVAILABLE],
            status_code=503,
        )
    if not real_name.strip() or not id_card_number.strip():
        raise ApiError(
            ErrorCode.PROVIDER_APPLICATION_INVALID,
            ERROR_MESSAGES[ErrorCode.PROVIDER_APPLICATION_INVALID],
            status_code=400,
        )
    return MockVerificationResult(
        status=IdentityVerification.Status.MOCK_PASSED,
        provider_request_no=f"mock-real-name-{uuid.uuid4().hex}",
        result_code="MOCK_PASSED",
    )


def verify_face_mock() -> MockVerificationResult:
    """开发期人脸 Mock；直接返回 MOCK_PASSED。"""
    if not settings.IDENTITY_MOCK_ENABLED:
        raise ApiError(
            ErrorCode.IDENTITY_VERIFICATION_UNAVAILABLE,
            ERROR_MESSAGES[ErrorCode.IDENTITY_VERIFICATION_UNAVAILABLE],
            status_code=503,
        )
    return MockVerificationResult(
        status=IdentityVerification.Status.MOCK_PASSED,
        provider_request_no=f"mock-face-{uuid.uuid4().hex}",
        result_code="MOCK_PASSED",
    )


def record_mock_verifications(
    user,
    *,
    real_name: str,
    id_card_number: str,
    id_card_front_media_id: str,
    id_card_back_media_id: str,
) -> dict[str, IdentityVerification]:
    """事务内保存实名资料和证件照片引用，并记录实名/人脸 Mock 状态。"""
    real_name_result = verify_real_name_mock(
        real_name=real_name,
        id_card_number=id_card_number,
    )
    face = verify_face_mock()
    now = timezone.now()
    results: dict[str, IdentityVerification] = {}
    with transaction.atomic():
        for verification_type, result in (
            (IdentityVerification.Type.REAL_NAME, real_name_result),
            (IdentityVerification.Type.FACE, face),
        ):
            verification, _ = IdentityVerification.objects.update_or_create(
                user=user,
                verification_type=verification_type,
                defaults={
                    "status": result.status,
                    "provider_request_no": result.provider_request_no,
                    "result_code": result.result_code,
                    "real_name_encrypted": encrypt_text(real_name)
                    if verification_type == IdentityVerification.Type.REAL_NAME
                    else "",
                    "id_card_number_encrypted": encrypt_text(id_card_number)
                    if verification_type == IdentityVerification.Type.REAL_NAME
                    else "",
                    "id_card_hash": hash_sensitive_text(id_card_number)
                    if verification_type == IdentityVerification.Type.REAL_NAME
                    else "",
                    "id_card_front_media_id": id_card_front_media_id
                    if verification_type == IdentityVerification.Type.REAL_NAME
                    else "",
                    "id_card_back_media_id": id_card_back_media_id
                    if verification_type == IdentityVerification.Type.REAL_NAME
                    else "",
                    "submitted_at": now,
                    "verified_at": now,
                },
            )
            results[verification_type] = verification
    return results


def _invalid(field: str, message: str) -> ApiError:
    """构造实名认证参数校验异常。"""
    return ApiError(
        ErrorCode.IDENTITY_VERIFICATION_INVALID,
        message,
        status_code=400,
        details={"field": field, "reason": message},
    )


def _is_valid_id_card(value: str) -> bool:
    """校验中国大陆 18 位身份证校验位。"""
    if len(value) != 18 or not value[:17].isdigit():
        return False
    checksum = sum(
        int(character) * weight
        for character, weight in zip(value[:17], ID_CARD_WEIGHTS, strict=True)
    )
    return value[-1].upper() == ID_CARD_CHECK_CODES[checksum % 11]


def validate_real_name_payload(payload: dict[str, Any]) -> dict[str, str]:
    """校验并规范化普通用户实名认证资料。"""
    details: dict[str, str] = {}
    real_name = str(payload.get("real_name", "")).strip()
    id_card_number = str(payload.get("id_card_number", "")).strip().upper()
    front_media_id = str(payload.get("id_card_front_media_id", "")).strip()
    back_media_id = str(payload.get("id_card_back_media_id", "")).strip()
    if not REAL_NAME_PATTERN.fullmatch(real_name) or not real_name.replace(" ", ""):
        details["real_name"] = "真实姓名格式不正确"
    if not _is_valid_id_card(id_card_number):
        details["id_card_number"] = "身份证号格式不正确"
    if not MEDIA_ID_PATTERN.fullmatch(front_media_id):
        details["id_card_front_media_id"] = "身份证正面照片资源标识不正确"
    if not MEDIA_ID_PATTERN.fullmatch(back_media_id):
        details["id_card_back_media_id"] = "身份证反面照片资源标识不正确"
    if front_media_id and front_media_id == back_media_id:
        details["id_card_back_media_id"] = "身份证正反面照片不能相同"
    if details:
        raise ApiError(
            ErrorCode.IDENTITY_VERIFICATION_INVALID,
            ERROR_MESSAGES[ErrorCode.IDENTITY_VERIFICATION_INVALID],
            status_code=400,
            details=details,
        )
    return {
        "real_name": real_name,
        "id_card_number": id_card_number,
        "id_card_front_media_id": front_media_id,
        "id_card_back_media_id": back_media_id,
    }


def _validate_identity_media(user, payload: dict[str, str]) -> None:
    """校验实名照片由本人上传且用途正确。"""
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


def submit_real_name_verification(
    *,
    user,
    payload: dict[str, Any],
    expected_version: int = 0,
    idempotency_key: str | None = None,
) -> IdentityVerification:
    """提交普通用户实名资料，进入人工审核；不执行人脸认证。"""
    normalized = validate_real_name_payload(payload)
    _validate_identity_media(user, normalized)
    normalized_key = (idempotency_key or "").strip()
    if len(normalized_key) > 128:
        raise _invalid("Idempotency-Key", "幂等键长度不能超过 128 个字符")
    fingerprint = sensitive_fingerprint(normalized)
    try:
        with transaction.atomic():
            verification, created = IdentityVerification.objects.get_or_create(
                user=user,
                verification_type=IdentityVerification.Type.REAL_NAME,
                defaults={
                    "verification_no": uuid.uuid4(),
                    "status": IdentityVerification.Status.PENDING,
                    "real_name_encrypted": encrypt_text(normalized["real_name"]),
                    "id_card_number_encrypted": encrypt_text(normalized["id_card_number"]),
                    "id_card_hash": hash_sensitive_text(normalized["id_card_number"]),
                    "id_card_front_media_id": normalized["id_card_front_media_id"],
                    "id_card_back_media_id": normalized["id_card_back_media_id"],
                    "provider_request_no": f"manual-real-name-{uuid.uuid4().hex}",
                    "result_code": "PENDING_MANUAL_REVIEW",
                    "submitted_at": timezone.now(),
                    "idempotency_key": normalized_key or None,
                    "request_fingerprint": fingerprint,
                },
            )
            if not created:
                if (
                    normalized_key
                    and verification.idempotency_key == normalized_key
                    and verification.request_fingerprint == fingerprint
                ):
                    return verification
                if verification.status == IdentityVerification.Status.PASSED:
                    raise ApiError(
                        ErrorCode.IDENTITY_VERIFICATION_STATE_INVALID,
                        ERROR_MESSAGES[ErrorCode.IDENTITY_VERIFICATION_STATE_INVALID],
                        status_code=409,
                    )
                if verification.version != expected_version:
                    raise ApiError(
                        ErrorCode.IDENTITY_VERIFICATION_VERSION_CONFLICT,
                        ERROR_MESSAGES[ErrorCode.IDENTITY_VERIFICATION_VERSION_CONFLICT],
                        status_code=409,
                    )
                verification.real_name_encrypted = encrypt_text(normalized["real_name"])
                verification.id_card_number_encrypted = encrypt_text(normalized["id_card_number"])
                verification.id_card_hash = hash_sensitive_text(normalized["id_card_number"])
                verification.id_card_front_media_id = normalized["id_card_front_media_id"]
                verification.id_card_back_media_id = normalized["id_card_back_media_id"]
                verification.status = IdentityVerification.Status.PENDING
                verification.reject_reason = ""
                verification.reviewer_id = None
                verification.reviewed_at = None
                verification.provider_request_no = f"manual-real-name-{uuid.uuid4().hex}"
                verification.result_code = "PENDING_MANUAL_REVIEW"
                verification.submitted_at = timezone.now()
                verification.idempotency_key = normalized_key or None
                verification.request_fingerprint = fingerprint
                verification.version += 1
                verification.save()
            mark_media_referenced(
                [
                    normalized["id_card_front_media_id"],
                    normalized["id_card_back_media_id"],
                ]
            )
            return verification
    except ApiError:
        raise


def review_real_name_verification(
    *,
    verification_no: str,
    approve: bool,
    reason: str,
    expected_version: int,
    reviewer,
) -> IdentityVerification:
    """管理员人工审核实名资料，通过或拒绝并记录版本。"""
    normalized_reason = reason.strip()
    if not approve and len(normalized_reason) < 2:
        raise _invalid("reason", "拒绝原因至少需要 2 个字符")
    with transaction.atomic():
        verification = (
            IdentityVerification.objects.select_for_update()
            .filter(
                verification_no=verification_no,
                verification_type=IdentityVerification.Type.REAL_NAME,
            )
            .first()
        )
        if verification is None:
            raise ApiError(
                ErrorCode.IDENTITY_VERIFICATION_NOT_FOUND,
                ERROR_MESSAGES[ErrorCode.IDENTITY_VERIFICATION_NOT_FOUND],
                status_code=404,
            )
        if verification.status != IdentityVerification.Status.PENDING:
            raise ApiError(
                ErrorCode.IDENTITY_VERIFICATION_STATE_INVALID,
                ERROR_MESSAGES[ErrorCode.IDENTITY_VERIFICATION_STATE_INVALID],
                status_code=409,
            )
        if verification.version != expected_version:
            raise ApiError(
                ErrorCode.IDENTITY_VERIFICATION_VERSION_CONFLICT,
                ERROR_MESSAGES[ErrorCode.IDENTITY_VERIFICATION_VERSION_CONFLICT],
                status_code=409,
            )
        verification.status = (
            IdentityVerification.Status.PASSED if approve else IdentityVerification.Status.REJECTED
        )
        verification.reject_reason = "" if approve else normalized_reason
        verification.reviewer_id = reviewer.id
        verification.reviewed_at = timezone.now()
        verification.version += 1
        verification.save()
        return verification


def identity_verification_payload(
    verification: IdentityVerification | None,
    *,
    user,
    request=None,
) -> dict[str, Any]:
    """返回实名认证安全摘要，不返回姓名、身份证号或密文。"""
    if verification is None:
        return {
            "verification_no": None,
            "status": "NOT_SUBMITTED",
            "real_name_status": "NOT_SUBMITTED",
            "id_card_front_media_id": None,
            "id_card_back_media_id": None,
            "id_card_front_media": None,
            "id_card_back_media": None,
            "reject_reason": "",
            "submitted_at": None,
            "reviewed_at": None,
            "version": 0,
            "user_public_id": str(user.public_id),
        }
    front_media = get_media_payloads(
        [verification.id_card_front_media_id] if verification.id_card_front_media_id else [],
        request,
    )
    back_media = get_media_payloads(
        [verification.id_card_back_media_id] if verification.id_card_back_media_id else [],
        request,
    )
    return {
        "verification_no": str(verification.verification_no)
        if verification.verification_no
        else None,
        "status": verification.status,
        "real_name_status": verification.status,
        "id_card_front_media_id": verification.id_card_front_media_id or None,
        "id_card_back_media_id": verification.id_card_back_media_id or None,
        "id_card_front_media": front_media[0] if front_media else None,
        "id_card_back_media": back_media[0] if back_media else None,
        "reject_reason": verification.reject_reason,
        "submitted_at": verification.submitted_at,
        "reviewed_at": verification.reviewed_at,
        "version": verification.version,
        "user_public_id": str(user.public_id),
    }
