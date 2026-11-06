"""热门搜索自动排名、人工置顶、下线和屏蔽业务服务。"""

from __future__ import annotations

from datetime import timedelta
from typing import Any
from zoneinfo import ZoneInfo

from django.conf import settings
from django.db import transaction
from django.db.models import Max, Sum
from django.utils import timezone

from backend.accounts.models import User
from backend.common.errors import ERROR_MESSAGES, ErrorCode
from backend.common.exceptions import ApiError
from backend.common.search import (
    is_sensitive_search_keyword,
    validate_search_keyword,
)
from backend.discovery.models import SearchQueryStat, SearchTrendingKeyword


def _search_scores() -> dict[str, tuple[str, int]]:
    """按配置窗口和公式汇总非敏感关键词的自动热度分数。"""

    today = timezone.localtime(
        timezone.now(),
        ZoneInfo(settings.API_DISPLAY_TIMEZONE),
    ).date()
    window_days = max(1, settings.SEARCH_TRENDING_WINDOW_DAYS)
    start_date = today - timedelta(days=window_days - 1)
    rows = (
        SearchQueryStat.objects.filter(
            search_date__gte=start_date,
            search_date__lte=today,
        )
        .values("normalized_keyword")
        .annotate(
            total_count=Sum("search_count"),
            display_keyword=Max("display_keyword"),
        )
    )
    scores: dict[str, tuple[str, int]] = {}
    for row in rows:
        if is_sensitive_search_keyword(row["display_keyword"]):
            continue
        total_count = int(row["total_count"] or 0)
        if total_count < settings.SEARCH_TRENDING_MIN_SEARCH_COUNT:
            continue
        if settings.SEARCH_TRENDING_SCORE_MODE == "RECENCY_DECAY":
            daily_rows = SearchQueryStat.objects.filter(
                normalized_keyword=row["normalized_keyword"],
                search_date__gte=start_date,
                search_date__lte=today,
            ).values_list("search_date", "search_count")
            score = 0
            for search_date, count in daily_rows:
                age_days = (today - search_date).days
                decay = settings.SEARCH_TRENDING_RECENCY_DECAY_PERCENT / 100
                score += int(count * (decay**age_days))
        else:
            score = total_count
        scores[row["normalized_keyword"]] = (row["display_keyword"], score)
    return scores


def refresh_trending_keywords() -> list[SearchTrendingKeyword]:
    """合并自动搜索热度和人工配置，更新热榜分数与名次。"""

    scores = _search_scores()
    with transaction.atomic():
        SearchTrendingKeyword.objects.update(hot_score=0)
        for normalized_keyword, (display_keyword, score) in scores.items():
            SearchTrendingKeyword.objects.update_or_create(
                normalized_keyword=normalized_keyword,
                defaults={
                    "display_keyword": display_keyword,
                    "hot_score": score,
                },
            )
        SearchTrendingKeyword.objects.filter(is_manual=False).exclude(
            normalized_keyword__in=scores
        ).update(hot_score=0, rank=0)
        candidates = list(
            SearchTrendingKeyword.objects.filter(
                display_status=SearchTrendingKeyword.DisplayStatus.ACTIVE
            )
        )
        candidates.sort(
            key=lambda item: (
                0 if item.manual_priority else 1,
                item.manual_priority or 0,
                -item.hot_score,
                item.normalized_keyword,
            )
        )
        for rank, item in enumerate(candidates, start=1):
            item.rank = rank
            item.updated_at = timezone.now()
        SearchTrendingKeyword.objects.bulk_update(candidates, ["rank", "updated_at"])
        return candidates


def trending_keyword_payload(
    item: SearchTrendingKeyword,
    *,
    include_admin_fields: bool = False,
) -> dict[str, Any]:
    """生成公开或管理端热门搜索响应，公开响应默认不展示热度分数。"""

    payload = {
        "keyword": item.normalized_keyword,
        "display_text": item.display_keyword,
        "hot_type": "MANUAL" if item.is_manual else "AUTO",
        "hot_score": (
            item.hot_score if include_admin_fields or settings.SEARCH_TRENDING_SHOW_SCORE else None
        ),
        "rank": item.rank,
        "updated_at": item.updated_at,
    }
    if include_admin_fields:
        payload.update(
            {
                "trending_id": item.public_id,
                "display_status": item.display_status,
                "manual_priority": item.manual_priority,
                "version": item.version,
            }
        )
    return payload


def list_trending_keywords(
    *,
    limit: int,
    include_admin_fields: bool = False,
) -> dict[str, Any]:
    """返回按人工置顶优先、自动热度排序的热门搜索列表。"""

    candidates = refresh_trending_keywords()
    visible = [
        item
        for item in candidates
        if item.display_status == SearchTrendingKeyword.DisplayStatus.ACTIVE
    ][:limit]
    return {
        "items": [
            trending_keyword_payload(item, include_admin_fields=include_admin_fields)
            for item in visible
        ],
        "total": len(visible),
        "limit": limit,
    }


def list_admin_trending_keywords() -> dict[str, Any]:
    """返回包含自动词和人工控制项的管理员热门搜索配置列表。"""

    refresh_trending_keywords()
    items = SearchTrendingKeyword.objects.all().order_by("rank", "manual_priority", "id")
    return {
        "items": [trending_keyword_payload(item, include_admin_fields=True) for item in items],
        "total": items.count(),
    }


def create_manual_trending_keyword(
    *,
    admin: User,
    display_keyword: str,
    display_status: str = SearchTrendingKeyword.DisplayStatus.ACTIVE,
    manual_priority: int = 0,
) -> dict[str, Any]:
    """创建或接管人工热门词；相同自然键重复请求幂等返回，不同配置返回冲突。"""

    normalized, display = validate_search_keyword(display_keyword)
    if is_sensitive_search_keyword(display):
        raise _invalid("display_keyword", "敏感信息不允许进入热门搜索")
    with transaction.atomic():
        existing = (
            SearchTrendingKeyword.objects.select_for_update()
            .filter(normalized_keyword=normalized)
            .first()
        )
        desired = {
            "display_keyword": display,
            "display_status": display_status,
            "manual_priority": manual_priority,
        }
        if existing:
            if all(getattr(existing, key) == value for key, value in desired.items()):
                existing.is_manual = True
                existing.created_by_user_id = admin.id
                existing.save(update_fields=["is_manual", "created_by_user_id", "updated_at"])
                return {
                    **trending_keyword_payload(existing, include_admin_fields=True),
                    "reused": True,
                }
            raise _state_invalid("该规范化关键词已存在不同的人工配置")
        item = SearchTrendingKeyword.objects.create(
            normalized_keyword=normalized,
            display_keyword=display,
            is_manual=True,
            display_status=display_status,
            manual_priority=manual_priority,
            created_by_user_id=admin.id,
        )
        return {
            **trending_keyword_payload(item, include_admin_fields=True),
            "reused": False,
        }


def update_manual_trending_keyword(
    *,
    admin: User,
    trending_id: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    """按乐观锁版本更新人工热门词控制状态，不允许并发覆盖。"""

    if "display_keyword" in payload:
        normalized, display = validate_search_keyword(payload["display_keyword"])
        if is_sensitive_search_keyword(display):
            raise _invalid("display_keyword", "敏感信息不允许进入热门搜索")
    else:
        normalized, display = "", ""
    with transaction.atomic():
        item = (
            SearchTrendingKeyword.objects.select_for_update().filter(public_id=trending_id).first()
        )
        if item is None:
            raise _not_found()
        if item.version != payload["expected_version"]:
            raise ApiError(
                ErrorCode.SEARCH_VERSION_CONFLICT,
                ERROR_MESSAGES[ErrorCode.SEARCH_VERSION_CONFLICT],
                status_code=409,
                details={"current_version": item.version},
            )
        if normalized and normalized != item.normalized_keyword:
            if SearchTrendingKeyword.objects.filter(normalized_keyword=normalized).exists():
                raise _state_invalid("目标规范化关键词已存在")
            item.normalized_keyword = normalized
            item.display_keyword = display
        item.display_status = payload.get("display_status", item.display_status)
        item.manual_priority = payload.get("manual_priority", item.manual_priority)
        item.is_manual = True
        item.created_by_user_id = admin.id
        item.version += 1
        item.save()
        return {
            **trending_keyword_payload(item, include_admin_fields=True),
            "reused": False,
        }


def _invalid(field: str, message: str) -> ApiError:
    """构造搜索配置参数错误。"""

    return ApiError(
        ErrorCode.SEARCH_INVALID,
        ERROR_MESSAGES[ErrorCode.SEARCH_INVALID],
        status_code=400,
        details={field: message},
    )


def _state_invalid(message: str) -> ApiError:
    """构造热门搜索状态冲突错误。"""

    return ApiError(
        ErrorCode.SEARCH_TRENDING_STATE_INVALID,
        ERROR_MESSAGES[ErrorCode.SEARCH_TRENDING_STATE_INVALID],
        status_code=409,
        details={"reason": message},
    )


def _not_found() -> ApiError:
    """构造热门搜索配置不存在错误。"""

    return ApiError(
        ErrorCode.SEARCH_TRENDING_NOT_FOUND,
        ERROR_MESSAGES[ErrorCode.SEARCH_TRENDING_NOT_FOUND],
        status_code=404,
    )
