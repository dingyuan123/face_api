"""服务者数据看板匿名事件记录和隐私摘要处理。"""

from __future__ import annotations

from typing import Any

from django.db import IntegrityError

from backend.common.crypto import sensitive_fingerprint
from backend.providers.models import ProviderAnalyticsEvent


def _request_value(request: Any, name: str) -> str:
    """从 Django/DRF 请求中读取可选的匿名访客标识。"""
    request = getattr(request, "_request", request)
    headers = getattr(request, "headers", {})
    value = headers.get("X-Visitor-ID") or headers.get("x-visitor-id")
    if value:
        return str(value).strip()
    query = getattr(request, "GET", {})
    return str(query.get("visitor_id", "") or "").strip()


def _hash(value: str, kind: str) -> str:
    """生成不可逆请求摘要，不保存原始访客标识、IP 或 User-Agent。"""
    return sensitive_fingerprint({kind: value}) if value else ""


def record_provider_event(
    *,
    provider_user_id: int,
    event_type: str,
    request: Any = None,
    service_public_id: str | None = None,
    biz_id: str = "",
    visitor_id: str | None = None,
) -> ProviderAnalyticsEvent | None:
    """幂等记录服务者浏览或转化事件；不记录个人敏感信息。"""
    if event_type not in ProviderAnalyticsEvent.EventType.values:
        return None
    visitor_value = visitor_id or _request_value(request, "visitor_id")
    request_obj = getattr(request, "_request", request)
    visitor_hash = _hash(visitor_value, "visitor_id")
    ip_hash = _hash(
        str(getattr(request_obj, "META", {}).get("REMOTE_ADDR", "")),
        "ip",
    )
    user_agent_hash = _hash(
        str(getattr(request_obj, "META", {}).get("HTTP_USER_AGENT", "")),
        "user_agent",
    )
    event_key = ""
    if biz_id:
        event_key = f"provider-event:{event_type}:{biz_id}"
    defaults = {
        "provider_user_id": provider_user_id,
        "event_type": event_type,
        "service_public_id": service_public_id,
        "biz_id": biz_id,
        "visitor_hash": visitor_hash,
        "ip_hash": ip_hash,
        "user_agent_hash": user_agent_hash,
    }
    if not event_key:
        return ProviderAnalyticsEvent.objects.create(event_key="", **defaults)
    try:
        event, _ = ProviderAnalyticsEvent.objects.get_or_create(
            event_key=event_key,
            defaults=defaults,
        )
        return event
    except IntegrityError:
        return ProviderAnalyticsEvent.objects.filter(event_key=event_key).first()
