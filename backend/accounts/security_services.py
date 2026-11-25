"""账号密码设置、找回、手机号更换和会话安全管理服务。"""

from __future__ import annotations

import re
import uuid
from datetime import timedelta
from typing import Any

from django.contrib.auth.hashers import check_password
from django.db import IntegrityError, transaction
from django.utils import timezone

from backend.accounts.models import (
    AccountSecurityEvent,
    AuthToken,
    PhoneChangeRequest,
    User,
    UserAuth,
    VerificationCode,
)
from backend.accounts.services import (
    encrypt_text,
    hash_phone,
    mask_phone,
    normalize_phone,
    send_sms_code,
)
from backend.common.context import current_trace_id
from backend.common.crypto import decrypt_text, sensitive_fingerprint
from backend.common.errors import ERROR_MESSAGES, ErrorCode
from backend.common.exceptions import ApiError

PASSWORD_PATTERN = re.compile(r"^(?=.*[A-Za-z])(?=.*\d).+$")


def _has_password(user: User) -> bool:
    """判断账号是否已设置非空、可用的登录密码。"""
    return bool(user.password) and user.has_usable_password()


def _invalid(field: str, message: str, code: ErrorCode) -> ApiError:
    """返回账号安全参数校验错误。"""
    return ApiError(
        code,
        message,
        status_code=400,
        details={field: message},
    )


def _validate_password(value: Any, *, field: str = "new_password") -> str:
    """校验用户密码长度、字符组成和弱口令。"""
    password = str(value or "")
    if not 8 <= len(password) <= 64 or not PASSWORD_PATTERN.fullmatch(password):
        raise _invalid(
            field,
            "密码必须为 8 到 64 位，并同时包含字母和数字",
            ErrorCode.AUTH_PASSWORD_POLICY,
        )
    if password.lower() in {
        "password",
        "password123",
        "12345678",
        "qwerty123",
        "abc123456",
    }:
        raise _invalid(
            field,
            "新密码过于简单，请更换其他密码",
            ErrorCode.AUTH_PASSWORD_POLICY,
        )
    return password


def _record_event(
    *,
    user: User,
    event_type: str,
    status: str = "SUCCESS",
    result_code: str = "",
    request_id: uuid.UUID | str | None = None,
    old_phone_masked: str = "",
    new_phone_masked: str = "",
    idempotency_key: str = "",
    request_fingerprint: str = "",
) -> AccountSecurityEvent:
    """记录不包含密码、验证码和令牌的账号安全事件。"""
    return AccountSecurityEvent.objects.create(
        user=user,
        event_type=event_type,
        status=status,
        result_code=result_code,
        request_id=uuid.UUID(str(request_id)) if request_id else None,
        old_phone_masked=old_phone_masked,
        new_phone_masked=new_phone_masked,
        idempotency_key=idempotency_key or None,
        request_fingerprint=request_fingerprint,
        trace_id=current_trace_id(),
    )


def _consume_sms_code(
    *,
    user: User,
    phone_hash: str,
    purpose: str,
    code: str,
    request_id: uuid.UUID | str | None = None,
) -> VerificationCode:
    """校验并一次性消费指定用途的短信验证码。"""
    normalized_code = str(code or "").strip()
    if not re.fullmatch(r"\d{6}", normalized_code):
        raise _invalid("code", "验证码必须为 6 位数字", ErrorCode.AUTH_CODE_INVALID)
    queryset = VerificationCode.objects.select_for_update().filter(
        phone_hash=phone_hash,
        purpose=purpose,
    )
    if request_id:
        queryset = queryset.filter(request_id=uuid.UUID(str(request_id)))
    verification = queryset.order_by("-created_at", "-id").first()
    if verification is None:
        raise _invalid("code", "验证码不存在或已失效", ErrorCode.AUTH_CODE_INVALID)
    if verification.consumed_at is not None:
        raise _invalid("code", "验证码已使用", ErrorCode.AUTH_CODE_CONSUMED)
    if verification.expires_at <= timezone.now():
        raise _invalid("code", "验证码已过期", ErrorCode.AUTH_CODE_EXPIRED)
    if verification.attempts >= verification.max_attempts:
        raise ApiError(
            ErrorCode.AUTH_CODE_ATTEMPTS_EXCEEDED,
            ERROR_MESSAGES[ErrorCode.AUTH_CODE_ATTEMPTS_EXCEEDED],
            status_code=423,
        )
    if not check_password(normalized_code, verification.code_hash):
        VerificationCode.objects.filter(pk=verification.pk).update(
            attempts=verification.attempts + 1
        )
        _record_event(
            user=user,
            event_type=f"{purpose}_CODE_FAILED",
            status="FAILED",
            result_code=ErrorCode.AUTH_CODE_INVALID.value,
            request_id=verification.request_id,
        )
        raise _invalid("code", "验证码不正确", ErrorCode.AUTH_CODE_INVALID)
    verification.consumed_at = timezone.now()
    verification.save(update_fields=["consumed_at"])
    return verification


def _revoke_tokens(
    *,
    user: User,
    current_session_id: uuid.UUID | None = None,
    revoke_all: bool = False,
) -> int:
    """撤销用户令牌，可保留当前设备会话。"""
    queryset = AuthToken.objects.filter(user=user, revoked_at__isnull=True)
    if not revoke_all and current_session_id is not None:
        queryset = queryset.exclude(session_id=current_session_id)
    return queryset.update(revoked_at=timezone.now())


def account_security_payload(user: User) -> dict[str, Any]:
    """返回账号密码、登录方式和可执行安全操作摘要。"""
    active_sessions = (
        AuthToken.objects.filter(
            user=user,
            token_type=AuthToken.TokenType.ACCESS,
            revoked_at__isnull=True,
            expires_at__gt=timezone.now(),
        )
        .values_list("session_id", flat=True)
        .distinct()
        .count()
    )
    return {
        "phone_masked": user.phone_masked,
        "has_password": _has_password(user),
        "auth_methods": sorted(
            user.auths.filter(status="ENABLED").values_list("auth_type", flat=True).distinct()
        ),
        "can_change_phone": bool(user.phone_hash or _has_password(user)),
        "can_reset_password": bool(user.phone_hash),
        "active_session_count": active_sessions,
    }


def _sms_payload(result: Any, phone_masked: str) -> dict[str, Any]:
    """返回验证码发送安全摘要。"""
    return {
        "request_id": result.request_id,
        "phone_masked": phone_masked,
        "expires_in": result.expires_in,
        "debug_code": result.debug_code,
    }


def send_password_change_sms(
    *,
    user: User,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    """向当前绑定手机号发送设置或修改密码验证码。"""
    if not user.phone_hash or not user.phone_encrypted:
        raise ApiError(
            ErrorCode.AUTH_PHONE_NOT_BOUND,
            ERROR_MESSAGES[ErrorCode.AUTH_PHONE_NOT_BOUND],
            status_code=409,
        )
    result = send_sms_code(
        phone_value=decrypt_text(user.phone_encrypted),
        idempotency_key=idempotency_key,
        purpose=VerificationCode.Purpose.PASSWORD_CHANGE,
    )
    return _sms_payload(result, user.phone_masked)


def set_or_change_password(
    *,
    user: User,
    new_password: str,
    current_password: str = "",
    code: str = "",
    idempotency_key: str = "",
    current_session_id: uuid.UUID | None = None,
) -> dict[str, Any]:
    """设置首次密码或校验旧密码和短信后修改用户密码。"""
    normalized_password = _validate_password(new_password)
    has_password = _has_password(user)
    if has_password:
        if not str(current_password or "") or not user.check_password(current_password):
            raise ApiError(
                ErrorCode.AUTH_PASSWORD_CURRENT_INVALID,
                ERROR_MESSAGES[ErrorCode.AUTH_PASSWORD_CURRENT_INVALID],
                status_code=400,
            )
        if user.check_password(normalized_password):
            raise _invalid(
                "new_password",
                "新密码不能与当前密码相同",
                ErrorCode.AUTH_PASSWORD_POLICY,
            )
    if not user.phone_hash or not user.phone_encrypted:
        raise ApiError(
            ErrorCode.AUTH_PHONE_NOT_BOUND,
            ERROR_MESSAGES[ErrorCode.AUTH_PHONE_NOT_BOUND],
            status_code=409,
        )
    fingerprint = sensitive_fingerprint(
        {
            "user_id": user.id,
            "operation": "PASSWORD_SET" if not has_password else "PASSWORD_CHANGE",
            "password_proof": user.password,
            "new_password_proof": normalized_password,
        }
    )
    event_type = "PASSWORD_SET" if not has_password else "PASSWORD_CHANGED"
    if idempotency_key:
        existing = AccountSecurityEvent.objects.filter(
            user=user,
            event_type=event_type,
            idempotency_key=idempotency_key,
        ).first()
        if existing:
            if existing.request_fingerprint != fingerprint:
                raise ApiError(
                    ErrorCode.AUTH_IDEMPOTENCY_CONFLICT,
                    ERROR_MESSAGES[ErrorCode.AUTH_IDEMPOTENCY_CONFLICT],
                    status_code=409,
                )
            return {
                "password_set": not has_password,
                "password_changed": has_password,
                "tokens_revoked_count": 0,
                "current_session_preserved": True,
                "reused": True,
            }
    with transaction.atomic():
        locked_user = User.objects.select_for_update().get(pk=user.pk)
        verification = _consume_sms_code(
            user=locked_user,
            phone_hash=locked_user.phone_hash,
            purpose=VerificationCode.Purpose.PASSWORD_CHANGE,
            code=code,
        )
        locked_user.set_password(normalized_password)
        locked_user.save(update_fields=["password", "updated_at"])
        UserAuth.objects.update_or_create(
            auth_type=UserAuth.Type.PASSWORD,
            auth_identifier=f"password:{locked_user.public_id}",
            defaults={
                "user": locked_user,
                "credential_hash": "",
                "status": "ENABLED",
            },
        )
        revoked = _revoke_tokens(
            user=locked_user,
            current_session_id=current_session_id,
        )
        _record_event(
            user=locked_user,
            event_type=event_type,
            request_id=verification.request_id,
            idempotency_key=idempotency_key,
            request_fingerprint=fingerprint,
        )
        return {
            "password_set": not has_password,
            "password_changed": has_password,
            "tokens_revoked_count": revoked,
            "current_session_preserved": current_session_id is not None,
            "reused": False,
        }


def send_password_reset_sms(
    *,
    phone_value: str,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    """向已绑定手机号发送普通用户密码重置验证码。"""
    phone = normalize_phone(phone_value)
    user = User.objects.filter(
        phone_hash=hash_phone(phone),
        status=User.Status.ACTIVE,
    ).first()
    if user is None or not user.phone_hash or not user.phone_encrypted:
        raise ApiError(
            ErrorCode.AUTH_INVALID_PHONE,
            "该手机号未绑定可用账号",
            status_code=404,
        )
    result = send_sms_code(
        phone_value=phone,
        idempotency_key=idempotency_key,
        purpose=VerificationCode.Purpose.PASSWORD_RESET,
    )
    _record_event(
        user=user,
        event_type="PASSWORD_RESET_CODE_SENT",
        request_id=result.request_id,
        idempotency_key=idempotency_key or "",
    )
    return _sms_payload(result, user.phone_masked)


def reset_password(
    *,
    phone_value: str,
    code: str,
    new_password: str,
    idempotency_key: str = "",
) -> dict[str, Any]:
    """使用手机号验证码重置密码并撤销全部设备令牌。"""
    phone = normalize_phone(phone_value)
    normalized_password = _validate_password(new_password)
    phone_hash = hash_phone(phone)
    fingerprint = sensitive_fingerprint(
        {
            "phone_hash": phone_hash,
            "new_password_proof": normalized_password,
        }
    )
    if idempotency_key:
        existing = AccountSecurityEvent.objects.filter(
            event_type="PASSWORD_RESET",
            idempotency_key=idempotency_key,
        ).first()
        if existing:
            if existing.request_fingerprint != fingerprint:
                raise ApiError(
                    ErrorCode.AUTH_IDEMPOTENCY_CONFLICT,
                    ERROR_MESSAGES[ErrorCode.AUTH_IDEMPOTENCY_CONFLICT],
                    status_code=409,
                )
            return {
                "password_reset": True,
                "phone_masked": existing.old_phone_masked,
                "tokens_revoked_count": 0,
                "reused": True,
            }
    with transaction.atomic():
        user = (
            User.objects.select_for_update()
            .filter(phone_hash=phone_hash, status=User.Status.ACTIVE)
            .first()
        )
        if user is None:
            raise ApiError(
                ErrorCode.AUTH_INVALID_PHONE,
                "该手机号未绑定可用账号",
                status_code=404,
            )
        verification = _consume_sms_code(
            user=user,
            phone_hash=phone_hash,
            purpose=VerificationCode.Purpose.PASSWORD_RESET,
            code=code,
        )
        user.set_password(normalized_password)
        user.save(update_fields=["password", "updated_at"])
        UserAuth.objects.update_or_create(
            auth_type=UserAuth.Type.PASSWORD,
            auth_identifier=f"password:{user.public_id}",
            defaults={
                "user": user,
                "credential_hash": "",
                "status": "ENABLED",
            },
        )
        revoked = _revoke_tokens(user=user, revoke_all=True)
        _record_event(
            user=user,
            event_type="PASSWORD_RESET",
            request_id=verification.request_id,
            idempotency_key=idempotency_key,
            request_fingerprint=fingerprint,
        )
        return {
            "password_reset": True,
            "phone_masked": user.phone_masked,
            "tokens_revoked_count": revoked,
            "reused": False,
        }


def _phone_change_payload(request: PhoneChangeRequest) -> dict[str, Any]:
    """返回手机号更换请求安全摘要。"""
    return {
        "request_no": str(request.request_no),
        "old_phone_masked": request.old_phone_masked,
        "new_phone_masked": request.new_phone_masked,
        "verification_mode": request.verification_mode,
        "status": request.status,
        "expires_in": 0
        if request.status == PhoneChangeRequest.Status.CONFIRMED
        else max(
            0,
            int((request.expires_at - timezone.now()).total_seconds()),
        ),
    }


def request_phone_change(
    *,
    user: User,
    new_phone_value: str,
    current_password: str = "",
    idempotency_key: str = "",
) -> dict[str, Any]:
    """创建双验证码手机号更换请求并分别发送新旧手机号验证码。"""
    new_phone = normalize_phone(new_phone_value)
    new_phone_hash = hash_phone(new_phone)
    if user.phone_hash == new_phone_hash:
        raise _invalid(
            "new_phone",
            "新手机号不能与当前绑定手机号相同",
            ErrorCode.AUTH_PHONE_CHANGE_INVALID,
        )
    if (
        User.objects.filter(phone_hash=new_phone_hash).exclude(pk=user.pk).exists()
        or UserAuth.objects.filter(
            auth_type=UserAuth.Type.PHONE,
            auth_identifier=new_phone_hash,
        )
        .exclude(user=user)
        .exists()
    ):
        raise ApiError(
            ErrorCode.AUTH_PHONE_ALREADY_BOUND,
            ERROR_MESSAGES[ErrorCode.AUTH_PHONE_ALREADY_BOUND],
            status_code=409,
        )
    if not user.phone_hash:
        if not _has_password(user) or not check_password(
            str(current_password or ""),
            user.password,
        ):
            raise ApiError(
                ErrorCode.AUTH_PASSWORD_CURRENT_INVALID,
                ERROR_MESSAGES[ErrorCode.AUTH_PASSWORD_CURRENT_INVALID],
                status_code=400,
            )
    fingerprint = sensitive_fingerprint(
        {
            "user_id": user.id,
            "old_phone_hash": user.phone_hash or "",
            "new_phone_hash": new_phone_hash,
            "password_proof": user.password if not user.phone_hash else "",
        }
    )
    if idempotency_key:
        existing = PhoneChangeRequest.objects.filter(
            user=user,
            idempotency_key=idempotency_key,
        ).first()
        if existing:
            if existing.request_fingerprint != fingerprint:
                raise ApiError(
                    ErrorCode.AUTH_IDEMPOTENCY_CONFLICT,
                    ERROR_MESSAGES[ErrorCode.AUTH_IDEMPOTENCY_CONFLICT],
                    status_code=409,
                )
            return _phone_change_payload(existing)
    old_result = None
    if user.phone_hash and user.phone_encrypted:
        old_result = send_sms_code(
            phone_value=decrypt_text(user.phone_encrypted),
            purpose=VerificationCode.Purpose.PHONE_CHANGE_OLD,
        )
    new_result = send_sms_code(
        phone_value=new_phone,
        purpose=VerificationCode.Purpose.PHONE_CHANGE_NEW,
    )
    try:
        request = PhoneChangeRequest.objects.create(
            user=user,
            new_phone_hash=new_phone_hash,
            new_phone_masked=mask_phone(new_phone),
            new_phone_encrypted=encrypt_text(new_phone),
            old_phone_masked=user.phone_masked,
            verification_mode="DUAL_SMS" if old_result else "PASSWORD_NEW_SMS",
            old_verification_request_id=old_result.request_id if old_result else None,
            new_verification_request_id=new_result.request_id,
            expires_at=timezone.now() + timedelta(seconds=new_result.expires_in),
            idempotency_key=idempotency_key,
            request_fingerprint=fingerprint,
        )
    except IntegrityError as exc:
        raise ApiError(
            ErrorCode.AUTH_PHONE_CHANGE_CONFLICT,
            "已有待确认的手机号更换请求",
            status_code=409,
        ) from exc
    _record_event(
        user=user,
        event_type="PHONE_CHANGE_REQUESTED",
        request_id=request.request_no,
        new_phone_masked=request.new_phone_masked,
        idempotency_key=idempotency_key,
        request_fingerprint=fingerprint,
    )
    return {
        **_phone_change_payload(request),
        "verification_mode": request.verification_mode,
        "old_debug_code": old_result.debug_code if old_result else None,
        "new_debug_code": new_result.debug_code,
    }


def confirm_phone_change(
    *,
    user: User,
    request_no: str,
    old_code: str,
    new_code: str,
    current_session_id: uuid.UUID | None = None,
) -> dict[str, Any]:
    """验证新旧手机号验证码并原子完成手机号换绑。"""
    fingerprint = sensitive_fingerprint(
        {
            "user_id": user.id,
            "request_no": request_no,
            "old_code": old_code,
            "new_code": new_code,
        }
    )
    try:
        request_uuid = uuid.UUID(str(request_no))
    except ValueError as exc:
        raise _invalid(
            "request_no",
            "手机号更换请求标识不正确",
            ErrorCode.AUTH_PHONE_CHANGE_INVALID,
        ) from exc
    with transaction.atomic():
        request = (
            PhoneChangeRequest.objects.select_for_update()
            .filter(user=user, request_no=request_uuid)
            .first()
        )
        if request is None:
            raise ApiError(
                ErrorCode.AUTH_PHONE_CHANGE_INVALID,
                ERROR_MESSAGES[ErrorCode.AUTH_PHONE_CHANGE_INVALID],
                status_code=404,
            )
        if request.status == PhoneChangeRequest.Status.CONFIRMED:
            return {
                **_phone_change_payload(request),
                "already_changed": True,
                "tokens_revoked_count": 0,
                "current_session_preserved": True,
            }
        if (
            request.status != PhoneChangeRequest.Status.PENDING
            or request.expires_at <= timezone.now()
        ):
            request.status = PhoneChangeRequest.Status.EXPIRED
            request.save(update_fields=["status"])
            raise ApiError(
                ErrorCode.AUTH_PHONE_CHANGE_CONFLICT,
                ERROR_MESSAGES[ErrorCode.AUTH_PHONE_CHANGE_CONFLICT],
                status_code=409,
            )
        if request.old_verification_request_id:
            _consume_sms_code(
                user=user,
                phone_hash=user.phone_hash,
                purpose=VerificationCode.Purpose.PHONE_CHANGE_OLD,
                code=old_code,
                request_id=request.old_verification_request_id,
            )
        _consume_sms_code(
            user=user,
            phone_hash=request.new_phone_hash,
            purpose=VerificationCode.Purpose.PHONE_CHANGE_NEW,
            code=new_code,
            request_id=request.new_verification_request_id,
        )
        if User.objects.filter(phone_hash=request.new_phone_hash).exclude(pk=user.pk).exists():
            raise ApiError(
                ErrorCode.AUTH_PHONE_ALREADY_BOUND,
                ERROR_MESSAGES[ErrorCode.AUTH_PHONE_ALREADY_BOUND],
                status_code=409,
            )
        old_phone_masked = request.old_phone_masked
        UserAuth.objects.filter(
            user=user,
            auth_type=UserAuth.Type.PHONE,
        ).delete()
        UserAuth.objects.update_or_create(
            auth_type=UserAuth.Type.PHONE,
            auth_identifier=request.new_phone_hash,
            defaults={
                "user": user,
                "credential_hash": "",
                "status": "ENABLED",
            },
        )
        user.phone_hash = request.new_phone_hash
        user.phone_masked = request.new_phone_masked
        user.phone_encrypted = request.new_phone_encrypted
        user.version += 1
        user.save(
            update_fields=[
                "phone_hash",
                "phone_masked",
                "phone_encrypted",
                "version",
                "updated_at",
            ]
        )
        revoked = _revoke_tokens(
            user=user,
            current_session_id=current_session_id,
        )
        request.status = PhoneChangeRequest.Status.CONFIRMED
        request.new_phone_encrypted = ""
        request.confirmed_at = timezone.now()
        request.save(
            update_fields=[
                "status",
                "new_phone_encrypted",
                "confirmed_at",
            ]
        )
        _record_event(
            user=user,
            event_type="PHONE_CHANGED",
            request_id=request.request_no,
            old_phone_masked=old_phone_masked,
            new_phone_masked=request.new_phone_masked,
            request_fingerprint=fingerprint,
        )
        return {
            **_phone_change_payload(request),
            "already_changed": False,
            "tokens_revoked_count": revoked,
            "current_session_preserved": current_session_id is not None,
        }
