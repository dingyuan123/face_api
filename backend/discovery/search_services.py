"""综合搜索聚合、分类搜索分页和搜索热度记录业务服务。"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any
from zoneinfo import ZoneInfo

from django.conf import settings
from django.db import IntegrityError, transaction
from django.db.models import F
from django.http import HttpRequest
from django.utils import timezone
from rest_framework.request import Request

from backend.accounts.models import User
from backend.common.pagination import ApiCursorPagination
from backend.common.search import (
    is_sensitive_search_keyword,
    validate_search_keyword,
)
from backend.content.news_services import list_public_news
from backend.content.services import moment_payloads, public_moment_queryset
from backend.discovery.models import SearchQueryStat
from backend.discovery.services import home_feed_payloads
from backend.providers.public_services import provider_search_queryset


def record_search_keyword(display_keyword: str, normalized_keyword: str) -> None:
    """按自然日聚合非敏感搜索词，不保存搜索用户、设备或原始请求。"""

    if is_sensitive_search_keyword(display_keyword):
        return
    local_today = timezone.localtime(
        timezone.now(),
        ZoneInfo(settings.API_DISPLAY_TIMEZONE),
    ).date()
    try:
        with transaction.atomic():
            stat, created = SearchQueryStat.objects.get_or_create(
                search_date=local_today,
                normalized_keyword=normalized_keyword,
                defaults={"display_keyword": display_keyword[:100], "search_count": 1},
            )
            if not created:
                SearchQueryStat.objects.filter(pk=stat.pk).update(
                    search_count=F("search_count") + 1,
                    display_keyword=display_keyword[:100],
                )
    except IntegrityError:
        SearchQueryStat.objects.filter(
            search_date=local_today,
            normalized_keyword=normalized_keyword,
        ).update(search_count=F("search_count") + 1)


def validated_search_terms(keyword: str | None) -> tuple[str, str]:
    """校验搜索词并记录聚合热度，返回规范化词和展示词。"""

    normalized, display = validate_search_keyword(keyword)
    record_search_keyword(display, normalized)
    return normalized, display


def _cursor_payload(
    *,
    queryset,
    payload_builder: Callable[[list[Any], HttpRequest | None, User | None], list[dict[str, Any]]],
    request: Request,
    view,
    limit: int,
    http_request: HttpRequest | None,
    viewer: User | None,
) -> dict[str, Any]:
    """使用统一游标分页器生成分类搜索响应。"""

    paginator = ApiCursorPagination()
    paginator.page_size = limit
    total = queryset.count()
    page_items = paginator.paginate_queryset(queryset, request, view=view) or []
    return {
        "items": payload_builder(page_items, http_request, viewer),
        "total": total,
        "next_cursor": paginator.get_next_link_cursor(),
        "has_more": paginator.get_next_link() is not None,
        "limit": paginator.get_page_size(request),
    }


def search_all_payload(
    *,
    keyword: str,
    preview_limit: int,
    request: HttpRequest | None = None,
    viewer: User | None = None,
) -> dict[str, Any]:
    """返回服务者、动态和资讯三个公开分组的综合搜索预览及准确总数。"""

    normalized, display = validated_search_terms(keyword)
    provider_queryset = provider_search_queryset(keyword=normalized)
    moment_queryset = public_moment_queryset(keyword=normalized)
    news_result = list_public_news(
        keyword=normalized,
        page=1,
        page_size=preview_limit,
        request=request,
    )
    provider_total = provider_queryset.count()
    moment_total = moment_queryset.count()
    provider_items = list(provider_queryset[:preview_limit])
    moment_items = list(moment_queryset[:preview_limit])
    return {
        "keyword": display,
        "providers": {
            "total": provider_total,
            "items": home_feed_payloads(provider_items, request),
            "has_more": provider_total > len(provider_items),
        },
        "moments": {
            "total": moment_total,
            "items": moment_payloads(moment_items, request, viewer),
            "has_more": moment_total > len(moment_items),
        },
        "news": {
            "total": news_result["total"],
            "items": news_result["items"],
            "has_more": news_result["total"] > len(news_result["items"]),
        },
    }


def search_provider_payload(
    *,
    keyword: str,
    request: Request,
    http_request: HttpRequest | None,
    viewer: User | None,
    limit: int,
    view,
) -> dict[str, Any]:
    """返回公开服务者关键词搜索游标分页。"""

    normalized, _ = validated_search_terms(keyword)
    return _cursor_payload(
        queryset=provider_search_queryset(keyword=normalized),
        payload_builder=lambda items, current_request, current_viewer: home_feed_payloads(
            items,
            current_request,
        ),
        request=request,
        view=view,
        limit=limit,
        http_request=http_request,
        viewer=viewer,
    )


def search_moment_payload(
    *,
    keyword: str,
    request: Request,
    http_request: HttpRequest | None,
    viewer: User | None,
    limit: int,
    view,
) -> dict[str, Any]:
    """返回公开动态关键词搜索游标分页。"""

    normalized, _ = validated_search_terms(keyword)
    return _cursor_payload(
        queryset=public_moment_queryset(keyword=normalized),
        payload_builder=lambda items, current_request, current_viewer: moment_payloads(
            items,
            current_request,
            current_viewer,
        ),
        request=request,
        view=view,
        limit=limit,
        http_request=http_request,
        viewer=viewer,
    )


def search_news_payload(
    *,
    keyword: str,
    request: HttpRequest | None,
    page: int,
    page_size: int,
) -> dict[str, Any]:
    """返回公开资讯关键词搜索页码分页。"""

    normalized, _ = validated_search_terms(keyword)
    return list_public_news(
        keyword=normalized,
        page=page,
        page_size=page_size,
        request=request,
    )
