from __future__ import annotations

from datetime import date, datetime
from typing import Any
from zoneinfo import ZoneInfo

from django.conf import settings
from django.utils import timezone
from rest_framework.renderers import JSONRenderer

from backend.common.context import current_trace_id


def build_success_envelope(data: Any, meta: dict[str, Any] | None = None) -> dict[str, Any]:
    trace_id = current_trace_id()
    response_meta = {"trace_id": trace_id}
    if meta:
        response_meta.update(meta)
    return {
        "code": 0,
        "message": "success",
        "data": data,
        "meta": response_meta,
        "trace_id": trace_id,
    }


def build_error_envelope(
    code: str,
    message: str,
    details: Any | None = None,
) -> dict[str, Any]:
    trace_id = current_trace_id()
    return {
        "code": code,
        "message": message,
        "details": details,
        "trace_id": trace_id,
    }


class ApiJSONRenderer(JSONRenderer):
    media_type = "application/json"
    charset = "utf-8"

    def render(
        self,
        data: Any,
        accepted_media_type: str | None = None,
        renderer_context: dict[str, Any] | None = None,
    ) -> bytes:
        if not _is_envelope(data):
            data = build_success_envelope(data)
        data = _format_api_value(data)
        return super().render(data, accepted_media_type, renderer_context)


def _format_api_value(value: Any) -> Any:
    """递归格式化 API 时间，日期保持 YYYY-MM-DD。"""

    if isinstance(value, datetime):
        display_value = (
            timezone.localtime(value, ZoneInfo(settings.API_DISPLAY_TIMEZONE))
            if timezone.is_aware(value)
            else value
        )
        return display_value.strftime(settings.API_DATETIME_FORMAT)
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): _format_api_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_format_api_value(item) for item in value]
    return value


def _is_envelope(data: Any) -> bool:
    if not isinstance(data, dict):
        return False
    success_keys = {"code", "message", "data", "meta", "trace_id"}
    error_keys = {"code", "message", "details", "trace_id"}
    return success_keys.issubset(data) or error_keys.issubset(data)
