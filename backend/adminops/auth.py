"""管理后台独立令牌认证、角色权限和审计辅助服务。"""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import uuid
from datetime import timedelta
from typing import Any

from django.conf import settings
from django.contrib.auth.hashers import check_password, make_password
from django.core.cache import cache
from django.db import transaction
from django.utils import timezone
from drf_spectacular.extensions import OpenApiAuthenticationExtension
from rest_framework.authentication import BaseAuthentication, get_authorization_header
from rest_framework.exceptions import AuthenticationFailed

from backend.accounts.models import User, VerificationCode
from backend.accounts.services import hash_phone, send_sms_code
from backend.adminops.models import (
    AdminAuthToken,
    AdminOperationLog,
    AdminPermission,
    AdminRole,
    AdminRoleMember,
    AdminRolePermission,
)
from backend.common.context import current_trace_id
from backend.common.errors import ERROR_MESSAGES, ErrorCode
from backend.common.exceptions import ApiError

PERMISSIONS = {
    "admin.session.read": "查看管理员会话",
    "admin.dashboard.read": "查看管理后台总览",
    "admin.user.read": "查看用户",
    "admin.user.ban": "封禁和解封用户",
    "admin.user.force_delete": "强制注销用户",
    "admin.provider.read": "查看服务者",
    "admin.provider.status": "调整服务者状态",
    "admin.order.read": "查看管理员订单",
    "admin.order.cancel": "取消管理员订单",
    "admin.finance.read": "查看财务流水和总览",
    "admin.finance.adjust": "人工清空和调整用户资金",
    "admin.commission.read": "查看佣金统计",
    "admin.withdrawal.read": "查看提现单",
    "admin.withdrawal.write": "审核提现单",
    "admin.report.read": "查看内容举报",
    "admin.report.write": "处理内容举报",
    "admin.moderation.read": "查看敏感词",
    "admin.moderation.write": "维护敏感词",
    "admin.analytics.read": "查看平台数据看板",
    "admin.settings.read": "查看系统设置",
    "admin.settings.write": "维护系统设置",
    "admin.support.read": "查看客服工单",
    "admin.support.reply": "回复客服工单",
    "admin.support.assign": "分配客服工单",
    "admin.support.close": "处理客服工单",
    "admin.support.write": "维护客服常见问题",
    "admin.audit.read": "查看管理审计",
    "admin.rbac.read": "查看角色权限",
    "admin.rbac.write": "维护角色权限",
    "admin.identity.review": "审核实名认证",
    "admin.provider_application.review": "审核服务者申请",
}


def ensure_admin_rbac(user: User) -> AdminRole:
    """为存量 is_staff 管理员创建默认超级管理员角色和成员关系。"""
    with transaction.atomic():
        for code, name in PERMISSIONS.items():
            AdminPermission.objects.get_or_create(
                code=code,
                defaults={"name": name, "category": code.split(".")[1]},
            )
        role, _ = AdminRole.objects.get_or_create(
            code="SUPER_ADMIN",
            defaults={
                "name": "超级管理员",
                "description": "开发测试阶段拥有全部管理权限",
            },
        )
        permission_ids = list(AdminPermission.objects.values_list("id", flat=True))
        for permission_id in permission_ids:
            AdminRolePermission.objects.get_or_create(
                role=role,
                permission_id=permission_id,
            )
        if user.is_staff and not AdminRoleMember.objects.filter(user=user).exists():
            AdminRoleMember.objects.get_or_create(
                role=role,
                user=user,
                defaults={"assigned_by": user.id},
            )
        return role


def _admin_token_raw(token_type: str, token_id: uuid.UUID) -> str:
    key = settings.AUTH_TOKEN_SIGNING_KEY.encode("utf-8")
    digest = hmac.new(
        key,
        f"admin:{token_type}:{token_id}".encode(),
        hashlib.sha256,
    ).hexdigest()
    return f"{token_id}.{digest[:40]}"


def _issue_token(
    *,
    user: User,
    session_id: uuid.UUID,
    token_type: str,
) -> tuple[str, AdminAuthToken]:
    token_id = uuid.uuid4()
    raw = _admin_token_raw(token_type, token_id)
    lifetime = (
        settings.AUTH_ACCESS_TOKEN_LIFETIME
        if token_type == AdminAuthToken.TokenType.ACCESS
        else settings.AUTH_REFRESH_TOKEN_LIFETIME
    )
    token = AdminAuthToken.objects.create(
        public_id=token_id,
        user=user,
        session_id=session_id,
        token_type=token_type,
        token_hash=hash_token(raw),
        expires_at=timezone.now() + timedelta(seconds=lifetime),
    )
    return raw, token


def hash_token(raw_token: str) -> str:
    """计算管理后台令牌哈希。"""
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def permission_codes_for_user(user: User) -> list[str]:
    """返回管理员已启用角色权限点。"""
    ensure_admin_rbac(user)
    return sorted(
        AdminPermission.objects.filter(
            role_links__role__members__user=user,
            role_links__role__status=AdminRole.Status.ACTIVE,
        )
        .values_list("code", flat=True)
        .distinct()
    )


def roles_for_user(user: User) -> list[str]:
    """返回管理员启用角色代码。"""
    ensure_admin_rbac(user)
    return sorted(
        AdminRole.objects.filter(
            members__user=user,
            status=AdminRole.Status.ACTIVE,
        )
        .values_list("code", flat=True)
        .distinct()
    )


def admin_login(
    *,
    phone: str,
    password: str,
    captcha_token: str = "",
    captcha_answer: str = "",
) -> dict[str, Any]:
    """校验管理员密码并签发独立管理后台令牌。"""
    validate_admin_captcha(captcha_token, captcha_answer)
    phone_hash = hash_phone(phone)
    user = User.objects.filter(
        phone_hash=phone_hash,
        is_staff=True,
        status=User.Status.ACTIVE,
    ).first()
    if user is None or not check_password(password, user.password):
        raise ApiError(
            ErrorCode.AUTH_INVALID_CREDENTIALS,
            ERROR_MESSAGES[ErrorCode.AUTH_INVALID_CREDENTIALS],
            status_code=401,
        )
    ensure_admin_rbac(user)
    session_id = uuid.uuid4()
    access_raw, access_token = _issue_token(
        user=user,
        session_id=session_id,
        token_type=AdminAuthToken.TokenType.ACCESS,
    )
    refresh_raw, refresh_token = _issue_token(
        user=user,
        session_id=session_id,
        token_type=AdminAuthToken.TokenType.REFRESH,
    )
    return {
        "token_type": "Bearer",
        "access_token": access_raw,
        "refresh_token": refresh_raw,
        "expires_in": max(
            0,
            int((access_token.expires_at - timezone.now()).total_seconds()),
        ),
        "refresh_expires_in": max(
            0,
            int((refresh_token.expires_at - timezone.now()).total_seconds()),
        ),
        "admin_public_id": str(user.public_id),
        "display_name": user.phone_masked,
        "roles": roles_for_user(user),
        "permissions": permission_codes_for_user(user),
        "menu_version": 1,
    }


def create_admin_captcha() -> dict[str, Any]:
    """创建开发测试用图形验证码挑战。"""
    if not settings.ADMIN_CAPTCHA_ENABLED:
        raise ApiError(
            ErrorCode.AUTH_CAPTCHA_INVALID,
            "当前环境未启用图形验证码",
            status_code=404,
        )
    token = str(uuid.uuid4())
    left = secrets.randbelow(20) + 1
    right = secrets.randbelow(20) + 1
    cache.set(f"admin-captcha:{token}", str(left + right), timeout=300)
    return {
        "captcha_token": token,
        "question": f"{left} + {right} = ?",
        "image_url": None,
        "expires_in": 300,
    }


def validate_admin_captcha(token: str, answer: str) -> None:
    """校验管理员登录图形验证码。"""
    if not settings.ADMIN_CAPTCHA_ENABLED:
        return
    if not token or not answer:
        raise ApiError(
            ErrorCode.AUTH_CAPTCHA_REQUIRED,
            ERROR_MESSAGES[ErrorCode.AUTH_CAPTCHA_REQUIRED],
            status_code=400,
        )
    expected = cache.get(f"admin-captcha:{token}")
    if expected is None or str(answer).strip() != expected:
        raise ApiError(
            ErrorCode.AUTH_CAPTCHA_INVALID,
            ERROR_MESSAGES[ErrorCode.AUTH_CAPTCHA_INVALID],
            status_code=400,
        )
    cache.delete(f"admin-captcha:{token}")


def admin_password_forgot(*, phone: str) -> dict[str, Any]:
    """为管理员手机号发送密码重置验证码。"""
    result = send_sms_code(
        phone_value=phone,
        purpose=VerificationCode.Purpose.PASSWORD_RESET,
    )
    return {
        "request_id": result.request_id,
        "expires_in": result.expires_in,
        "reused": result.reused,
        "debug_code": result.debug_code,
    }


def admin_password_reset(
    *,
    phone: str,
    code: str,
    new_password: str,
) -> dict[str, bool]:
    """验证短信码并重置管理员密码，撤销现有管理会话。"""
    phone_hash = hash_phone(phone)
    if len(new_password) < 12:
        raise ApiError(
            ErrorCode.AUTH_INVALID_CREDENTIALS,
            "管理员密码至少需要 12 位",
            status_code=400,
        )
    verification = (
        VerificationCode.objects.select_for_update()
        .filter(
            phone_hash=phone_hash,
            purpose=VerificationCode.Purpose.PASSWORD_RESET,
            consumed_at__isnull=True,
        )
        .order_by("-created_at")
        .first()
    )
    if (
        verification is None
        or verification.expires_at <= timezone.now()
        or not check_password(code, verification.code_hash)
    ):
        raise ApiError(
            ErrorCode.AUTH_CODE_INVALID,
            ERROR_MESSAGES[ErrorCode.AUTH_CODE_INVALID],
            status_code=400,
        )
    user = User.objects.filter(
        phone_hash=phone_hash,
        is_staff=True,
        status=User.Status.ACTIVE,
    ).first()
    if user is None:
        raise ApiError(
            ErrorCode.AUTH_ACCOUNT_NOT_ALLOWED,
            ERROR_MESSAGES[ErrorCode.AUTH_ACCOUNT_NOT_ALLOWED],
            status_code=403,
        )
    verification.consumed_at = timezone.now()
    verification.save(update_fields=["consumed_at"])
    user.password = make_password(new_password)
    user.save(update_fields=["password", "updated_at"])
    AdminAuthToken.objects.filter(user=user, revoked_at__isnull=True).update(
        revoked_at=timezone.now()
    )
    return {"password_reset": True}


def admin_refresh(*, refresh_token: str) -> dict[str, Any]:
    """轮换管理员会话访问和刷新令牌。"""
    token = (
        AdminAuthToken.objects.select_related("user")
        .filter(
            token_hash=hash_token(refresh_token),
            token_type=AdminAuthToken.TokenType.REFRESH,
        )
        .first()
    )
    if (
        token is None
        or token.revoked_at is not None
        or token.expires_at <= timezone.now()
        or token.user.status != User.Status.ACTIVE
        or not token.user.is_staff
    ):
        raise ApiError(
            ErrorCode.AUTH_TOKEN_INVALID,
            ERROR_MESSAGES[ErrorCode.AUTH_TOKEN_INVALID],
            status_code=401,
        )
    with transaction.atomic():
        now = timezone.now()
        AdminAuthToken.objects.filter(session_id=token.session_id).update(revoked_at=now)
        access_raw, access = _issue_token(
            user=token.user,
            session_id=token.session_id,
            token_type=AdminAuthToken.TokenType.ACCESS,
        )
        refresh_raw, refresh = _issue_token(
            user=token.user,
            session_id=token.session_id,
            token_type=AdminAuthToken.TokenType.REFRESH,
        )
    return {
        "token_type": "Bearer",
        "access_token": access_raw,
        "refresh_token": refresh_raw,
        "expires_in": max(
            0,
            int((access.expires_at - timezone.now()).total_seconds()),
        ),
        "refresh_expires_in": max(
            0,
            int((refresh.expires_at - timezone.now()).total_seconds()),
        ),
        "admin_public_id": str(token.user.public_id),
        "display_name": token.user.phone_masked,
        "roles": roles_for_user(token.user),
        "permissions": permission_codes_for_user(token.user),
        "menu_version": 1,
    }


def admin_logout(*, access_token: AdminAuthToken) -> dict[str, bool]:
    """撤销当前管理员会话全部令牌。"""
    AdminAuthToken.objects.filter(session_id=access_token.session_id).update(
        revoked_at=timezone.now()
    )
    return {"logged_out": True}


class AdminBearerTokenAuthentication(BaseAuthentication):
    """解析独立管理后台 Bearer 令牌。"""

    keyword = b"bearer"

    def authenticate(self, request):
        auth = get_authorization_header(request).split()
        if not auth or auth[0].lower() != self.keyword:
            return None
        if len(auth) != 2:
            raise AuthenticationFailed(
                ERROR_MESSAGES[ErrorCode.AUTH_TOKEN_INVALID],
                code=ErrorCode.AUTH_TOKEN_INVALID,
            )
        raw = auth[1].decode("utf-8")
        token = (
            AdminAuthToken.objects.select_related("user")
            .filter(
                token_hash=hash_token(raw),
                token_type=AdminAuthToken.TokenType.ACCESS,
            )
            .first()
        )
        if (
            token is None
            or token.revoked_at is not None
            or token.expires_at <= timezone.now()
            or token.user.status != User.Status.ACTIVE
            or not token.user.is_staff
        ):
            raise AuthenticationFailed(
                ERROR_MESSAGES[ErrorCode.AUTH_TOKEN_INVALID],
                code=ErrorCode.AUTH_TOKEN_INVALID,
            )
        token.last_used_at = timezone.now()
        token.save(update_fields=["last_used_at"])
        return token.user, token

    def authenticate_header(self, request):
        return "Bearer"


class AdminBearerTokenAuthenticationScheme(OpenApiAuthenticationExtension):
    """向 OpenAPI 注册独立管理后台 Bearer 安全方案。"""

    target_class = "backend.adminops.auth.AdminBearerTokenAuthentication"
    name = "AdminBearerTokenAuth"

    def get_security_definition(self, auto_schema):
        return {
            "type": "http",
            "scheme": "bearer",
            "bearerFormat": "opaque",
        }


def require_admin_permission(user: User, permission_code: str) -> None:
    """校验管理员权限点，禁止只依赖前端按钮。"""
    if permission_code not in permission_codes_for_user(user):
        raise ApiError(
            ErrorCode.PERMISSION_DENIED,
            ERROR_MESSAGES[ErrorCode.PERMISSION_DENIED],
            status_code=403,
            details={"permission": permission_code},
        )


def write_admin_operation(
    *,
    operator: User,
    action: str,
    target_type: str,
    target_id: str,
    before_state: dict[str, Any] | None = None,
    after_state: dict[str, Any] | None = None,
    reason: str = "",
    idempotency_key: str = "",
) -> AdminOperationLog:
    """记录管理员写操作审计。"""

    def json_state(value: dict[str, Any] | None) -> dict[str, Any]:
        if not value:
            return {}
        return json.loads(json.dumps(value, ensure_ascii=False, default=str))

    return AdminOperationLog.objects.create(
        operator=operator,
        operator_role="SUPER_ADMIN",
        action=action,
        target_type=target_type,
        target_id=str(target_id),
        before_state=json_state(before_state),
        after_state=json_state(after_state),
        reason=reason,
        idempotency_key=idempotency_key,
        trace_id=current_trace_id(),
    )
