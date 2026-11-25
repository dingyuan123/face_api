"""管理后台公司简介和营业执照资料维护业务服务。"""

from __future__ import annotations

import uuid
from typing import Any

from django.db import transaction
from django.http import HttpRequest

from backend.accounts.models import User
from backend.adminops.auth import write_admin_operation
from backend.adminops.models import AdminOperationLog, CompanyProfile
from backend.common.crypto import sensitive_fingerprint
from backend.common.errors import ERROR_MESSAGES, ErrorCode
from backend.common.exceptions import ApiError
from backend.media.models import MediaAsset
from backend.media.services import (
    get_available_media,
    get_media_payloads,
    mark_media_referenced,
    upload_image,
)

SINGLETON_KEY = "DEFAULT"


def _invalid(field: str, message: str) -> ApiError:
    """返回带字段定位信息的公司资料校验错误。"""
    return ApiError(
        ErrorCode.VALIDATION_ERROR,
        message,
        status_code=400,
        details={field: message},
    )


def _normalize_company_name(value: Any) -> str:
    """校验并规范化公司全称。"""
    company_name = str(value or "").strip()
    if not 2 <= len(company_name) <= 120:
        raise _invalid("company_name", "公司全称长度必须为 2 到 120 个字符")
    return company_name


def _normalize_introduction(value: Any) -> str:
    """校验并规范化公司简介正文。"""
    introduction = str(value or "").strip()
    if not 1 <= len(introduction) <= 2000:
        raise _invalid("introduction", "公司简介长度必须为 1 到 2000 个字符")
    return introduction


def _normalize_license_media_id(value: Any, *, operator: User) -> str:
    """校验营业执照媒体属于当前管理员且用途正确。"""
    media_id = str(value or "").strip()
    if not media_id:
        return ""
    try:
        uuid.UUID(media_id)
    except ValueError as exc:
        raise _invalid(
            "business_license_media_id",
            "营业执照媒体标识不正确",
        ) from exc
    get_available_media(
        user=operator,
        purpose=MediaAsset.Purpose.COMPANY_BUSINESS_LICENSE,
        media_ids=[media_id],
    )
    return media_id


def _audit_state(item: CompanyProfile | None) -> dict[str, Any]:
    """返回可写入审计日志的公司资料状态，不包含签名图片地址。"""
    if item is None:
        return {
            "company_name": "",
            "introduction": "",
            "business_license_media_id": "",
            "version": 0,
        }
    return {
        "company_name": item.company_name,
        "introduction": item.introduction,
        "business_license_media_id": item.business_license_media_id,
        "version": item.version,
    }


def company_profile_payload(
    item: CompanyProfile | None,
    request: HttpRequest | None = None,
) -> dict[str, Any]:
    """返回管理后台公司资料和营业执照临时展示地址。"""
    if item is None:
        return {
            **_audit_state(None),
            "business_license_media": None,
            "has_business_license": False,
            "updated_by_public_id": None,
            "created_at": None,
            "updated_at": None,
        }
    license_media = (
        get_media_payloads([item.business_license_media_id], request)
        if item.business_license_media_id
        else []
    )
    updated_by = (
        User.objects.filter(id=item.updated_by).only("public_id").first()
        if item.updated_by
        else None
    )
    return {
        **_audit_state(item),
        "business_license_media": license_media[0] if license_media else None,
        "has_business_license": bool(license_media),
        "updated_by_public_id": str(updated_by.public_id) if updated_by else None,
        "created_at": item.created_at,
        "updated_at": item.updated_at,
    }


def public_company_profile_payload(
    item: CompanyProfile | None,
    request: HttpRequest | None = None,
) -> dict[str, Any]:
    """返回普通用户可见的公司简介和营业执照展示信息。"""
    if item is None:
        return {
            "company_name": "",
            "introduction": "",
            "business_license_media": None,
            "has_business_license": False,
        }
    license_media = (
        get_media_payloads([item.business_license_media_id], request)
        if item.business_license_media_id
        else []
    )
    media = license_media[0] if license_media else None
    return {
        "company_name": item.company_name,
        "introduction": item.introduction,
        "business_license_media": (
            {
                "media_id": media["media_id"],
                "content_type": media["content_type"],
                "width": media["width"],
                "height": media["height"],
                "display_url": media["display_url"],
                "display_url_expires_at": media["display_url_expires_at"],
            }
            if media
            else None
        ),
        "has_business_license": media is not None,
    }


def get_company_profile(request: HttpRequest | None = None) -> dict[str, Any]:
    """读取公司资料；尚未创建时返回 version 为 0 的空表单。"""
    item = CompanyProfile.objects.filter(singleton_key=SINGLETON_KEY).first()
    return company_profile_payload(item, request)


def get_public_company_profile(
    request: HttpRequest | None = None,
) -> dict[str, Any]:
    """读取普通用户可见的公司简介和营业执照。"""
    item = CompanyProfile.objects.filter(singleton_key=SINGLETON_KEY).first()
    return public_company_profile_payload(item, request)


def upload_company_business_license(
    *,
    operator: User,
    data: bytes,
    idempotency_key: str = "",
) -> tuple[MediaAsset, bool]:
    """上传公司营业执照图片并在首次写入时记录管理审计。"""
    result = upload_image(
        user=operator,
        purpose=MediaAsset.Purpose.COMPANY_BUSINESS_LICENSE,
        data=data,
        idempotency_key=idempotency_key or None,
    )
    if not result.reused:
        write_admin_operation(
            operator=operator,
            action="COMPANY_LICENSE_UPLOAD",
            target_type="COMPANY_LICENSE",
            target_id=str(result.asset.public_id),
            after_state={
                "media_id": str(result.asset.public_id),
                "purpose": result.asset.purpose,
                "content_type": result.asset.content_type,
                "byte_size": result.asset.byte_size,
            },
            idempotency_key=idempotency_key,
        )
    return result.asset, result.reused


def update_company_profile(
    *,
    operator: User,
    payload: dict[str, Any],
    request: HttpRequest | None = None,
    idempotency_key: str = "",
) -> dict[str, Any]:
    """创建或更新单份公司资料，并使用版本号防止并发覆盖。"""
    expected_version = int(payload.get("expected_version", -1))
    normalized: dict[str, Any] = {}
    if "company_name" in payload:
        normalized["company_name"] = _normalize_company_name(payload["company_name"])
    if "introduction" in payload:
        normalized["introduction"] = _normalize_introduction(payload["introduction"])
    if "business_license_media_id" in payload:
        normalized["business_license_media_id"] = _normalize_license_media_id(
            payload["business_license_media_id"],
            operator=operator,
        )
    request_fingerprint = sensitive_fingerprint(
        {
            "expected_version": expected_version,
            "payload": normalized,
        }
    )
    if idempotency_key:
        existing_log = (
            AdminOperationLog.objects.filter(
                action__in={
                    "COMPANY_PROFILE_CREATE",
                    "COMPANY_PROFILE_UPDATE",
                },
                target_type="COMPANY_PROFILE",
                target_id=SINGLETON_KEY,
                idempotency_key=idempotency_key,
            )
            .order_by("-created_at", "-id")
            .first()
        )
        if existing_log:
            if existing_log.after_state.get("_request_fingerprint") != request_fingerprint:
                raise ApiError(
                    ErrorCode.ADMIN_IDEMPOTENCY_CONFLICT,
                    ERROR_MESSAGES[ErrorCode.ADMIN_IDEMPOTENCY_CONFLICT],
                    status_code=409,
                )
            return get_company_profile(request)
    with transaction.atomic():
        item = (
            CompanyProfile.objects.select_for_update().filter(singleton_key=SINGLETON_KEY).first()
        )
        if item is None and expected_version != 0:
            raise ApiError(
                ErrorCode.ADMIN_VERSION_CONFLICT,
                ERROR_MESSAGES[ErrorCode.ADMIN_VERSION_CONFLICT],
                status_code=409,
                details={"expected_version": "首次创建公司资料时必须传 0"},
            )
        if item is not None and item.version != expected_version:
            raise ApiError(
                ErrorCode.ADMIN_VERSION_CONFLICT,
                ERROR_MESSAGES[ErrorCode.ADMIN_VERSION_CONFLICT],
                status_code=409,
            )
        if item is not None and not normalized:
            raise _invalid("company_name", "至少需要修改一个公司资料字段")
        if item is None:
            if "company_name" not in normalized or "introduction" not in normalized:
                raise _invalid("company_name", "首次创建必须填写公司全称和公司简介")
            item = CompanyProfile(
                singleton_key=SINGLETON_KEY,
                company_name=normalized["company_name"],
                introduction=normalized["introduction"],
                business_license_media_id=normalized.get(
                    "business_license_media_id",
                    "",
                ),
                updated_by=operator.id,
            )
        else:
            before = _audit_state(item)
            for field, value in normalized.items():
                setattr(item, field, value)
            item.version += 1
            item.updated_by = operator.id
            item.save()
            after = {
                **_audit_state(item),
                "_request_fingerprint": request_fingerprint,
            }
            write_admin_operation(
                operator=operator,
                action="COMPANY_PROFILE_UPDATE",
                target_type="COMPANY_PROFILE",
                target_id=SINGLETON_KEY,
                before_state=before,
                after_state=after,
                idempotency_key=idempotency_key,
            )
            if item.business_license_media_id:
                mark_media_referenced([item.business_license_media_id])
            return company_profile_payload(item, request)
        item.save()
        write_admin_operation(
            operator=operator,
            action="COMPANY_PROFILE_CREATE",
            target_type="COMPANY_PROFILE",
            target_id=SINGLETON_KEY,
            before_state=_audit_state(None),
            after_state={
                **_audit_state(item),
                "_request_fingerprint": request_fingerprint,
            },
            idempotency_key=idempotency_key,
        )
        if item.business_license_media_id:
            mark_media_referenced([item.business_license_media_id])
        return company_profile_payload(item, request)
