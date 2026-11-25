"""Sign in with Apple 的 iOS App 身份令牌验证适配器。"""

from __future__ import annotations

import hashlib
import logging
import time

import jwt
from django.conf import settings
from jwt import PyJWKClient

from backend.integrations.oauth.contracts import (
    OAuthIdentity,
    OAuthProviderError,
    OAuthProviderUnavailable,
)

logger = logging.getLogger("jianmianliao.oauth.apple")


class AppleLoginProvider:
    """验证 Apple 签发的 identity_token，只接受当前 iOS App 的有效用户。"""

    def verify(self, *, identity_token: str, nonce: str) -> OAuthIdentity:
        """验证签名、签发方、受众、时效及存在时的 nonce 后返回 Apple sub。"""
        token = identity_token.strip()
        expected_nonce = nonce.strip()
        if not token or not expected_nonce or not settings.APPLE_CLIENT_ID:
            raise OAuthProviderError("Apple 登录参数或客户端配置不完整")
        try:
            signing_key = PyJWKClient(
                settings.APPLE_JWKS_URL,
                cache_keys=True,
                lifespan=3600,
                timeout=settings.APPLE_JWKS_TIMEOUT_SECONDS,
            ).get_signing_key_from_jwt(token)
            claims = jwt.decode(
                token,
                signing_key.key,
                algorithms=["RS256"],
                audience=settings.APPLE_CLIENT_ID,
                issuer="https://appleid.apple.com",
                options={"require": ["exp", "iat", "iss", "aud", "sub"]},
                leeway=30,
            )
        except jwt.PyJWKClientError as exc:
            raise OAuthProviderUnavailable("Apple 登录验证暂不可用") from exc
        except (jwt.InvalidTokenError, ValueError) as exc:
            raise OAuthProviderError("Apple 登录凭据无效") from exc
        token_nonce = str(claims.get("nonce", ""))
        expected_nonce_hash = hashlib.sha256(expected_nonce.encode("utf-8")).hexdigest()
        nonce_verified = bool(token_nonce)
        if token_nonce and token_nonce not in {expected_nonce, expected_nonce_hash}:
            raise OAuthProviderError("Apple nonce 校验失败")
        if not token_nonce:
            logger.warning(
                "Apple identity_token 未包含 nonce，按客户端兼容模式继续验证标准声明",
                extra={
                    "oauth_provider": "APPLE",
                    "subject_present": bool(claims.get("sub")),
                    "nonce_verified": False,
                },
            )
        if int(claims.get("exp", 0)) <= int(time.time()) - 30:
            raise OAuthProviderError("Apple 登录凭据已过期")
        subject = str(claims.get("sub", "")).strip()
        if not subject:
            raise OAuthProviderError("Apple 登录凭据缺少用户标识")
        return OAuthIdentity(
            provider="APPLE",
            subject=subject,
            nonce_verified=nonce_verified,
        )
