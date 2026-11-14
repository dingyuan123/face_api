"""第三方登录适配器的统一输入输出契约。"""

from __future__ import annotations

from dataclasses import dataclass


class OAuthProviderError(Exception):
    """第三方凭据无效或第三方服务返回业务错误。"""


class OAuthProviderUnavailable(Exception):
    """第三方登录服务暂时不可用。"""


@dataclass(frozen=True)
class OAuthIdentity:
    """第三方认证成功后的标准化用户标识。"""

    provider: str
    subject: str
    open_id: str | None = None
    union_id: str | None = None
