"""微信开放平台 App 登录适配器。"""

from __future__ import annotations

import json
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from django.conf import settings

from backend.integrations.oauth.contracts import (
    OAuthIdentity,
    OAuthProviderError,
    OAuthProviderUnavailable,
)


class WeChatLoginProvider:
    """使用微信临时 code 换取 openid 和 unionid，不信任客户端传入身份标识。"""

    def verify(self, *, code: str, state: str) -> OAuthIdentity:
        """验证登录来源参数并调用微信 OAuth2 接口换取稳定账号标识。"""
        normalized_code = code.strip()
        normalized_state = state.strip()
        if not normalized_code or not normalized_state:
            raise OAuthProviderError("微信登录 code 或 state 不能为空")
        if not settings.WECHAT_LOGIN_APP_ID or not settings.WECHAT_LOGIN_APP_SECRET:
            raise OAuthProviderUnavailable("微信登录 AppID 或 AppSecret 未配置")
        params = {
            "appid": settings.WECHAT_LOGIN_APP_ID,
            "secret": settings.WECHAT_LOGIN_APP_SECRET,
            "code": normalized_code,
            "grant_type": "authorization_code",
        }
        payload = self._get_json(
            f"{settings.WECHAT_LOGIN_API_BASE_URL.rstrip('/')}/sns/oauth2/access_token",
            params,
        )
        print(payload)
        if payload.get("errcode"):
            raise OAuthProviderError("微信登录凭据无效")
        open_id = str(payload.get("openid", "")).strip()
        union_id = str(payload.get("unionid", "")).strip() or None
        if not open_id:
            raise OAuthProviderError("微信登录响应缺少 openid")
        return OAuthIdentity(
            provider="WECHAT",
            subject=union_id or open_id,
            open_id=open_id,
            union_id=union_id,
        )

    def _get_json(self, url: str, params: dict[str, str]) -> dict[str, object]:
        request = Request(
            f"{url}?{urlencode(params)}",
            headers={
                "Accept": "application/json",
                "User-Agent": "JianMianLiaoOAuth/1.0",
            },
        )
        try:
            with urlopen(request, timeout=settings.WECHAT_LOGIN_TIMEOUT_SECONDS) as response:
                raw = response.read(64 * 1024).decode("utf-8")
                payload = json.loads(raw)
        except (HTTPError, URLError, TimeoutError, json.JSONDecodeError, UnicodeDecodeError):
            raise OAuthProviderUnavailable("微信登录服务暂不可用") from None
        if not isinstance(payload, dict):
            raise OAuthProviderUnavailable("微信登录响应格式不正确")
        return payload
