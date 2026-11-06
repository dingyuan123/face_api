"""资讯外部来源同步的 Celery 任务和可同步执行入口。"""

from __future__ import annotations

import logging
from typing import Any

from celery import shared_task
from django.utils import timezone

from backend.content.news_adapters import ExternalNewsItem, NewsProvider, RssNewsProvider
from backend.content.news_models import (
    NewsArticle,
    NewsArticleEvent,
    NewsCategory,
    NewsSource,
    NewsSyncRun,
)
from backend.content.news_services import _record_event, _safe_external_url

logger = logging.getLogger(__name__)


def _source_unique_key(source: NewsSource, item: ExternalNewsItem) -> str:
    return f"{source.code}:{item.external_id or item.canonical_url}"[:255]


def upsert_external_news_item(
    *,
    source: NewsSource,
    item: ExternalNewsItem,
) -> str:
    """按来源唯一键幂等写入外部资讯摘要；默认进入待审核状态。"""

    source_url = _safe_external_url(item.source_url, "source_url")
    canonical_url = _safe_external_url(item.canonical_url, "canonical_url") or source_url
    image_url = _safe_external_url(item.image_url, "cover_url")
    unique_key = _source_unique_key(source, item)
    defaults = {
        "title": item.title[:200],
        "summary": item.summary[:2000],
        "body": "",
        "source_url": source_url,
        "canonical_url": canonical_url,
        "cover_url": image_url,
        "author": item.author[:100],
        "source_name": item.source_name[:100] or source.name,
        "country_code": source.country_code,
        "language_code": source.language_code,
        "source_published_at": item.published_at,
    }
    article, created = NewsArticle.objects.get_or_create(
        source_unique_key=unique_key,
        defaults={
            **defaults,
            "source": source,
            "external_id": item.external_id[:255],
            "status": NewsArticle.Status.PENDING,
        },
    )
    if not created:
        changed_fields = []
        for field, value in defaults.items():
            if getattr(article, field) != value:
                setattr(article, field, value)
                changed_fields.append(field)
        if changed_fields:
            article.version += 1
            article.save(update_fields=[*changed_fields, "version", "updated_at"])
            _record_event(
                article=article,
                event_type=NewsArticleEvent.EventType.SYNCED,
                actor_user_id=None,
            )
            return "updated"
        return "skipped"
    general_category = NewsCategory.objects.filter(code="GENERAL", is_active=True).first()
    if general_category:
        article.category_links.create(category=general_category, position=0)
    _record_event(
        article=article,
        event_type=NewsArticleEvent.EventType.SYNCED,
        actor_user_id=None,
    )
    return "created"


def execute_news_sync(
    *,
    run_no: str,
    source_codes: list[str],
    keyword: str = "",
    country_code: str = "",
    language_code: str = "",
    limit: int = 20,
    provider: NewsProvider | None = None,
) -> dict[str, Any]:
    """执行资讯同步运行并记录来源级成功和失败数量。"""

    run = NewsSyncRun.objects.get(run_no=run_no)
    run.status = NewsSyncRun.Status.RUNNING
    run.started_at = timezone.now()
    run.save(update_fields=["status", "started_at"])
    provider = provider or RssNewsProvider()
    sources = NewsSource.objects.filter(enabled=True)
    if source_codes:
        sources = sources.filter(code__in=source_codes)
    if country_code:
        sources = sources.filter(country_code=country_code.upper())
    if language_code:
        sources = sources.filter(language_code=language_code)
    errors = []
    for source in sources:
        try:
            items = provider.fetch_latest(source, keyword=keyword, limit=limit)
            run.fetched_count += len(items)
            for item in items:
                if not item.title or not item.image_url or not item.source_url:
                    run.skipped_count += 1
                    continue
                result = upsert_external_news_item(source=source, item=item)
                if result == "created":
                    run.created_count += 1
                elif result == "updated":
                    run.updated_count += 1
                else:
                    run.skipped_count += 1
            source.last_synced_at = timezone.now()
            source.save(update_fields=["last_synced_at", "updated_at"])
        except Exception as exc:
            run.failed_count += 1
            errors.append(f"{source.code}: {type(exc).__name__}")
            logger.warning("资讯来源同步失败 source=%s error=%s", source.code, type(exc).__name__)
    run.status = (
        NewsSyncRun.Status.SUCCEEDED
        if not errors
        else NewsSyncRun.Status.PARTIAL
        if run.created_count or run.updated_count or run.skipped_count
        else NewsSyncRun.Status.FAILED
    )
    run.error_message = "\n".join(errors)[:4000]
    run.finished_at = timezone.now()
    run.save()
    return {
        "run_no": str(run.run_no),
        "status": run.status,
        "fetched_count": run.fetched_count,
        "created_count": run.created_count,
        "updated_count": run.updated_count,
        "skipped_count": run.skipped_count,
        "failed_count": run.failed_count,
    }


@shared_task(bind=True, max_retries=2)
def sync_news_sources_task(
    self,
    run_no: str,
    source_codes: list[str],
    keyword: str = "",
    country_code: str = "",
    language_code: str = "",
    limit: int = 20,
) -> dict[str, Any]:
    """异步执行外部资讯同步；运行记录本身负责幂等追踪。"""

    try:
        return execute_news_sync(
            run_no=run_no,
            source_codes=source_codes,
            keyword=keyword,
            country_code=country_code,
            language_code=language_code,
            limit=limit,
        )
    except Exception as exc:
        logger.exception("资讯同步任务异常 run_no=%s", run_no)
        raise self.retry(exc=exc) from exc
