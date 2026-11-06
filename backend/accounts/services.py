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
        {"phone": phone_hash, "code": code_text, "purpose": VerificationCode.Purpose.LOGIN}
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
        "primary_role": user.primary_role,
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
            if current.primary_role != normalized_role:
                raise ApiError(
                    ErrorCode.USER_INITIAL_ROLE_CONFLICT,
                    ERROR_MESSAGES[ErrorCode.USER_INITIAL_ROLE_CONFLICT],
                    status_code=409,
                )
            return initial_role_payload(current)

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
        "default_workspace": user.default_workspace,
        "next_route": user.default_workspace,
        "requires_identity_selection": not user.initial_role_selected,
        "provider_status": user.provider_status,
    }
