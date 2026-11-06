"""搜索词规范化、长度校验和敏感信息识别公共工具。"""

from __future__ import annotations

import re
import unicodedata

from django.conf import settings

from backend.common.errors import ERROR_MESSAGES, ErrorCode
from backend.common.exceptions import ApiError

WHITESPACE_PATTERN = re.compile(r"\s+")
PHONE_PATTERN = re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)")
EMAIL_PATTERN = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
URL_PATTERN = re.compile(r"\b(?:https?://|www\.)\S+\b", re.IGNORECASE)
ID_CARD_PATTERN = re.compile(r"(?<!\d)\d{17}[\dXx](?!\d)")
BANK_CARD_PATTERN = re.compile(r"(?<!\d)\d{16,19}(?!\d)")


def normalize_search_keyword(keyword: str) -> tuple[str, str]:
    """返回规范化检索词和安全展示词，统一空白、兼容字符和大小写。"""

    display = WHITESPACE_PATTERN.sub(" ", unicodedata.normalize("NFKC", keyword)).strip()
    return display.casefold(), display


def validate_search_keyword(keyword: str | None) -> tuple[str, str]:
    """校验搜索词非空和长度，并返回规范化检索词及展示词。"""

    raw = str(keyword or "").strip()
    if not raw:
        raise _invalid("keyword", "搜索关键词不能为空")
    normalized, display = normalize_search_keyword(raw)
    max_length = settings.SEARCH_KEYWORD_MAX_LENGTH
    if len(normalized) > max_length:
        raise _invalid("keyword", f"搜索关键词不能超过 {max_length} 个字符")
    return normalized, display


def is_sensitive_search_keyword(keyword: str) -> bool:
    """判断搜索词是否包含手机号、身份证、邮箱、链接或银行卡等敏感信息。"""

    compact = WHITESPACE_PATTERN.sub("", keyword)
    return any(
        pattern.search(compact)
        for pattern in (
            PHONE_PATTERN,
            EMAIL_PATTERN,
            URL_PATTERN,
            ID_CARD_PATTERN,
            BANK_CARD_PATTERN,
        )
    )


def _invalid(field: str, message: str) -> ApiError:
    """构造统一搜索参数错误。"""

    return ApiError(
        ErrorCode.SEARCH_INVALID,
        ERROR_MESSAGES[ErrorCode.SEARCH_INVALID],
        status_code=400,
        details={field: message},
    )
