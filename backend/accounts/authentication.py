"""Bearer 不透明访问令牌认证和 OpenAPI 安全方案声明。"""

from __future__ import annotations

from django.utils import timezone
from drf_spectacular.extensions import OpenApiAuthenticationExtension
from rest_framework.authentication import BaseAuthentication, get_authorization_header
from rest_framework.exceptions import AuthenticationFailed

from backend.accounts.models import AuthToken, User
from backend.accounts.services import hash_token
from backend.common.errors import ERROR_MESSAGES, ErrorCode


class BearerTokenAuthentication(BaseAuthentication):
    """从 Authorization 头解析并校验当前访问令牌。"""

    keyword = b"bearer"

    def authenticate(self, request):
        """校验令牌哈希、撤销状态、过期时间和账号状态。"""
        auth = get_authorization_header(request).split()
        if not auth or auth[0].lower() != self.keyword:
            return None
        if len(auth) != 2:
            raise AuthenticationFailed(
                ERROR_MESSAGES[ErrorCode.AUTH_TOKEN_INVALID],
                code=ErrorCode.AUTH_TOKEN_INVALID,
            )
        raw_token = auth[1].decode("utf-8")
        token = (
            AuthToken.objects.select_related("user")
            .filter(token_hash=hash_token(raw_token), token_type=AuthToken.TokenType.ACCESS)
            .first()
        )
        if token is None or token.revoked_at is not None:
            raise AuthenticationFailed(
                ERROR_MESSAGES[ErrorCode.AUTH_TOKEN_INVALID],
                code=ErrorCode.AUTH_TOKEN_INVALID,
            )
        if token.expires_at <= timezone.now():
            raise AuthenticationFailed(
                ERROR_MESSAGES[ErrorCode.AUTH_TOKEN_EXPIRED],
                code=ErrorCode.AUTH_TOKEN_EXPIRED,
            )
        if token.user.status != User.Status.ACTIVE:
            raise AuthenticationFailed(
                "账号状态不允许访问",
                code=ErrorCode.AUTH_ACCOUNT_NOT_ALLOWED,
            )
        token.last_used_at = timezone.now()
        token.save(update_fields=["last_used_at"])
        return token.user, token

    def authenticate_header(self, request):
        """返回 Bearer 认证质询头。"""
        return "Bearer"


class BearerTokenAuthenticationScheme(OpenApiAuthenticationExtension):
    """向 OpenAPI 注册 Bearer 令牌安全方案。"""

    target_class = "backend.accounts.authentication.BearerTokenAuthentication"
    name = "BearerTokenAuth"

    def get_security_definition(self, auto_schema):
        """返回 OpenAPI HTTP Bearer 安全定义。"""
        return {
            "type": "http",
            "scheme": "bearer",
            "bearerFormat": "opaque",
        }
