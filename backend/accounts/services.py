"""账号认证、令牌生命周期、首次身份选择的业务服务。"""

from __future__ import annotations

import hashlib
import hmac
import json
import re
import uuid
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from django.conf import settings
from django.contrib.auth.hashers import check_password, make_password
from django.db import transaction
from django.db.models import F
from django.utils import timezone

from backend.accounts.models import (
    AuthToken,
    LoginRequest,
    User,
    UserAuth,
    VerificationCode,
    VerificationSendGuard,
)
from backend.common.crypto import encrypt_text
from backend.common.errors import ERROR_MESSAGES, ErrorCode
from backend.common.exceptions import ApiError
from backend.integrations.oauth.contracts import OAuthIdentity
from backend.referrals.services import bind_new_user_referral

PHONE_PATTERN = re.compile(r"^1[3-9]\d{9}$")


@dataclass(frozen=True)
class SmsCodeResult:
    """验证码发送结果；开发模式可包含脱敏调试验证码。"""

    request_id: str
    expires_in: int
    debug_code: str | None
    reused: bool


@dataclass(frozen=True)
class LoginResult:
    """登录或令牌刷新结果，包含令牌、有效期和账号引导状态。"""

    access_token: str
    refresh_token: str
    expires_in: int
    refresh_expires_in: int
    user_public_id: str
    is_new_user: bool
    requires_identity_selection: bool
    requires_phone_binding: bool = False


@dataclass(frozen=True)
class PhoneBindingResult:
    """手机号绑定或安全合并结果，合并后必须使用返回的新会话令牌。"""

    login: LoginResult
    already_bound: bool
    merged: bool


def normalize_phone(value: str) -> str:
    """校验并规范化中国大陆手机号格式。"""
    phone = value.strip().replace(" ", "")
    if not PHONE_PATTERN.fullmatch(phone):
        raise ApiError(
            ErrorCode.AUTH_INVALID_PHONE,
            ERROR_MESSAGES[ErrorCode.AUTH_INVALID_PHONE],
            status_code=400,
        )
    return phone


def hash_phone(phone: str) -> str:
    """使用独立密钥计算手机号 HMAC，避免保存明文手机号。"""
    key = settings.PHONE_HASH_KEY.encode("utf-8")
    return hmac.new(key, phone.encode("utf-8"), hashlib.sha256).hexdigest()


def hash_oauth_identifier(provider: str, identifier: str) -> str:
    """计算第三方账号标识 HMAC，数据库不保存 Apple sub 或微信 openid 明文。"""
    key = settings.OAUTH_SUBJECT_HASH_KEY.encode("utf-8")
    value = f"{provider}:{identifier}".encode()
    return hmac.new(key, value, hashlib.sha256).hexdigest()


def mask_phone(phone: str) -> str:
    """生成仅保留前三位和后四位的脱敏手机号。"""
    return f"{phone[:3]}****{phone[-4:]}"


def _fingerprint(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _debug_code(request_id: uuid.UUID) -> str:
    key = settings.SMS_MOCK_SIGNING_KEY.encode("utf-8")
    digest = hmac.new(key, request_id.bytes, hashlib.sha256).digest()
    return f"{int.from_bytes(digest[:8], 'big') % 1_000_000:06d}"


def _token_raw(token_type: str, token_id: uuid.UUID) -> str:
    key = settings.AUTH_TOKEN_SIGNING_KEY.encode("utf-8")
    digest = hmac.new(key, f"{token_type}:{token_id}".encode(), hashlib.sha256).hexdigest()
    return f"{token_id}.{digest[:40]}"


def hash_token(raw_token: str) -> str:
    """计算不透明令牌哈希；数据库只保存该摘要。"""
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def _password_request_proof(password: str) -> str:
    """使用独立密钥生成密码请求证明，幂等记录不保存明文或可直接比对的密码摘要。"""
    key = settings.AUTH_TOKEN_SIGNING_KEY.encode("utf-8")
    return hmac.new(key, password.encode("utf-8"), hashlib.sha256).hexdigest()


def _validate_idempotency_key(value: str | None) -> str | None:
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


def send_sms_code(*, phone_value: str, idempotency_key: str | None = None) -> SmsCodeResult:
    """发送登录验证码，并通过幂等键和频率锁处理重复请求。"""
    phone = normalize_phone(phone_value)
    key = _validate_idempotency_key(idempotency_key)
    phone_hash = hash_phone(phone)
    fingerprint = _fingerprint({"phone": phone_hash, "purpose": VerificationCode.Purpose.LOGIN})

    if not settings.SMS_MOCK_ENABLED:
        raise ApiError(
            ErrorCode.AUTH_SMS_UNAVAILABLE,
            ERROR_MESSAGES[ErrorCode.AUTH_SMS_UNAVAILABLE],
            status_code=503,
        )

    with transaction.atomic():
        if key:
            existing = VerificationCode.objects.filter(idempotency_key=key).first()
            if existing:
                if existing.request_fingerprint != fingerprint:
                    raise ApiError(
                        ErrorCode.AUTH_IDEMPOTENCY_CONFLICT,
                        ERROR_MESSAGES[ErrorCode.AUTH_IDEMPOTENCY_CONFLICT],
                        status_code=409,
                    )
                return _sms_result(existing, reused=True)

        now = timezone.now()
        guard, _ = VerificationSendGuard.objects.select_for_update().get_or_create(
            phone_hash=phone_hash,
            defaults={"next_allowed_at": now},
        )
        if guard.next_allowed_at > now:
            raise ApiError(
                ErrorCode.AUTH_CODE_RESEND_TOO_EARLY,
                ERROR_MESSAGES[ErrorCode.AUTH_CODE_RESEND_TOO_EARLY],
                status_code=429,
            )

        request_id = uuid.uuid4()
        debug_code = _debug_code(request_id)
        code = VerificationCode.objects.create(
            request_id=request_id,
            phone_hash=phone_hash,
            phone_masked=mask_phone(phone),
            code_hash=make_password(debug_code),
            expires_at=now + timedelta(seconds=settings.SMS_CODE_TTL_SECONDS),
            max_attempts=settings.SMS_CODE_MAX_ATTEMPTS,
            idempotency_key=key,
            request_fingerprint=fingerprint,
        )
        guard.next_allowed_at = now + timedelta(seconds=settings.SMS_CODE_RESEND_SECONDS)
        guard.save(update_fields=["next_allowed_at", "updated_at"])
        return _sms_result(code, reused=False)


def _sms_result(code: VerificationCode, *, reused: bool) -> SmsCodeResult:
    expires_in = max(0, int((code.expires_at - timezone.now()).total_seconds()))
    debug_code = _debug_code(code.request_id) if settings.SMS_MOCK_ENABLED else None
    return SmsCodeResult(
        request_id=str(code.request_id),
        expires_in=expires_in,
        debug_code=debug_code,
        reused=reused,
    )


def login_with_code(
    *,
    phone_value: str,
    code_value: str,
    idempotency_key: str | None = None,
    referral_context: dict[str, Any] | None = None,
    request: Any = None,
) -> LoginResult:
    """校验一次性验证码并登录或自动注册用户。"""
    phone = normalize_phone(phone_value)
    code_text = str(code_value).strip()
    if not re.fullmatch(r"\d{6}", code_text):
        raise ApiError(
            ErrorCode.AUTH_CODE_INVALID,
            ERROR_MESSAGES[ErrorCode.AUTH_CODE_INVALID],
            status_code=400,
        )

    key = _validate_idempotency_key(idempotency_key)
    effective_key = key or f"auto:{uuid.uuid4()}"
    phone_hash = hash_phone(phone)
    fingerprint = _fingerprint(
        {
            "phone": phone_hash,
            "code": code_text,
            "purpose": VerificationCode.Purpose.LOGIN,
            "referral_context": referral_context or {},
        }
    )

    verification_to_count: VerificationCode | None = None
    try:
        with transaction.atomic():
            login_request, _ = LoginRequest.objects.select_for_update().get_or_create(
                idempotency_key=effective_key,
                defaults={
                    "request_fingerprint": fingerprint,
                    "phone_hash": phone_hash,
                    "phone_masked": mask_phone(phone),
                },
            )
            if login_request.request_fingerprint != fingerprint:
                raise ApiError(
                    ErrorCode.AUTH_IDEMPOTENCY_CONFLICT,
                    ERROR_MESSAGES[ErrorCode.AUTH_IDEMPOTENCY_CONFLICT],
                    status_code=409,
                )
            if login_request.completed_at:
                return _login_result_from_request(login_request)

            verification = (
                VerificationCode.objects.select_for_update()
                .filter(
                    phone_hash=phone_hash,
                    purpose=VerificationCode.Purpose.LOGIN,
                )
                .order_by("-created_at")
                .first()
            )
            if verification is None:
                raise ApiError(
                    ErrorCode.AUTH_CODE_INVALID,
                    ERROR_MESSAGES[ErrorCode.AUTH_CODE_INVALID],
                    status_code=400,
                )
            if verification.consumed_at is not None:
                raise ApiError(
                    ErrorCode.AUTH_CODE_CONSUMED,
                    ERROR_MESSAGES[ErrorCode.AUTH_CODE_CONSUMED],
                    status_code=409,
                )
            if verification.expires_at <= timezone.now():
                raise ApiError(
                    ErrorCode.AUTH_CODE_EXPIRED,
                    ERROR_MESSAGES[ErrorCode.AUTH_CODE_EXPIRED],
                    status_code=400,
                )
            if verification.attempts >= verification.max_attempts:
                raise ApiError(
                    ErrorCode.AUTH_CODE_ATTEMPTS_EXCEEDED,
                    ERROR_MESSAGES[ErrorCode.AUTH_CODE_ATTEMPTS_EXCEEDED],
                    status_code=423,
                )
            if not check_password(code_text, verification.code_hash):
                verification_to_count = verification
                raise ApiError(
                    ErrorCode.AUTH_CODE_INVALID,
                    ERROR_MESSAGES[ErrorCode.AUTH_CODE_INVALID],
                    status_code=400,
                )

            verification.consumed_at = timezone.now()
            verification.save(update_fields=["consumed_at"])

            auth = (
                UserAuth.objects.select_for_update()
                .filter(auth_type=UserAuth.Type.PHONE, auth_identifier=phone_hash)
                .select_related("user")
                .first()
            )
            is_new_user = auth is None
            if auth is not None:
                user = auth.user
            else:
                user, _ = User.objects.get_or_create(
                    phone_hash=phone_hash,
                    defaults={
                        "phone_masked": mask_phone(phone),
                        "phone_encrypted": encrypt_text(phone),
                    },
                )
                UserAuth.objects.get_or_create(
                    auth_type=UserAuth.Type.PHONE,
                    auth_identifier=phone_hash,
                    defaults={"user": user},
                )
            if user.status != User.Status.ACTIVE:
                raise ApiError(
                    ErrorCode.AUTH_ACCOUNT_NOT_ALLOWED,
                    "账号状态不允许登录",
                    status_code=403,
                )
            if is_new_user:
                bind_new_user_referral(
                    user=user,
                    context=referral_context,
                    registration_source="PHONE",
                    is_new_user=True,
                    request=request,
                )
            user.phone_masked = mask_phone(phone)
            user.phone_encrypted = encrypt_text(phone)
            user.last_login_at = timezone.now()
            user.save(
                update_fields=[
                    "phone_masked",
                    "phone_encrypted",
                    "last_login_at",
                    "updated_at",
                ]
            )
            login_request.user = user
            login_request.is_new_user = is_new_user
            login_request.completed_at = timezone.now()
            login_request.save(update_fields=["user", "is_new_user", "completed_at"])
            return _create_login_result(user, login_request, is_new_user)
    except ApiError:
        if verification_to_count is not None:
            VerificationCode.objects.filter(pk=verification_to_count.pk).update(
                attempts=F("attempts") + 1
            )
        raise


def login_with_password(
    *,
    phone_value: str,
    password_value: str,
    idempotency_key: str | None = None,
) -> LoginResult:
    """开发环境使用已有账号密码签发标准令牌；生产环境强制禁用。"""
    if not settings.DEV_PASSWORD_LOGIN_ENABLED:
        raise ApiError(
            ErrorCode.NOT_FOUND,
            ERROR_MESSAGES[ErrorCode.NOT_FOUND],
            status_code=404,
        )

    phone = normalize_phone(phone_value)
    password = str(password_value)
    phone_hash = hash_phone(phone)
    key = _validate_idempotency_key(idempotency_key)
    effective_key = key or f"auto:{uuid.uuid4()}"
    fingerprint = _fingerprint(
        {
            "phone": phone_hash,
            "password_proof": _password_request_proof(password),
            "purpose": "DEV_PASSWORD_LOGIN",
        }
    )
    with transaction.atomic():
        login_request = (
            LoginRequest.objects.select_for_update(of=("self",))
            .select_related("user")
            .filter(idempotency_key=effective_key)
            .first()
        )
        if login_request is not None and login_request.request_fingerprint != fingerprint:
            raise ApiError(
                ErrorCode.AUTH_IDEMPOTENCY_CONFLICT,
                ERROR_MESSAGES[ErrorCode.AUTH_IDEMPOTENCY_CONFLICT],
                status_code=409,
            )
        if login_request is not None and login_request.completed_at:
            if login_request.user is None or login_request.user.status != User.Status.ACTIVE:
                raise ApiError(
                    ErrorCode.AUTH_ACCOUNT_NOT_ALLOWED,
                    "账号状态不允许登录",
                    status_code=403,
                )
            return _login_result_from_request(login_request)

        user = User.objects.filter(phone_hash=phone_hash).first()
        if user is None or not user.has_usable_password() or not user.check_password(password):
            raise ApiError(
                ErrorCode.AUTH_INVALID_CREDENTIALS,
                ERROR_MESSAGES[ErrorCode.AUTH_INVALID_CREDENTIALS],
                status_code=401,
            )
        if user.status != User.Status.ACTIVE:
            raise ApiError(
                ErrorCode.AUTH_ACCOUNT_NOT_ALLOWED,
                "账号状态不允许登录",
                status_code=403,
            )

        if login_request is None:
            login_request = LoginRequest.objects.create(
                idempotency_key=effective_key,
                request_fingerprint=fingerprint,
                phone_hash=phone_hash,
                phone_masked=mask_phone(phone),
            )
        user.last_login_at = timezone.now()
        user.save(update_fields=["last_login_at", "updated_at"])
        login_request.user = user
        login_request.is_new_user = False
        login_request.completed_at = timezone.now()
        login_request.save(update_fields=["user", "is_new_user", "completed_at"])
        return _create_login_result(user, login_request, False)


def login_with_oauth(
    *,
    identity: OAuthIdentity,
    idempotency_key: str | None = None,
    referral_context: dict[str, Any] | None = None,
) -> LoginResult:
    """使用已验证的 Apple 或微信身份登录，不存在时创建未绑定手机号用户。"""
    provider = identity.provider.upper()
    if provider not in {UserAuth.Type.APPLE, UserAuth.Type.WECHAT}:
        raise ApiError(
            ErrorCode.AUTH_OAUTH_INVALID,
            ERROR_MESSAGES[ErrorCode.AUTH_OAUTH_INVALID],
            status_code=400,
        )
    identifiers = _oauth_auth_identifiers(identity)
    if not identifiers:
        raise ApiError(
            ErrorCode.AUTH_OAUTH_INVALID,
            ERROR_MESSAGES[ErrorCode.AUTH_OAUTH_INVALID],
            status_code=400,
        )
    key = _validate_idempotency_key(idempotency_key)
    effective_key = key or f"auto:{uuid.uuid4()}"
    fingerprint = _fingerprint(
        {
            "provider": provider,
            "identifiers": identifiers,
            "purpose": "OAUTH_LOGIN",
            "referral_context": referral_context or {},
        }
    )
    with transaction.atomic():
        login_request, _ = LoginRequest.objects.select_for_update().get_or_create(
            idempotency_key=effective_key,
            defaults={
                "request_fingerprint": fingerprint,
                "phone_hash": None,
                "phone_masked": "",
            },
        )
        if login_request.request_fingerprint != fingerprint:
            raise ApiError(
                ErrorCode.AUTH_IDEMPOTENCY_CONFLICT,
                ERROR_MESSAGES[ErrorCode.AUTH_IDEMPOTENCY_CONFLICT],
                status_code=409,
            )
        if login_request.completed_at:
            return _login_result_from_request(login_request)

        auth = (
            UserAuth.objects.select_for_update()
            .filter(auth_type=provider, auth_identifier__in=identifiers)
            .select_related("user")
            .first()
        )
        is_new_user = auth is None
        if auth is None:
            user = User.objects.create(phone_hash=None, phone_masked="")
            for auth_identifier in identifiers:
                UserAuth.objects.create(
                    user=user,
                    auth_type=provider,
                    auth_identifier=auth_identifier,
                )
        else:
            user = auth.user
            existing_identifiers = set(
                UserAuth.objects.filter(user=user, auth_type=provider).values_list(
                    "auth_identifier", flat=True
                )
            )
            for auth_identifier in identifiers:
                if auth_identifier not in existing_identifiers:
                    UserAuth.objects.get_or_create(
                        auth_type=provider,
                        auth_identifier=auth_identifier,
                        defaults={"user": user},
                    )
        if user.status != User.Status.ACTIVE:
            raise ApiError(
                ErrorCode.AUTH_ACCOUNT_NOT_ALLOWED,
                ERROR_MESSAGES[ErrorCode.AUTH_ACCOUNT_NOT_ALLOWED],
                status_code=403,
            )
        user.last_login_at = timezone.now()
        user.save(update_fields=["last_login_at", "updated_at"])
        login_request.user = user
        login_request.is_new_user = is_new_user
        login_request.completed_at = timezone.now()
        login_request.save(update_fields=["user", "is_new_user", "completed_at"])
        return _create_login_result(user, login_request, is_new_user)


def bind_phone_to_account(
    *,
    user: User,
    phone_value: str,
    code_value: str,
    idempotency_key: str | None = None,
    referral_context: dict[str, Any] | None = None,
    request: Any = None,
) -> PhoneBindingResult:
    """验证手机号并将第三方账号绑定到新手机号或安全合并到空闲手机号账号。"""
    phone = normalize_phone(phone_value)
    phone_hash = hash_phone(phone)
    code_text = str(code_value).strip()
    if not re.fullmatch(r"\d{6}", code_text):
        raise ApiError(
            ErrorCode.AUTH_CODE_INVALID,
            ERROR_MESSAGES[ErrorCode.AUTH_CODE_INVALID],
            status_code=400,
        )
    key = _validate_idempotency_key(idempotency_key)
    effective_key = key or f"auto:{uuid.uuid4()}"
    was_unbound = user.phone_hash is None
    fingerprint = _fingerprint(
        {
            "user_public_id": str(user.public_id),
            "phone_hash": phone_hash,
            "code": code_text,
            "purpose": "PHONE_BINDING",
            "referral_context": referral_context or {},
        }
    )
    verification_to_count: VerificationCode | None = None
    try:
        with transaction.atomic():
            login_request, _ = LoginRequest.objects.select_for_update().get_or_create(
                idempotency_key=effective_key,
                defaults={
                    "request_fingerprint": fingerprint,
                    "phone_hash": phone_hash,
                    "phone_masked": mask_phone(phone),
                },
            )
            if login_request.request_fingerprint != fingerprint:
                raise ApiError(
                    ErrorCode.AUTH_IDEMPOTENCY_CONFLICT,
                    ERROR_MESSAGES[ErrorCode.AUTH_IDEMPOTENCY_CONFLICT],
                    status_code=409,
                )
            if login_request.completed_at:
                return PhoneBindingResult(
                    login=_login_result_from_request(login_request),
                    already_bound=True,
                    merged=False,
                )
            if user.phone_hash == phone_hash:
                _save_bound_phone(user, phone)
                login_request.user = user
                login_request.completed_at = timezone.now()
                login_request.save(update_fields=["user", "completed_at"])
                return PhoneBindingResult(
                    login=_create_login_result(user, login_request, False),
                    already_bound=True,
                    merged=False,
                )
            if user.phone_hash is not None:
                raise ApiError(
                    ErrorCode.AUTH_PHONE_ALREADY_BOUND,
                    ERROR_MESSAGES[ErrorCode.AUTH_PHONE_ALREADY_BOUND],
                    status_code=409,
                )

            verification = (
                VerificationCode.objects.select_for_update()
                .filter(phone_hash=phone_hash, purpose=VerificationCode.Purpose.LOGIN)
                .order_by("-created_at")
                .first()
            )
            if verification is None:
                raise ApiError(
                    ErrorCode.AUTH_CODE_INVALID,
                    ERROR_MESSAGES[ErrorCode.AUTH_CODE_INVALID],
                    status_code=400,
                )
            if verification.consumed_at is not None:
                raise ApiError(
                    ErrorCode.AUTH_CODE_CONSUMED,
                    ERROR_MESSAGES[ErrorCode.AUTH_CODE_CONSUMED],
                    status_code=409,
                )
            if verification.expires_at <= timezone.now():
                raise ApiError(
                    ErrorCode.AUTH_CODE_EXPIRED,
                    ERROR_MESSAGES[ErrorCode.AUTH_CODE_EXPIRED],
                    status_code=400,
                )
            if verification.attempts >= verification.max_attempts:
                raise ApiError(
                    ErrorCode.AUTH_CODE_ATTEMPTS_EXCEEDED,
                    ERROR_MESSAGES[ErrorCode.AUTH_CODE_ATTEMPTS_EXCEEDED],
                    status_code=423,
                )
            if not check_password(code_text, verification.code_hash):
                verification_to_count = verification
                raise ApiError(
                    ErrorCode.AUTH_CODE_INVALID,
                    ERROR_MESSAGES[ErrorCode.AUTH_CODE_INVALID],
                    status_code=400,
                )
            verification.consumed_at = timezone.now()
            verification.save(update_fields=["consumed_at"])

            phone_auth = (
                UserAuth.objects.select_for_update()
                .filter(auth_type=UserAuth.Type.PHONE, auth_identifier=phone_hash)
                .select_related("user")
                .first()
            )
            if phone_auth is None:
                _save_bound_phone(user, phone)
                UserAuth.objects.get_or_create(
                    auth_type=UserAuth.Type.PHONE,
                    auth_identifier=phone_hash,
                    defaults={"user": user},
                )
                target_user = user
                merged = False
                if was_unbound:
                    bind_new_user_referral(
                        user=target_user,
                        context=referral_context,
                        registration_source="WECHAT"
                        if any(
                            auth.auth_type == UserAuth.Type.WECHAT
                            for auth in UserAuth.objects.filter(user=target_user)
                        )
                        else "APPLE",
                        is_new_user=True,
                        request=request,
                    )
            else:
                target_user = phone_auth.user
                if target_user.status != User.Status.ACTIVE:
                    raise ApiError(
                        ErrorCode.AUTH_ACCOUNT_NOT_ALLOWED,
                        ERROR_MESSAGES[ErrorCode.AUTH_ACCOUNT_NOT_ALLOWED],
                        status_code=403,
                    )
                if _has_external_auth(target_user):
                    raise ApiError(
                        ErrorCode.AUTH_ACCOUNT_ALREADY_BOUND,
                        ERROR_MESSAGES[ErrorCode.AUTH_ACCOUNT_ALREADY_BOUND],
                        status_code=409,
                    )
                if _has_business_data(user):
                    raise ApiError(
                        ErrorCode.AUTH_ACCOUNT_MERGE_CONFLICT,
                        ERROR_MESSAGES[ErrorCode.AUTH_ACCOUNT_MERGE_CONFLICT],
                        status_code=409,
                    )
                UserAuth.objects.filter(user=user).update(user=target_user)
                AuthToken.objects.filter(user=user).update(
                    revoked_at=timezone.now(),
                )
                user.status = User.Status.LOGOFF
                user.save(update_fields=["status", "updated_at"])
                target_user.last_login_at = timezone.now()
                target_user.save(update_fields=["last_login_at", "updated_at"])
                merged = True

            login_request.user = target_user
            login_request.is_new_user = False
            login_request.completed_at = timezone.now()
            login_request.save(update_fields=["user", "is_new_user", "completed_at"])
            return PhoneBindingResult(
                login=_create_login_result(target_user, login_request, False),
                already_bound=False,
                merged=merged,
            )
    except ApiError:
        if verification_to_count is not None:
            VerificationCode.objects.filter(pk=verification_to_count.pk).update(
                attempts=F("attempts") + 1
            )
        raise


def _oauth_auth_identifiers(identity: OAuthIdentity) -> list[str]:
    """返回第三方账号的去重 HMAC 映射键，微信优先保留 unionid 和 openid 两个映射。"""
    provider = identity.provider.upper()
    raw_identifiers: list[str] = []
    if provider == UserAuth.Type.APPLE:
        raw_identifiers.append(f"sub:{identity.subject}")
    elif provider == UserAuth.Type.WECHAT:
        if identity.union_id:
            raw_identifiers.append(f"union:{identity.union_id}")
        if identity.open_id:
            raw_identifiers.append(f"openid:{identity.open_id}")
    return list(
        dict.fromkeys(
            hash_oauth_identifier(provider, raw_identifier)
            for raw_identifier in raw_identifiers
            if raw_identifier
        )
    )


def _save_bound_phone(user: User, phone: str) -> None:
    """保存手机号密文和脱敏展示值，不保存明文手机号。"""
    user.phone_hash = hash_phone(phone)
    user.phone_masked = mask_phone(phone)
    user.phone_encrypted = encrypt_text(phone)
    user.save(update_fields=["phone_hash", "phone_masked", "phone_encrypted", "updated_at"])


def _has_external_auth(user: User) -> bool:
    """判断手机号账号是否已经绑定微信或 Apple，避免覆盖已有第三方账号。"""
    return user.auths.filter(auth_type__in=[UserAuth.Type.WECHAT, UserAuth.Type.APPLE]).exists()


def _has_business_data(user: User) -> bool:
    """只允许自动合并尚未产生跨模块业务数据的空账号，避免数据归属被隐式转移。"""
    for relation in User._meta.related_objects:
        model = relation.related_model
        if model._meta.app_label == "accounts":
            continue
        if model._base_manager.filter(**{relation.field.name: user}).exists():
            return True
    return False


def _create_login_result(user: User, login_request: LoginRequest, is_new_user: bool) -> LoginResult:
    access_raw, access_token = _create_token(
        user=user,
        token_type=AuthToken.TokenType.ACCESS,
        session_id=login_request.session_id,
        login_request=login_request,
    )
    refresh_raw, refresh_token = _create_token(
        user=user,
        token_type=AuthToken.TokenType.REFRESH,
        session_id=login_request.session_id,
        login_request=login_request,
    )
    return LoginResult(
        access_token=access_raw,
        refresh_token=refresh_raw,
        expires_in=_remaining_seconds(access_token.expires_at),
        refresh_expires_in=_remaining_seconds(refresh_token.expires_at),
        user_public_id=str(user.public_id),
        is_new_user=is_new_user,
        requires_identity_selection=not user.initial_role_selected,
        requires_phone_binding=user.phone_hash is None,
    )


def _login_result_from_request(login_request: LoginRequest) -> LoginResult:
    if login_request.user is None:
        raise ApiError(ErrorCode.API_ERROR, ERROR_MESSAGES[ErrorCode.API_ERROR], status_code=500)
    tokens = {token.token_type: token for token in login_request.tokens.all()}
    access = tokens.get(AuthToken.TokenType.ACCESS)
    refresh = tokens.get(AuthToken.TokenType.REFRESH)
    if access is None or refresh is None:
        raise ApiError(ErrorCode.API_ERROR, ERROR_MESSAGES[ErrorCode.API_ERROR], status_code=500)
    return LoginResult(
        access_token=_token_raw(access.token_type, access.public_id),
        refresh_token=_token_raw(refresh.token_type, refresh.public_id),
        expires_in=_remaining_seconds(access.expires_at),
        refresh_expires_in=_remaining_seconds(refresh.expires_at),
        user_public_id=str(login_request.user.public_id),
        is_new_user=bool(login_request.is_new_user),
        requires_identity_selection=not login_request.user.initial_role_selected,
        requires_phone_binding=login_request.user.phone_hash is None,
    )


def _create_token(
    *,
    user: User,
    token_type: str,
    session_id: uuid.UUID,
    login_request: LoginRequest | None = None,
) -> tuple[str, AuthToken]:
    token_id = uuid.uuid4()
    raw_token = _token_raw(token_type, token_id)
    lifetime = (
        settings.AUTH_ACCESS_TOKEN_LIFETIME
        if token_type == AuthToken.TokenType.ACCESS
        else settings.AUTH_REFRESH_TOKEN_LIFETIME
    )
    token = AuthToken.objects.create(
        public_id=token_id,
        login_request=login_request,
        user=user,
        session_id=session_id,
        token_type=token_type,
        token_hash=hash_token(raw_token),
        expires_at=timezone.now() + timedelta(seconds=lifetime),
    )
    return raw_token, token


def _remaining_seconds(value) -> int:
    return max(0, int((value - timezone.now()).total_seconds()))


def _token_result(access: AuthToken, refresh: AuthToken) -> LoginResult:
    return LoginResult(
        access_token=_token_raw(access.token_type, access.public_id),
        refresh_token=_token_raw(refresh.token_type, refresh.public_id),
        expires_in=_remaining_seconds(access.expires_at),
        refresh_expires_in=_remaining_seconds(refresh.expires_at),
        user_public_id=str(access.user.public_id),
        is_new_user=False,
        requires_identity_selection=not access.user.initial_role_selected,
        requires_phone_binding=access.user.phone_hash is None,
    )


def refresh_access_token(*, refresh_token_value: str) -> LoginResult:
    """校验刷新令牌并轮换当前设备会话的访问和刷新令牌。"""
    raw_token = refresh_token_value.strip()
    token_hash = hash_token(raw_token)
    with transaction.atomic():
        token = (
            AuthToken.objects.select_for_update()
            .select_related("user")
            .filter(token_hash=token_hash, token_type=AuthToken.TokenType.REFRESH)
            .first()
        )
        if token is None:
            raise ApiError(
                ErrorCode.AUTH_TOKEN_INVALID,
                ERROR_MESSAGES[ErrorCode.AUTH_TOKEN_INVALID],
                status_code=401,
            )
        if token.revoked_at is not None:
            raise ApiError(
                ErrorCode.AUTH_TOKEN_INVALID,
                ERROR_MESSAGES[ErrorCode.AUTH_TOKEN_INVALID],
                status_code=401,
            )
        if token.expires_at <= timezone.now():
            raise ApiError(
                ErrorCode.AUTH_TOKEN_EXPIRED,
                ERROR_MESSAGES[ErrorCode.AUTH_TOKEN_EXPIRED],
                status_code=401,
            )
        if token.user.status != User.Status.ACTIVE:
            raise ApiError(
                ErrorCode.AUTH_ACCOUNT_NOT_ALLOWED,
                "账号状态不允许登录",
                status_code=403,
            )
        User.objects.select_for_update().get(pk=token.user_id)
        now = timezone.now()
        AuthToken.objects.filter(session_id=token.session_id, revoked_at__isnull=True).update(
            revoked_at=now
        )
        access_raw, access = _create_token(
            user=token.user,
            token_type=AuthToken.TokenType.ACCESS,
            session_id=token.session_id,
        )
        refresh_raw, refresh = _create_token(
            user=token.user,
            token_type=AuthToken.TokenType.REFRESH,
            session_id=token.session_id,
        )
        return LoginResult(
            access_token=access_raw,
            refresh_token=refresh_raw,
            expires_in=_remaining_seconds(access.expires_at),
            refresh_expires_in=_remaining_seconds(refresh.expires_at),
            user_public_id=str(token.user.public_id),
            is_new_user=False,
            requires_identity_selection=not token.user.initial_role_selected,
        )


def logout_session(*, user: User, access_token: AuthToken) -> None:
    """撤销当前设备会话的全部有效令牌，不影响其他设备。"""
    if access_token.user_id != user.id or access_token.token_type != AuthToken.TokenType.ACCESS:
        raise ApiError(
            ErrorCode.AUTH_TOKEN_INVALID,
            ERROR_MESSAGES[ErrorCode.AUTH_TOKEN_INVALID],
            status_code=401,
        )
    with transaction.atomic():
        User.objects.select_for_update().get(pk=user.pk)
        AuthToken.objects.filter(
            user=user,
            session_id=access_token.session_id,
            revoked_at__isnull=True,
        ).update(revoked_at=timezone.now())


def session_payload(user: User) -> dict[str, Any]:
    """返回当前用户安全的会话和工作区状态。"""
    return {
        "user_public_id": str(user.public_id),
        "phone_masked": user.phone_masked,
        "status": user.status,
        "requires_identity_selection": not user.initial_role_selected,
        "requires_phone_binding": user.phone_hash is None,
        "auth_methods": sorted(user.auths.values_list("auth_type", flat=True).distinct()),
        "primary_role": user.primary_role,
        "current_role": _current_role(user),
        "roles": _user_roles(user),
        "default_workspace": user.default_workspace,
        "provider_status": user.provider_status,
    }


def select_initial_role(user: User, role: str) -> dict[str, Any]:
    """在事务内完成一次性首次身份选择并返回默认工作区。"""
    normalized_role = role.strip().upper()
    if normalized_role not in User.InitialRole.values:
        raise ApiError(
            ErrorCode.USER_INITIAL_ROLE_INVALID,
            ERROR_MESSAGES[ErrorCode.USER_INITIAL_ROLE_INVALID],
            status_code=400,
        )

    with transaction.atomic():
        current = User.objects.select_for_update().get(pk=user.pk)
        if current.initial_role_selected:
            if (current.initial_role or current.primary_role) != normalized_role:
                raise ApiError(
                    ErrorCode.USER_INITIAL_ROLE_CONFLICT,
                    ERROR_MESSAGES[ErrorCode.USER_INITIAL_ROLE_CONFLICT],
                    status_code=409,
                )
            return initial_role_payload(current)

        current.initial_role = normalized_role
        current.primary_role = normalized_role
        current.initial_role_selected = True
        current.initial_role_selected_at = timezone.now()
        current.default_workspace = (
            User.Workspace.USER_HOME
            if normalized_role == User.InitialRole.USER
            else User.Workspace.PROVIDER_ONBOARDING
        )
        if normalized_role == User.InitialRole.PROVIDER:
            current.provider_status = User.ProviderStatus.NOT_SUBMITTED
        current.save(
            update_fields=[
                "initial_role",
                "primary_role",
                "initial_role_selected",
                "initial_role_selected_at",
                "default_workspace",
                "provider_status",
                "updated_at",
            ]
        )
        return initial_role_payload(current)


def initial_role_payload(user: User) -> dict[str, Any]:
    """返回身份选择和后续页面路由状态。"""
    return {
        "primary_role": user.primary_role,
        "current_role": _current_role(user),
        "roles": _user_roles(user),
        "default_workspace": user.default_workspace,
        "next_route": user.default_workspace,
        "requires_identity_selection": not user.initial_role_selected,
        "provider_status": user.provider_status,
    }


def _current_role(user: User) -> str:
    """返回当前客户端应使用的主身份。"""

    return user.primary_role or User.InitialRole.USER


def _user_roles(user: User) -> list[str]:
    """返回用户当前可用身份，普通用户始终保留，服务者通过后追加。"""

    roles = [User.InitialRole.USER]
    if user.provider_enabled and user.provider_status == User.ProviderStatus.APPROVED:
        roles.append(User.InitialRole.PROVIDER)
    return roles
