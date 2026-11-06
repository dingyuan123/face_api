from __future__ import annotations

import json
import logging
import re
from typing import Any

from backend.common.context import current_trace_id

SENSITIVE_KEYS = {
    "access_token",
    "api_key",
    "authorization",
    "bank_card",
    "cookie",
    "face",
    "id_card",
    "identity_number",
    "location",
    "password",
    "phone",
    "private_key",
    "refresh_token",
    "secret",
    "token",
}
REDACTED = "[REDACTED]"
SENSITIVE_KEY_MARKERS = (
    "password",
    "token",
    "secret",
    "authorization",
    "api_key",
    "id_card",
    "bank_card",
)
SENSITIVE_PATTERNS = (
    re.compile(r"(?i)(bearer\s+)[a-z0-9._~+/=-]+"),
    re.compile(r"(?i)\b(password|token|secret|api_key)(\s*[=:]\s*)[^,\s;}]+"),
    re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)"),
)


def redact_text(value: str) -> str:
    redacted = SENSITIVE_PATTERNS[0].sub(r"\1" + REDACTED, value)
    redacted = SENSITIVE_PATTERNS[1].sub(
        lambda match: match.group(1) + match.group(2) + REDACTED, redacted
    )
    return SENSITIVE_PATTERNS[2].sub(REDACTED, redacted)


def redact_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: REDACTED if is_sensitive_key(str(key)) else redact_value(item)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [redact_value(item) for item in value]
    if isinstance(value, str):
        return redact_text(value)
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return redact_text(str(value))


def is_sensitive_key(key: str) -> bool:
    normalized = key.lower()
    return normalized in SENSITIVE_KEYS or any(
        marker in normalized for marker in SENSITIVE_KEY_MARKERS
    )


class SensitiveDataFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = redact_value(record.getMessage())
        record.args = ()
        for key, value in list(record.__dict__.items()):
            if key in {"exc_info", "exc_text", "stack_info", "args", "msg"}:
                continue
            if is_sensitive_key(key):
                record.__dict__[key] = REDACTED
            elif key not in {"message", "asctime"} and isinstance(value, (dict, list, tuple, str)):
                record.__dict__[key] = redact_value(value)
        return True


class RequestTraceFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.trace_id = current_trace_id()
        return True


class RedactingJsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": self.formatTime(record, datefmt="%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "message": redact_value(record.getMessage()),
            "trace_id": getattr(record, "trace_id", current_trace_id()),
        }
        for key, value in record.__dict__.items():
            if key in logging.LogRecord("", 0, "", 0, "", (), None).__dict__:
                continue
            if key in {"trace_id", "message", "asctime"}:
                continue
            if is_sensitive_key(key):
                payload[key] = REDACTED
            else:
                payload[key] = redact_value(value)
        if record.exc_info:
            payload["exception"] = redact_text(self.formatException(record.exc_info))
        return json.dumps(payload, ensure_ascii=False, default=str)
