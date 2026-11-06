from __future__ import annotations

import uuid
from datetime import timedelta

import pytest
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from backend.accounts.models import AuthToken, User
from backend.accounts.services import _token_raw, hash_token
from backend.catalog.models import ProviderService, ServiceCategory
from backend.content.models import Moment
from backend.content.news_models import NewsArticle, NewsCategory
from backend.discovery.models import SearchQueryStat, SearchTrendingKeyword
from backend.media.models import MediaAsset
from backend.providers.models import ProviderProfile

pytestmark = pytest.mark.django_db


def create_user(phone_hash: str, *, staff: bool = False, provider: bool = False) -> User:
    return User.objects.create(
        phone_hash=phone_hash,
        phone_masked="138****8000",
        is_staff=staff,
        initial_role_selected=True,
        primary_role=User.InitialRole.PROVIDER if provider else User.InitialRole.USER,
        default_workspace=User.Workspace.PROVIDER_WORKSPACE
        if provider
        else User.Workspace.USER_HOME,
        provider_status=User.ProviderStatus.APPROVED
        if provider
        else User.ProviderStatus.NOT_SUBMITTED,
        provider_enabled=provider,
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


def create_search_content(provider: User) -> None:
    ServiceCategory.objects.get_or_create(code="SPORT", defaults={"name": "运动"})
    NewsCategory.objects.get_or_create(code="GENERAL", defaults={"name": "综合"})
    media_id = str(uuid.uuid4())
    MediaAsset.objects.create(
        public_id=media_id,
        owner=provider,
        purpose=MediaAsset.Purpose.PROVIDER_SERVICE_COVER,
        storage_key=f"search/{provider.id}/{media_id}",
        content_type="image/jpeg",
        extension="jpg",
        byte_size=1024,
        width=800,
        height=800,
        sha256=uuid.uuid4().hex,
        request_fingerprint="search-media",
    )
    profile = ProviderProfile.objects.create(
        user=provider,
        nickname="台球教练阿明",
        signature="耐心陪练",
        introduction="擅长台球基础教学和轻松陪练。",
    )
    service = ProviderService.objects.create(
        provider_user=provider,
        category_id="SPORT",
        title="台球助教体验",
        price_amount_minor=6800,
        duration_minutes=60,
        introduction="适合台球新手学习基础动作。",
        cover_media_id=media_id,
        status=ProviderService.Status.ONLINE,
        request_fingerprint="search-service",
    )
    Moment.objects.create(
        provider_user=provider,
        content="今天分享一组台球训练照片。",
        status=Moment.Status.PUBLISHED,
        published_at=timezone.now(),
        attached_service=service,
        request_fingerprint="search-moment",
    )
    NewsArticle.objects.create(
        title="城市台球公开课开始报名",
        summary="公开课介绍台球基础训练方法。",
        body="详细内容由管理员维护。",
        source_name="见面聊编辑部",
        status=NewsArticle.Status.PUBLISHED,
        published_at=timezone.now(),
    ).category_links.create(category_id="GENERAL")
    assert profile.nickname == "台球教练阿明"


def test_search_all_returns_matching_provider_moment_and_news() -> None:
    client = APIClient()
    provider = create_user("search-provider", provider=True)
    create_search_content(provider)

    response = client.get(reverse("v1:search-all"), {"keyword": "台球"})
    data = response.json()["data"]

    assert response.status_code == 200
    assert data["keyword"] == "台球"
    assert data["providers"]["total"] == 1
    assert data["moments"]["total"] == 1
    assert data["news"]["total"] == 1
    assert data["providers"]["items"][0]["provider_public_id"] == str(provider.public_id)


def test_category_search_only_returns_public_content_and_supports_paging() -> None:
    client = APIClient()
    provider = create_user("search-public-provider", provider=True)
    create_search_content(provider)
    private_provider = create_user("search-private-provider", provider=True)
    private_provider.provider_enabled = False
    private_provider.save(update_fields=["provider_enabled"])
    ProviderProfile.objects.create(
        user=private_provider,
        nickname="隐藏台球教练",
        introduction="不应出现在公开搜索结果中。",
    )

    providers = client.get(
        reverse("v1:search-providers"),
        {"keyword": "台球", "limit": 1},
    )
    moments = client.get(
        reverse("v1:search-moments"),
        {"keyword": "台球", "limit": 1},
    )
    news = client.get(
        reverse("v1:search-news"),
        {"keyword": "台球", "page": 1, "page_size": 1},
    )

    assert providers.status_code == 200
    assert providers.json()["data"]["total"] == 1
    assert providers.json()["data"]["has_more"] is False
    assert moments.json()["data"]["items"][0]["content"].startswith("今天分享")
    assert news.json()["data"]["items"][0]["title"] == "城市台球公开课开始报名"


def test_search_rejects_empty_keyword_but_does_not_store_sensitive_search() -> None:
    client = APIClient()

    empty_response = client.get(reverse("v1:search-all"), {"keyword": " "})
    sensitive_response = client.get(
        reverse("v1:search-all"),
        {"keyword": "13812345678"},
    )

    assert empty_response.status_code == 400
    assert empty_response.json()["code"] == "SEARCH_INVALID"
    assert sensitive_response.status_code == 200
    assert not SearchQueryStat.objects.exists()


def test_trending_merges_manual_priority_and_admin_can_hide_keyword() -> None:
    client = APIClient()
    admin = create_user("search-admin", staff=True)
    create_user("search-warmup", provider=True)
    client.get(reverse("v1:search-all"), {"keyword": "自动热词"})
    created = client.post(
        reverse("v1:admin-search-trending"),
        {
            "display_keyword": "人工置顶",
            "display_status": "ACTIVE",
            "manual_priority": 1,
        },
        **auth_headers(admin),
    )
    repeated = client.post(
        reverse("v1:admin-search-trending"),
        {
            "display_keyword": "人工置顶",
            "display_status": "ACTIVE",
            "manual_priority": 1,
        },
        **auth_headers(admin),
    )
    trending = client.get(reverse("v1:search-trending"), {"limit": 10})

    assert created.status_code == 201
    assert repeated.status_code == 201
    assert repeated.json()["data"]["reused"] is True
    assert trending.json()["data"]["items"][0]["display_text"] == "人工置顶"
    assert trending.json()["data"]["items"][0]["hot_score"] is None

    hidden = client.patch(
        reverse(
            "v1:admin-search-trending-detail",
            args=[created.json()["data"]["trending_id"]],
        ),
        {
            "expected_version": created.json()["data"]["version"],
            "display_status": "HIDDEN",
        },
        **auth_headers(admin),
    )
    after_hidden = client.get(reverse("v1:search-trending"), {"limit": 10})

    assert hidden.status_code == 200
    assert all(item["display_text"] != "人工置顶" for item in after_hidden.json()["data"]["items"])


def test_admin_trending_update_rejects_stale_version() -> None:
    client = APIClient()
    admin = create_user("search-version-admin", staff=True)
    headers = auth_headers(admin)
    created = client.post(
        reverse("v1:admin-search-trending"),
        {"display_keyword": "版本热词", "manual_priority": 2},
        **headers,
    )
    first_update = client.patch(
        reverse(
            "v1:admin-search-trending-detail",
            args=[created.json()["data"]["trending_id"]],
        ),
        {"expected_version": 1, "manual_priority": 3},
        **headers,
    )
    stale_update = client.patch(
        reverse(
            "v1:admin-search-trending-detail",
            args=[created.json()["data"]["trending_id"]],
        ),
        {"expected_version": 1, "manual_priority": 4},
        **headers,
    )

    assert first_update.status_code == 200
    assert stale_update.status_code == 409
    assert stale_update.json()["code"] == "SEARCH_VERSION_CONFLICT"
    assert (
        SearchTrendingKeyword.objects.get(public_id=created.json()["data"]["trending_id"]).version
        == 2
    )
