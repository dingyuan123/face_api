"""敏感文本加密、HMAC 摘要和请求指纹公共能力。"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
from typing import Any

from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings

from backend.common.errors import ERROR_MESSAGES, ErrorCode
from backend.common.exceptions import ApiError


def _fernet() -> Fernet:
    raw_key = settings.IDENTITY_ENCRYPTION_KEY.encode("utf-8")
    try:
        return Fernet(raw_key)
    except (ValueError, TypeError):
        digest = hashlib.sha256(raw_key).digest()
        return Fernet(base64.urlsafe_b64encode(digest))


def encrypt_text(value: str) -> str:
    """使用身份加密密钥对敏感文本进行 Fernet 加密。"""
    return _fernet().encrypt(value.encode("utf-8")).decode("ascii")


def decrypt_text(value: str) -> str:
    """解密身份敏感文本；失败时返回统一内部错误。"""
    try:
        return _fernet().decrypt(value.encode("ascii")).decode("utf-8")
    except (InvalidToken, ValueError) as exc:
        raise ApiError(
            ErrorCode.INTERNAL_ERROR,
            ERROR_MESSAGES[ErrorCode.INTERNAL_ERROR],
            status_code=500,
        ) from exc


def hash_sensitive_text(value: str) -> str:
    """使用服务端密钥计算敏感文本 HMAC，不保存可直接碰撞的明文摘要。"""
    key = settings.IDENTITY_ENCRYPTION_KEY.encode("utf-8")
    return hmac.new(key, value.encode("utf-8"), hashlib.sha256).hexdigest()


def sensitive_fingerprint(payload: dict[str, Any]) -> str:
    """计算稳定请求指纹，用于判断同幂等键请求内容是否一致。"""
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hash_sensitive_text(encoded)
