from __future__ import annotations

import uuid
from datetime import timedelta

import pytest
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from backend.accounts.models import AuthToken, User
from backend.accounts.services import _token_raw, hash_token
from backend.content.news_adapters import ExternalNewsItem, _plain_text
from backend.content.news_models import (
    NewsArticle,
    NewsSource,
    NewsSyncRun,
)
from backend.content.tasks import execute_news_sync

pytestmark = pytest.mark.django_db


def create_user(phone_hash: str, *, staff: bool = False) -> User:
    return User.objects.create(
        phone_hash=phone_hash,
        phone_masked="138****8000",
        is_staff=staff,
        initial_role_selected=True,
        primary_role=User.InitialRole.USER,
    )


def auth_headers(user: User) -> dict[str, str]:
    token_public_id = uuid.uuid4()
    token_id = _token_raw(AuthToken.TokenType.ACCESS, token_public_id)
    AuthToken.objects.create(
        public_id=token_public_id,
        user=user,
        token_type=AuthToken.TokenType.ACCESS,
        token_hash=hash_token(token_id),
        expires_at=timezone.now() + timedelta(hours=1),
    )
    return {"HTTP_AUTHORIZATION": f"Bearer {token_id}"}


def create_news_payload() -> dict:
    return {
        "title": "本地测试资讯",
        "summary": "这是一条用于验证资讯列表和分享的摘要。",
        "category_codes": ["GENERAL"],
        "source_name": "见面聊编辑部",
        "is_featured": True,
        "mounts": [
            {
                "mount_type": "LINK",
                "title": "相关链接",
                "external_url": "https://example.com/article",
            }
        ],
    }


def test_default_news_sources_require_reliable_cover_support() -> None:
    """默认同步来源应优先使用能够稳定提供文章封面的 RSS。"""

    google_source = NewsSource.objects.get(code="GOOGLE_NEWS_ZH")
    bbc_source = NewsSource.objects.get(code="BBC_WORLD")
    guardian_source = NewsSource.objects.get(code="GUARDIAN_WORLD")
    al_jazeera_source = NewsSource.objects.get(code="AL_JAZEERA")

    assert google_source.feed_url == "https://news.google.com/rss?hl=zh-CN&gl=CN&ceid=CN:zh-Hans"
    assert google_source.enabled is False
    assert bbc_source.enabled is True
    assert guardian_source.enabled is True
    assert al_jazeera_source.enabled is False


def test_external_summary_is_normalized_to_plain_text() -> None:
    """外部 RSS 摘要应移除 HTML、脚本和多余空白后再保存。"""

    summary = _plain_text(
        "<p>第一条摘要</p><script>alert('x')</script><p>第二条摘要&nbsp;&nbsp;内容</p>"
    )

    assert summary == "第一条摘要 第二条摘要 内容"


def test_sync_skips_external_items_without_cover() -> None:
    """同步资讯必须至少具有标题、封面和原文链接，否则跳过创建。"""

    NewsSource.objects.create(
        code="TEST_COVER_RSS",
        name="测试封面 RSS",
        feed_url="https://example.com/rss",
    )
    run = NewsSyncRun.objects.create(source_codes=["TEST_COVER_RSS"])
    fixed_published_at = timezone.now()

    class FakeProvider:
        def fetch_latest(self, source, *, keyword="", limit=20):
            return [
                ExternalNewsItem(
                    external_id="with-cover",
                    title="有封面资讯",
                    summary="正常摘要",
                    source_url="https://example.com/news/1",
                    canonical_url="https://example.com/news/1",
                    image_url="https://example.com/cover.jpg",
                    author="作者",
                    source_name=source.name,
                    published_at=fixed_published_at,
                ),
                ExternalNewsItem(
                    external_id="without-cover",
                    title="无封面资讯",
                    summary="不应创建",
                    source_url="https://example.com/news/2",
                    canonical_url="https://example.com/news/2",
                    image_url="",
                    author="作者",
                    source_name=source.name,
                    published_at=fixed_published_at,
                ),
            ]

    result = execute_news_sync(
        run_no=str(run.run_no),
        source_codes=["TEST_COVER_RSS"],
        provider=FakeProvider(),
    )

    assert result["fetched_count"] == 2
    assert result["created_count"] == 1
    assert result["skipped_count"] == 1
    assert NewsArticle.objects.filter(source_unique_key="TEST_COVER_RSS:with-cover").exists()
    assert not NewsArticle.objects.filter(source_unique_key="TEST_COVER_RSS:without-cover").exists()


def test_admin_news_crud_publish_reject_and_share_are_safe() -> None:
    client = APIClient()
    admin = create_user("news-admin", staff=True)
    create_user("news-viewer")

    categories = client.get(reverse("v1:news-categories"))
    assert categories.status_code == 200
    assert categories.json()["data"][0]["code"] == "GENERAL"

    created = client.post(
        reverse("v1:admin-news"),
        create_news_payload(),
        format="json",
        HTTP_IDEMPOTENCY_KEY="news-create-001",
        **auth_headers(admin),
    )
    replayed = client.post(
        reverse("v1:admin-news"),
        create_news_payload(),
        format="json",
        HTTP_IDEMPOTENCY_KEY="news-create-001",
        **auth_headers(admin),
    )
    assert created.status_code == replayed.status_code == 201
    assert created.json()["data"]["news_id"] == replayed.json()["data"]["news_id"]
    assert created.json()["data"]["status"] == "DRAFT"
    news_id = created.json()["data"]["news_id"]

    public_before_publish = client.get(reverse("v1:public-news-detail", args=[news_id]))
    assert public_before_publish.status_code == 404
    published = client.post(
        reverse("v1:admin-news-publish", args=[news_id]),
        {"expected_version": created.json()["data"]["version"]},
        format="json",
        **auth_headers(admin),
    )
    assert published.status_code == 200
    assert published.json()["data"]["status"] == "PUBLISHED"
    assert published.json()["data"]["mounts"][0]["mount_type"] == "LINK"

    listed = client.get(reverse("v1:public-news"), {"category_code": "GENERAL"})
    detail = client.get(reverse("v1:public-news-detail", args=[news_id]))
    shared = client.get(reverse("v1:news-share", args=[news_id]))
    assert listed.status_code == detail.status_code == shared.status_code == 200
    assert listed.json()["data"]["total"] == 1
    assert detail.json()["data"]["title"] == "本地测试资讯"
    assert shared.json()["data"]["share_url"].endswith(f"/news/{news_id}")
    assert "Authorization" not in shared.json()["data"]["share_url"]

    stale_update = client.patch(
        reverse("v1:admin-news-detail", args=[news_id]),
        {**create_news_payload(), "expected_version": 1},
        format="json",
        **auth_headers(admin),
    )
    assert stale_update.status_code == 409

    published_reject = client.post(
        reverse("v1:admin-news-reject", args=[news_id]),
        {"expected_version": published.json()["data"]["version"], "reason": "来源不明确"},
        format="json",
        **auth_headers(admin),
    )
    assert published_reject.status_code == 409

    rejected_created = client.post(
        reverse("v1:admin-news"),
        create_news_payload(),
        format="json",
        **auth_headers(admin),
    )
    rejected = client.post(
        reverse("v1:admin-news-reject", args=[rejected_created.json()["data"]["news_id"]]),
        {
            "expected_version": rejected_created.json()["data"]["version"],
            "reason": "来源不明确",
        },
        format="json",
        **auth_headers(admin),
    )
    assert rejected.status_code == 200
    assert rejected.json()["data"]["status"] == "REJECTED"


def test_news_favorite_requires_published_target_and_sync_is_idempotent() -> None:
    client = APIClient()
    admin = create_user("news-favorite-admin", staff=True)
    viewer = create_user("news-favorite-viewer")
    created = client.post(
        reverse("v1:admin-news"),
        create_news_payload(),
        format="json",
        **auth_headers(admin),
    )
    news_id = created.json()["data"]["news_id"]
    unpublished_favorite = client.post(
        reverse("v1:favorites"),
        {"target_type": "NEWS", "target_id": news_id},
        format="json",
        **auth_headers(viewer),
    )
    assert unpublished_favorite.status_code == 400

    client.post(
        reverse("v1:admin-news-publish", args=[news_id]),
        {"expected_version": created.json()["data"]["version"]},
        format="json",
        **auth_headers(admin),
    )
    favorite = client.post(
        reverse("v1:favorites"),
        {"target_type": "NEWS", "target_id": news_id},
        format="json",
        **auth_headers(viewer),
    )
    repeated = client.post(
        reverse("v1:favorites"),
        {"target_type": "NEWS", "target_id": news_id},
        format="json",
        **auth_headers(viewer),
    )
    assert favorite.status_code == repeated.status_code == 200
    assert favorite.json()["data"]["is_favorited"] is True

    NewsSource.objects.create(
        code="TEST_RSS",
        name="测试 RSS",
        feed_url="https://example.com/rss",
    )
    run = NewsSyncRun.objects.create(source_codes=["TEST_RSS"])

    fixed_published_at = timezone.now()

    class FakeProvider:
        def fetch_latest(self, source, *, keyword="", limit=20):
            return [
                ExternalNewsItem(
                    external_id="external-1",
                    title="外部摘要",
                    summary="只保存摘要",
                    source_url="https://example.com/news/1",
                    canonical_url="https://example.com/news/1",
                    image_url="https://example.com/image.jpg",
                    author="作者",
                    source_name=source.name,
                    published_at=fixed_published_at,
                )
            ]

    first = execute_news_sync(
        run_no=str(run.run_no),
        source_codes=["TEST_RSS"],
        provider=FakeProvider(),
    )
    second_run = NewsSyncRun.objects.create(source_codes=["TEST_RSS"])
    second = execute_news_sync(
        run_no=str(second_run.run_no),
        source_codes=["TEST_RSS"],
        provider=FakeProvider(),
    )
    assert first["created_count"] == 1
    assert second["skipped_count"] == 1
    assert NewsArticle.objects.filter(source_unique_key="TEST_RSS:external-1").count() == 1
    assert NewsArticle.objects.get(source_unique_key="TEST_RSS:external-1").status == "PENDING"
