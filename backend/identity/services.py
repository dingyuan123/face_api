"""实名和人脸认证适配边界；当前提供开发 Mock 实现。"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from backend.common.errors import ERROR_MESSAGES, ErrorCode
from backend.common.exceptions import ApiError
from backend.identity.models import IdentityVerification


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
) -> dict[str, IdentityVerification]:
    """事务内记录实名和人脸 Mock 状态，同一用户每种认证只保留一条。"""
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
                    "submitted_at": now,
                    "verified_at": now,
                },
            )
            results[verification_type] = verification
    return results
