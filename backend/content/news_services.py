"""资讯文章校验、管理发布、公开查询、收藏目标和分享链接业务服务。"""

from __future__ import annotations

import hashlib
import json
import uuid
from typing import Any
from urllib.parse import quote, urljoin, urlparse

from django.conf import settings
from django.db import IntegrityError, transaction
from django.db.models import Q, QuerySet
from django.http import HttpRequest
from django.utils import timezone

from backend.accounts.models import User
from backend.catalog.services import get_public_service_payload
from backend.common.context import current_trace_id
from backend.common.errors import ERROR_MESSAGES, ErrorCode
from backend.common.exceptions import ApiError
from backend.content.news_models import (
    NewsArticle,
    NewsArticleAttachment,
    NewsArticleCategory,
    NewsArticleEvent,
    NewsArticleMount,
    NewsCategory,
    NewsSource,
    NewsSyncRun,
)
from backend.media.models import MediaAsset
from backend.media.services import (
    get_available_media_for_purposes,
    get_media_payloads,
    mark_media_referenced,
)
from backend.providers.public_services import provider_public_payload


def _invalid(field: str, message: str) -> ApiError:
    """构造统一的资讯参数错误。"""

    return ApiError(
        ErrorCode.NEWS_INVALID,
        ERROR_MESSAGES[ErrorCode.NEWS_INVALID],
        status_code=400,
        details={field: message},
    )


def _not_found(field: str = "news_id", message: str = "资讯不存在") -> ApiError:
    """构造统一的资讯不存在错误。"""

    return ApiError(
        ErrorCode.NEWS_NOT_FOUND,
        ERROR_MESSAGES[ErrorCode.NEWS_NOT_FOUND],
        status_code=404,
        details={field: message},
    )


def _safe_external_url(value: str, field: str) -> str:
    """校验外部链接协议和主机，拒绝危险协议与空主机地址。"""

    normalized = value.strip()
    if not normalized:
        return ""
    parsed = urlparse(normalized)
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.netloc:
        raise _invalid(field, "只允许填写完整的 HTTP 或 HTTPS 地址")
    return normalized


def _normalize_idempotency_key(value: str | None) -> str | None:
    """规范化管理员创建资讯的幂等键。"""

    if value is None:
        return None
    normalized = value.strip()
    if not 1 <= len(normalized) <= 128:
        raise _invalid("idempotency_key", "Idempotency-Key 长度必须在 1 到 128 之间")
    return normalized


def _request_fingerprint(payload: dict[str, Any]) -> str:
    """计算创建请求一致性摘要，用于识别同幂等键的不同请求。"""

    serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _validate_media_ids(user: User, media_ids: list[str], field: str) -> list[str]:
    """校验资讯图片属于当前管理员且用途为资讯图片。"""

    normalized = [str(media_id).strip() for media_id in media_ids if str(media_id).strip()]
    if len(normalized) != len(set(normalized)):
        raise _invalid(field, "媒体 ID 不能重复")
    get_available_media_for_purposes(
        user=user,
        purposes={MediaAsset.Purpose.NEWS_IMAGE},
        media_ids=normalized,
    )
    return normalized


def _record_event(
    *,
    article: NewsArticle,
    event_type: str,
    actor_user_id: int | None,
    reason: str = "",
) -> None:
    """追加资讯审计事件，不覆盖历史操作记录。"""

    NewsArticleEvent.objects.create(
        article=article,
        event_type=event_type,
        actor_user_id=actor_user_id,
        reason=reason,
        trace_id=current_trace_id(),
    )


def _validate_category_codes(category_codes: list[str]) -> list[str]:
    """校验资讯类目配置并返回去重后的稳定代码。"""
    normalized = [code.strip().upper() for code in category_codes if code.strip()]
    if len(normalized) != len(set(normalized)):
        raise _invalid("category_codes", "资讯类目不能重复")
    categories = {
        category.code: category
        for category in NewsCategory.objects.filter(code__in=normalized, is_active=True)
    }
    if len(categories) != len(normalized):
        raise _invalid("category_codes", "资讯类目不存在或已停用")
    return normalized


def _replace_categories(article: NewsArticle, category_codes: list[str]) -> None:
    """替换资讯类目关联并保持输入顺序。"""

    normalized = _validate_category_codes(category_codes)
    categories = {
        category.code: category
        for category in NewsCategory.objects.filter(code__in=normalized, is_active=True)
    }
    NewsArticleCategory.objects.filter(article=article).delete()
    NewsArticleCategory.objects.bulk_create(
        [
            NewsArticleCategory(
                article=article,
                category=categories[code],
                position=position,
            )
            for position, code in enumerate(normalized)
        ]
    )


def _replace_attachments(
    article: NewsArticle,
    user: User,
    attachments: list[dict[str, Any]],
) -> None:
    """替换资讯图片、视频和链接附件快照。"""

    if len(attachments) > 20:
        raise _invalid("attachments", "资讯附件最多 20 个")
    normalized_items = []
    for position, item in enumerate(attachments):
        attachment_type = str(item.get("type", "IMAGE")).upper()
        if attachment_type not in NewsArticleAttachment.Type.values:
            raise _invalid("attachments", "附件类型不正确")
        media_id = str(item.get("media_id") or "").strip()
        url = _safe_external_url(str(item.get("url") or ""), "attachments")
        if attachment_type == "IMAGE" and not media_id and not url:
            raise _invalid("attachments", "图片附件必须提供 media_id 或安全 URL")
        if attachment_type in {"VIDEO", "LINK"} and not url:
            raise _invalid("attachments", "视频或链接附件必须提供安全 URL")
        normalized_items.append(
            {
                "type": attachment_type,
                "media_id": media_id,
                "url": url,
                "title": str(item.get("title") or "").strip()[:200],
                "position": position,
            }
        )
    media_ids = [item["media_id"] for item in normalized_items if item["media_id"]]
    _validate_media_ids(user, media_ids, "attachments")
    NewsArticleAttachment.objects.filter(article=article).delete()
    NewsArticleAttachment.objects.bulk_create(
        [NewsArticleAttachment(article=article, **item) for item in normalized_items]
    )


def _mount_snapshot(
    mount_type: str, item: dict[str, Any], request: HttpRequest | None
) -> dict[str, Any]:
    """读取服务者或服务公开摘要并生成可长期展示的卡片快照。"""

    target_public_id = str(item.get("target_public_id") or "").strip()
    title = str(item.get("title") or "").strip()
    subtitle = str(item.get("subtitle") or "").strip()
    cover_media_id = str(item.get("cover_media_id") or "").strip()
    cover_url = _safe_external_url(str(item.get("cover_url") or ""), "mounts")
    external_url = _safe_external_url(str(item.get("external_url") or ""), "mounts")
    if mount_type == NewsArticleMount.MountType.PROVIDER:
        if not target_public_id:
            raise _invalid("mounts", "服务者卡片必须提供 target_public_id")
        provider_payload = provider_public_payload(
            provider_public_id=target_public_id,
            request=request,
        )["provider"]
        title = title or provider_payload.get("nickname") or "服务者"
        subtitle = subtitle or provider_payload.get("signature") or ""
        avatar_media = provider_payload.get("avatar_media") or {}
        cover_media_id = cover_media_id or str(avatar_media.get("media_id") or "")
    elif mount_type == NewsArticleMount.MountType.SERVICE:
        if not target_public_id:
            raise _invalid("mounts", "服务卡片必须提供 target_public_id")
        service_payload = get_public_service_payload(target_public_id, request)
        title = title or service_payload.get("title") or "服务"
        subtitle = subtitle or service_payload.get("introduction") or ""
        cover_media = service_payload.get("cover_media") or {}
        cover_media_id = cover_media_id or str(cover_media.get("media_id") or "")
    elif mount_type == NewsArticleMount.MountType.MERCHANT:
        title = title or str(item.get("merchant_name") or "").strip() or "商家"
    elif mount_type == NewsArticleMount.MountType.LINK:
        if not external_url:
            raise _invalid("mounts", "链接卡片必须提供 external_url")
        title = title or "相关链接"
    if not title:
        raise _invalid("mounts", "卡片标题不能为空")
    return {
        "mount_type": mount_type,
        "target_public_id": target_public_id or None,
        "title": title[:200],
        "subtitle": subtitle[:300],
        "cover_media_id": cover_media_id,
        "cover_url": cover_url,
        "external_url": external_url,
        "merchant_name": str(item.get("merchant_name") or "").strip()[:100],
        "merchant_address": str(item.get("merchant_address") or "").strip()[:255],
        "merchant_city_code": str(item.get("merchant_city_code") or "").strip()[:32],
        "payload_snapshot": {
            "target_public_id": target_public_id or None,
            "title": title[:200],
            "subtitle": subtitle[:300],
        },
    }


def _replace_mounts(
    article: NewsArticle,
    user: User,
    mounts: list[dict[str, Any]],
    request: HttpRequest | None,
) -> None:
    """替换资讯关联卡片并保存目标下架后仍可展示的快照。"""

    if len(mounts) > 10:
        raise _invalid("mounts", "资讯挂载卡片最多 10 个")
    snapshots = []
    for position, item in enumerate(mounts):
        mount_type = str(item.get("mount_type") or "").upper()
        if mount_type not in NewsArticleMount.MountType.values:
            raise _invalid("mounts", "挂载卡片类型不正确")
        snapshot = _mount_snapshot(mount_type, item, request)
        snapshot["position"] = position
        snapshots.append(snapshot)
    media_ids = [snapshot["cover_media_id"] for snapshot in snapshots if snapshot["cover_media_id"]]
    if media_ids:
        _validate_media_ids(user, media_ids, "mounts")
    NewsArticleMount.objects.filter(article=article).delete()
    NewsArticleMount.objects.bulk_create(
        [NewsArticleMount(article=article, **snapshot) for snapshot in snapshots]
    )


def _validate_payload(
    user: User, payload: dict[str, Any], request: HttpRequest | None
) -> dict[str, Any]:
    """规范化管理员资讯输入并校验关联目标。"""

    title = str(payload.get("title") or "").strip()
    summary = str(payload.get("summary") or "").strip()
    if not 1 <= len(title) <= 200:
        raise _invalid("title", "资讯标题必须为 1 到 200 个字符")
    if not 1 <= len(summary) <= 2000:
        raise _invalid("summary", "资讯摘要必须为 1 到 2000 个字符")
    body = str(payload.get("body") or "").strip()
    if len(body) > 100_000:
        raise _invalid("body", "资讯正文不能超过 100000 个字符")
    category_codes = [str(code) for code in payload.get("category_codes", [])]
    if not category_codes:
        raise _invalid("category_codes", "至少选择一个资讯类目")
    cover_media_ids = _validate_media_ids(
        user,
        [str(payload.get("cover_media_id") or "")],
        "cover_media_id",
    )
    normalized = {
        "title": title,
        "summary": summary,
        "body": body,
        "source_url": _safe_external_url(str(payload.get("source_url") or ""), "source_url"),
        "canonical_url": _safe_external_url(
            str(payload.get("canonical_url") or payload.get("source_url") or ""),
            "canonical_url",
        ),
        "cover_url": _safe_external_url(str(payload.get("cover_url") or ""), "cover_url"),
        "cover_media_id": cover_media_ids[0] if cover_media_ids else "",
        "author": str(payload.get("author") or "").strip()[:100],
        "source_name": str(payload.get("source_name") or "").strip()[:100],
        "country_code": str(payload.get("country_code") or "").strip().upper()[:8],
        "city_code": str(payload.get("city_code") or "").strip().upper()[:32],
        "language_code": str(payload.get("language_code") or "").strip()[:16],
        "category_codes": category_codes,
        "attachments": list(payload.get("attachments") or []),
        "mounts": list(payload.get("mounts") or []),
        "is_featured": bool(payload.get("is_featured", False)),
        "allow_recommend": bool(payload.get("allow_recommend", True)),
    }
    return normalized


def _article_queryset() -> QuerySet[NewsArticle]:
    return (
        NewsArticle.objects.select_related("source")
        .prefetch_related(
            "category_links__category",
            "attachments",
            "mounts",
        )
        .filter(deleted_at__isnull=True)
    )


def _category_codes(article: NewsArticle) -> list[str]:
    return [link.category.code for link in article.category_links.all()]


def _attachment_payload(
    attachment: NewsArticleAttachment,
    media_payloads: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    return {
        "type": attachment.type,
        "media": media_payloads.get(str(attachment.media_id)) if attachment.media_id else None,
        "url": attachment.url,
        "title": attachment.title,
        "position": attachment.position,
    }


def _mount_payload(
    mount: NewsArticleMount,
    media_payloads: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    return {
        "mount_type": mount.mount_type,
        "target_public_id": str(mount.target_public_id) if mount.target_public_id else None,
        "title": mount.title,
        "subtitle": mount.subtitle,
        "cover_media": media_payloads.get(str(mount.cover_media_id))
        if mount.cover_media_id
        else None,
        "cover_url": mount.cover_url,
        "external_url": mount.external_url,
        "merchant": {
            "name": mount.merchant_name,
            "address": mount.merchant_address,
            "city_code": mount.merchant_city_code,
        }
        if mount.merchant_name or mount.merchant_address
        else None,
        "position": mount.position,
    }


def news_payload(
    article: NewsArticle,
    request: HttpRequest | None = None,
) -> dict[str, Any]:
    """返回资讯文章安全摘要，不暴露内部主键和后台用户 ID。"""

    media_ids = [article.cover_media_id]
    media_ids.extend(item.media_id for item in article.attachments.all())
    media_ids.extend(item.cover_media_id for item in article.mounts.all())
    media_payloads = {
        payload["media_id"]: payload
        for payload in get_media_payloads(
            [media_id for media_id in media_ids if media_id],
            request,
        )
    }
    return {
        "news_id": str(article.public_id),
        "title": article.title,
        "summary": article.summary,
        "body": article.body,
        "cover_media": media_payloads.get(str(article.cover_media_id))
        if article.cover_media_id
        else None,
        "cover_url": article.cover_url,
        "author": article.author,
        "source_name": article.source_name,
        "source_url": article.source_url,
        "country_code": article.country_code,
        "city_code": article.city_code,
        "language_code": article.language_code,
        "category_codes": _category_codes(article),
        "attachments": [
            _attachment_payload(item, media_payloads) for item in article.attachments.all()
        ],
        "mounts": [_mount_payload(item, media_payloads) for item in article.mounts.all()],
        "status": article.status,
        "is_featured": article.is_featured,
        "allow_recommend": article.allow_recommend,
        "view_count": article.view_count,
        "version": article.version,
        "source_published_at": article.source_published_at,
        "published_at": article.published_at,
        "created_at": article.created_at,
        "updated_at": article.updated_at,
    }


def news_category_payloads() -> list[dict[str, Any]]:
    """返回启用的资讯类目配置。"""

    return [
        {
            "code": item.code,
            "name": item.name,
            "sort_order": item.sort_order,
        }
        for item in NewsCategory.objects.filter(is_active=True)
    ]


def create_news_article(
    *,
    user: User,
    payload: dict[str, Any],
    request: HttpRequest | None = None,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    """管理员创建资讯草稿，支持幂等重放并写入关联快照。"""

    normalized_key = _normalize_idempotency_key(idempotency_key)
    normalized = _validate_payload(user, payload, request)
    fingerprint = _request_fingerprint(normalized)
    if normalized_key:
        existing = NewsArticle.objects.filter(
            created_by_user_id=user.id,
            idempotency_key=normalized_key,
        ).first()
        if existing:
            if existing.request_fingerprint != fingerprint:
                raise _invalid("idempotency_key", "幂等请求与原请求不一致")
            return news_payload(existing, request)
    try:
        with transaction.atomic():
            article = NewsArticle.objects.create(
                title=normalized["title"],
                summary=normalized["summary"],
                body=normalized["body"],
                source_url=normalized["source_url"],
                canonical_url=normalized["canonical_url"],
                source_unique_key=f"manual:{uuid.uuid4()}",
                cover_url=normalized["cover_url"],
                cover_media_id=normalized["cover_media_id"],
                author=normalized["author"],
                source_name=normalized["source_name"],
                country_code=normalized["country_code"],
                city_code=normalized["city_code"],
                language_code=normalized["language_code"],
                is_featured=normalized["is_featured"],
                allow_recommend=normalized["allow_recommend"],
                status=NewsArticle.Status.DRAFT,
                created_by_user_id=user.id,
                idempotency_key=normalized_key,
                request_fingerprint=fingerprint,
            )
            _replace_categories(article, normalized["category_codes"])
            _replace_attachments(article, user, normalized["attachments"])
            _replace_mounts(article, user, normalized["mounts"], request)
            mark_media_referenced(
                [
                    media_id
                    for media_id in [article.cover_media_id]
                    + [item.media_id for item in article.attachments.all()]
                    + [item.cover_media_id for item in article.mounts.all()]
                    if media_id
                ]
            )
            _record_event(
                article=article,
                event_type=NewsArticleEvent.EventType.CREATED,
                actor_user_id=user.id,
            )
            return news_payload(article, request)
    except IntegrityError as exc:
        raise _invalid("idempotency_key", "资讯创建并发冲突，请使用相同请求重试") from exc


def update_news_article(
    *,
    user: User,
    news_id: str,
    payload: dict[str, Any],
    expected_version: int,
    request: HttpRequest | None = None,
) -> dict[str, Any]:
    """管理员编辑草稿或被拒绝资讯，使用版本号防止并发覆盖。"""

    article = _article_queryset().filter(public_id=news_id).first()
    if article is None:
        raise _not_found()
    if article.status not in {NewsArticle.Status.DRAFT, NewsArticle.Status.REJECTED}:
        raise ApiError(
            ErrorCode.NEWS_STATE_INVALID,
            ERROR_MESSAGES[ErrorCode.NEWS_STATE_INVALID],
            status_code=409,
            details={"status": "只有草稿或审核拒绝的资讯可以编辑"},
        )
    if article.version != expected_version:
        raise ApiError(
            ErrorCode.NEWS_VERSION_CONFLICT,
            ERROR_MESSAGES[ErrorCode.NEWS_VERSION_CONFLICT],
            status_code=409,
        )
    normalized = _validate_payload(user, payload, request)
    with transaction.atomic():
        locked = NewsArticle.objects.select_for_update().get(pk=article.pk)
        if locked.version != expected_version:
            raise ApiError(
                ErrorCode.NEWS_VERSION_CONFLICT,
                ERROR_MESSAGES[ErrorCode.NEWS_VERSION_CONFLICT],
                status_code=409,
            )
        for field in (
            "title",
            "summary",
            "body",
            "source_url",
            "canonical_url",
            "cover_url",
            "cover_media_id",
            "author",
            "source_name",
            "country_code",
            "city_code",
            "language_code",
            "is_featured",
            "allow_recommend",
        ):
            setattr(locked, field, normalized[field])
        locked.reject_reason = ""
        locked.version += 1
        locked.save()
        _replace_categories(locked, normalized["category_codes"])
        _replace_attachments(locked, user, normalized["attachments"])
        _replace_mounts(locked, user, normalized["mounts"], request)
        _record_event(
            article=locked,
            event_type=NewsArticleEvent.EventType.UPDATED,
            actor_user_id=user.id,
        )
        return news_payload(locked, request)


def review_news_article(
    *,
    user: User,
    news_id: str,
    approve: bool,
    expected_version: int,
    reason: str = "",
    request: HttpRequest | None = None,
) -> dict[str, Any]:
    """管理员发布或拒绝资讯；发布是幂等语义，拒绝必须填写原因。"""

    article = _article_queryset().filter(public_id=news_id).first()
    if article is None:
        raise _not_found()
    if approve and article.status == NewsArticle.Status.PUBLISHED:
        return news_payload(article, request)
    if article.status not in {
        NewsArticle.Status.DRAFT,
        NewsArticle.Status.PENDING,
        NewsArticle.Status.REJECTED,
    }:
        raise ApiError(
            ErrorCode.NEWS_STATE_INVALID,
            ERROR_MESSAGES[ErrorCode.NEWS_STATE_INVALID],
            status_code=409,
        )
    normalized_reason = reason.strip()
    if not approve and not normalized_reason:
        raise _invalid("reason", "拒绝资讯时必须填写原因")
    with transaction.atomic():
        locked = NewsArticle.objects.select_for_update().get(pk=article.pk)
        if locked.version != expected_version:
            raise ApiError(
                ErrorCode.NEWS_VERSION_CONFLICT,
                ERROR_MESSAGES[ErrorCode.NEWS_VERSION_CONFLICT],
                status_code=409,
            )
        if approve:
            locked.status = NewsArticle.Status.PUBLISHED
            locked.published_at = locked.published_at or timezone.now()
            locked.reject_reason = ""
            event_type = NewsArticleEvent.EventType.PUBLISHED
        else:
            locked.status = NewsArticle.Status.REJECTED
            locked.reject_reason = normalized_reason
            event_type = NewsArticleEvent.EventType.REJECTED
        locked.version += 1
        locked.save()
        _record_event(
            article=locked,
            event_type=event_type,
            actor_user_id=user.id,
            reason=normalized_reason,
        )
        return news_payload(locked, request)


def delete_news_article(
    *,
    user: User,
    news_id: str,
    expected_version: int,
    reason: str = "",
) -> dict[str, Any]:
    """管理员逻辑删除资讯并保留审计记录。"""

    article = _article_queryset().filter(public_id=news_id).first()
    if article is None:
        raise _not_found()
    if article.version != expected_version:
        raise ApiError(
            ErrorCode.NEWS_VERSION_CONFLICT,
            ERROR_MESSAGES[ErrorCode.NEWS_VERSION_CONFLICT],
            status_code=409,
        )
    with transaction.atomic():
        locked = NewsArticle.objects.select_for_update().get(pk=article.pk)
        locked.status = NewsArticle.Status.DELETED
        locked.deleted_at = timezone.now()
        locked.version += 1
        locked.save()
        _record_event(
            article=locked,
            event_type=NewsArticleEvent.EventType.DELETED,
            actor_user_id=user.id,
            reason=reason.strip(),
        )
    return {"news_id": str(article.public_id), "deleted": True}


def get_news_article(news_id: str, request: HttpRequest | None = None) -> dict[str, Any]:
    """返回已发布公开资讯详情并增加浏览次数。"""

    article = (
        _article_queryset()
        .filter(
            public_id=news_id,
            status=NewsArticle.Status.PUBLISHED,
        )
        .first()
    )
    if article is None:
        raise _not_found()
    NewsArticle.objects.filter(pk=article.pk).update(view_count=article.view_count + 1)
    article.view_count += 1
    return news_payload(article, request)


def list_public_news(
    *,
    category_code: str | None = None,
    country_code: str | None = None,
    language_code: str | None = None,
    keyword: str | None = None,
    featured: bool | None = None,
    page: int = 1,
    page_size: int = 20,
    request: HttpRequest | None = None,
) -> dict[str, Any]:
    """返回 App 只读资讯列表，支持类目、地区、语言和标题摘要关键词筛选。"""

    queryset = _article_queryset().filter(status=NewsArticle.Status.PUBLISHED)
    if category_code:
        queryset = queryset.filter(category_links__category__code=category_code.upper())
    if country_code:
        queryset = queryset.filter(country_code=country_code.upper())
    if language_code:
        queryset = queryset.filter(language_code=language_code)
    if keyword:
        search = keyword.strip()
        queryset = queryset.filter(
            Q(title__icontains=search)
            | Q(summary__icontains=search)
            | Q(source_name__icontains=search)
            | Q(category_links__category__name__icontains=search)
            | Q(category_links__category__code__icontains=search)
        )
    if featured is not None:
        queryset = queryset.filter(is_featured=featured)
    total = queryset.distinct().count()
    start = max(0, (page - 1) * page_size)
    articles = list(queryset.distinct().order_by("-published_at", "-id")[start : start + page_size])
    return {
        "items": [news_payload(item, request) for item in articles],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


def list_admin_news(
    *,
    status: str | None = None,
    keyword: str | None = None,
    page: int = 1,
    page_size: int = 20,
    request: HttpRequest | None = None,
) -> dict[str, Any]:
    """返回管理员资讯管理列表。"""

    queryset = _article_queryset()
    if status:
        if status not in NewsArticle.Status.values:
            raise _invalid("status", "资讯状态不存在")
        queryset = queryset.filter(status=status)
    if keyword:
        queryset = queryset.filter(Q(title__icontains=keyword) | Q(summary__icontains=keyword))
    total = queryset.count()
    start = max(0, (page - 1) * page_size)
    return {
        "items": [
            news_payload(item, request)
            for item in queryset.order_by("-updated_at", "-id")[start : start + page_size]
        ],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


def get_admin_news_article(news_id: str, request: HttpRequest | None = None) -> dict[str, Any]:
    """返回管理员资讯详情。"""

    article = _article_queryset().filter(public_id=news_id).first()
    if article is None:
        raise _not_found()
    return news_payload(article, request)


def news_share_payload(news_id: str, request: HttpRequest | None = None) -> dict[str, Any]:
    """生成不含登录身份和令牌的资讯分享链接及分享卡片。"""

    article = (
        _article_queryset()
        .filter(
            public_id=news_id,
            status=NewsArticle.Status.PUBLISHED,
        )
        .first()
    )
    if article is None:
        raise _not_found()
    base_url = (
        _safe_external_url(
            str(settings.PUBLIC_SHARE_BASE_URL),
            "PUBLIC_SHARE_BASE_URL",
        ).rstrip("/")
        + "/"
    )
    share_url = urljoin(base_url, f"news/{quote(str(article.public_id))}")
    cover_url = article.cover_url
    if article.cover_media_id:
        media_payloads = get_media_payloads([article.cover_media_id], request)
        if media_payloads:
            cover_url = media_payloads[0].get("display_url") or cover_url
    return {
        "share_url": share_url,
        "share_title": article.title,
        "share_summary": article.summary,
        "share_image_url": cover_url,
    }


def favorite_news_exists(news_id: str) -> bool:
    """校验资讯收藏目标是否为已发布公开资讯。"""

    return NewsArticle.objects.filter(
        public_id=news_id,
        status=NewsArticle.Status.PUBLISHED,
        deleted_at__isnull=True,
    ).exists()


def news_source_payload(source: NewsSource) -> dict[str, Any]:
    """返回外部资讯来源配置摘要。"""

    return {
        "code": source.code,
        "name": source.name,
        "source_type": source.source_type,
        "feed_url": source.feed_url,
        "homepage_url": source.homepage_url,
        "country_code": source.country_code,
        "language_code": source.language_code,
        "enabled": source.enabled,
        "fetch_interval_minutes": source.fetch_interval_minutes,
        "attribution": source.attribution,
        "license_note": source.license_note,
        "last_synced_at": source.last_synced_at,
    }


def list_news_sources() -> list[dict[str, Any]]:
    """返回管理员配置的外部资讯来源。"""

    return [news_source_payload(item) for item in NewsSource.objects.all()]


def _source_payload_validation(payload: dict[str, Any]) -> dict[str, Any]:
    """校验外部资讯来源配置。"""

    code = str(payload.get("code") or "").strip().upper()
    name = str(payload.get("name") or "").strip()
    if not code or len(code) > 64:
        raise _invalid("code", "来源代码必须为 1 到 64 个字符")
    if not name or len(name) > 100:
        raise _invalid("name", "来源名称必须为 1 到 100 个字符")
    source_type = str(payload.get("source_type") or "RSS").upper()
    if source_type not in NewsSource.SourceType.values:
        raise _invalid("source_type", "来源类型不正确")
    feed_url = _safe_external_url(str(payload.get("feed_url") or ""), "feed_url")
    if source_type == NewsSource.SourceType.RSS and not feed_url:
        raise _invalid("feed_url", "RSS 来源必须提供订阅地址")
    fetch_interval_minutes = int(payload.get("fetch_interval_minutes") or 60)
    if not 5 <= fetch_interval_minutes <= 1440:
        raise _invalid("fetch_interval_minutes", "同步间隔必须为 5 到 1440 分钟")
    return {
        "code": code,
        "name": name,
        "source_type": source_type,
        "feed_url": feed_url,
        "homepage_url": _safe_external_url(
            str(payload.get("homepage_url") or ""),
            "homepage_url",
        ),
        "country_code": str(payload.get("country_code") or "").strip().upper()[:8],
        "language_code": str(payload.get("language_code") or "").strip()[:16],
        "enabled": bool(payload.get("enabled", True)),
        "fetch_interval_minutes": fetch_interval_minutes,
        "attribution": str(payload.get("attribution") or "").strip()[:255],
        "license_note": str(payload.get("license_note") or "").strip(),
    }


def create_news_source(*, payload: dict[str, Any]) -> dict[str, Any]:
    """管理员创建外部资讯来源。"""

    normalized = _source_payload_validation(payload)
    if NewsSource.objects.filter(code=normalized["code"]).exists():
        raise _invalid("code", "来源代码已存在")
    source = NewsSource.objects.create(**normalized)
    return news_source_payload(source)


def update_news_source(*, source_code: str, payload: dict[str, Any]) -> dict[str, Any]:
    """管理员更新外部资讯来源，不允许修改稳定来源代码。"""

    source = NewsSource.objects.filter(code=source_code.upper()).first()
    if source is None:
        raise _not_found("source_code", "资讯来源不存在")
    normalized = _source_payload_validation({**payload, "code": source.code})
    for field, value in normalized.items():
        setattr(source, field, value)
    source.save()
    return news_source_payload(source)


def news_sync_run_payload(run: NewsSyncRun) -> dict[str, Any]:
    """返回资讯同步任务执行结果。"""

    return {
        "run_no": str(run.run_no),
        "status": run.status,
        "source_codes": run.source_codes,
        "filters": run.filters,
        "fetched_count": run.fetched_count,
        "created_count": run.created_count,
        "updated_count": run.updated_count,
        "skipped_count": run.skipped_count,
        "failed_count": run.failed_count,
        "error_message": run.error_message,
        "started_at": run.started_at,
        "finished_at": run.finished_at,
        "created_at": run.created_at,
    }


def create_news_sync_run(
    *,
    user: User,
    source_codes: list[str],
    filters: dict[str, Any],
) -> dict[str, Any]:
    """创建并触发一键资讯同步；开发环境可配置为同步执行。"""

    normalized_codes = [str(code).strip().upper() for code in source_codes if str(code).strip()]
    keyword = str(filters.get("keyword") or "").strip()[:100]
    country_code = str(filters.get("country_code") or "").strip().upper()[:8]
    language_code = str(filters.get("language_code") or "").strip()[:16]
    limit = max(
        1,
        min(
            int(filters.get("limit") or settings.NEWS_FETCH_MAX_ITEMS),
            settings.NEWS_FETCH_MAX_ITEMS,
        ),
    )
    run = NewsSyncRun.objects.create(
        requested_by_user_id=user.id,
        source_codes=normalized_codes,
        filters={
            "keyword": keyword,
            "country_code": country_code,
            "language_code": language_code,
            "limit": limit,
        },
    )
    task_arguments = {
        "run_no": str(run.run_no),
        "source_codes": normalized_codes,
        "keyword": keyword,
        "country_code": country_code,
        "language_code": language_code,
        "limit": limit,
    }
    if settings.NEWS_SYNC_ASYNC:
        from backend.content.tasks import sync_news_sources_task

        try:
            sync_news_sources_task.delay(**task_arguments)
        except Exception as exc:
            run.status = NewsSyncRun.Status.FAILED
            run.error_message = "资讯同步任务投递失败"
            run.finished_at = timezone.now()
            run.save()
            raise ApiError(
                ErrorCode.NEWS_SYNC_UNAVAILABLE,
                ERROR_MESSAGES[ErrorCode.NEWS_SYNC_UNAVAILABLE],
                status_code=503,
            ) from exc
    else:
        from backend.content.tasks import execute_news_sync

        execute_news_sync(**task_arguments)
        run.refresh_from_db()
    return news_sync_run_payload(run)


def get_news_sync_run(run_no: str) -> dict[str, Any]:
    """查询资讯同步任务执行状态。"""

    run = NewsSyncRun.objects.filter(run_no=run_no).first()
    if run is None:
        raise _not_found("run_no", "资讯同步任务不存在")
    return news_sync_run_payload(run)
