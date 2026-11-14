"""地点搜索、公共场所过滤和快捷关键词管理接口测试。"""

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
from backend.integrations.geo.contracts import (
    GeoProviderUnavailable,
    GeoSearchItem,
    GeoSearchResult,
)
from backend.locations.models import LocationSearchKeyword, ProviderLocationState
from backend.profiles.models import UserProfile
from backend.providers.models import ProviderProfile

pytestmark = pytest.mark.django_db


def create_user(*, staff: bool = False, provider: bool = False) -> User:
    """创建具备可用 Bearer 令牌的测试用户。"""

    return User.objects.create(
        phone_hash=f"location-user-{uuid.uuid4().hex}",
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
    """为测试用户签发不透明访问令牌。"""

    token_public_id = uuid.uuid4()
    raw_token = _token_raw(AuthToken.TokenType.ACCESS, token_public_id)
    AuthToken.objects.create(
        public_id=token_public_id,
        user=user,
        token_type=AuthToken.TokenType.ACCESS,
        token_hash=hash_token(raw_token),
        expires_at=timezone.now() + timedelta(hours=1),
    )
    return {"HTTP_AUTHORIZATION": f"Bearer {raw_token}"}


class StaticGeoProvider:
    """返回固定 POI 的测试适配器，用于验证过滤和距离计算。"""

    def __init__(self, items: list[GeoSearchItem]) -> None:
        self.items = items
        self.calls: list[dict[str, float | int | str]] = []

    def search_nearby(
        self,
        *,
        keyword: str,
        latitude: float,
        longitude: float,
        radius_m: int,
        limit: int,
    ) -> GeoSearchResult:
        self.calls.append(
            {
                "keyword": keyword,
                "latitude": latitude,
                "longitude": longitude,
                "radius_m": radius_m,
                "limit": limit,
            }
        )
        return GeoSearchResult(
            items=self.items[:limit], provider_total=len(self.items), provider="FAKE"
        )


def poi(
    name: str,
    category: str,
    *,
    latitude: float = 34.341,
    longitude: float = 108.941,
    address: str = "公共场所地址",
) -> GeoSearchItem:
    """构造第三方 POI 测试数据。"""

    return GeoSearchItem(
        provider_poi_id=f"poi-{name}",
        name=name,
        address=address,
        province="陕西省",
        city="西安市",
        district="雁塔区",
        category_code="TEST",
        category_name=category,
        latitude=latitude,
        longitude=longitude,
    )


def test_location_search_requires_authenticated_user() -> None:
    client = APIClient()

    response = client.get(
        reverse("v1:location-search"),
        {
            "keyword": "咖啡",
            "latitude": 34.341,
            "longitude": 108.941,
            "coordinate_system": "GCJ02",
        },
    )

    assert response.status_code == 401


def test_location_search_filters_unsafe_pois_and_returns_distance(monkeypatch) -> None:
    user = create_user()
    provider = StaticGeoProvider(
        [
            poi("咖啡店", "咖啡厅"),
            poi("示例酒店", "酒店"),
            poi("神秘场所", "未知分类"),
        ]
    )
    monkeypatch.setattr("backend.locations.services.get_geo_provider", lambda: provider)
    client = APIClient()

    response = client.get(
        reverse("v1:location-search"),
        {
            "keyword": "咖啡",
            "latitude": 34.341,
            "longitude": 108.940,
            "coordinate_system": "GCJ02",
            "radius_m": 2000,
            "limit": 10,
        },
        **auth_headers(user),
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["items"][0]["name"] == "咖啡店"
    assert data["items"][0]["distance_m"] == pytest.approx(92, abs=3)
    assert data["filtered_count"] == 2
    assert provider.calls[0]["keyword"] == "咖啡"


def test_location_search_rejects_hotel_keyword_before_provider_call(monkeypatch) -> None:
    user = create_user()
    provider = StaticGeoProvider([])
    monkeypatch.setattr("backend.locations.services.get_geo_provider", lambda: provider)
    client = APIClient()

    response = client.get(
        reverse("v1:location-search"),
        {
            "keyword": "附近酒店",
            "latitude": 34.341,
            "longitude": 108.941,
            "coordinate_system": "GCJ02",
        },
        **auth_headers(user),
    )

    assert response.status_code == 422
    assert response.json()["code"] == "LOCATION_KEYWORD_NOT_ALLOWED"
    assert provider.calls == []


def test_location_search_accepts_quick_keyword_and_wgs84(monkeypatch) -> None:
    user = create_user()
    provider = StaticGeoProvider([poi("咖啡店", "咖啡厅")])
    monkeypatch.setattr("backend.locations.services.get_geo_provider", lambda: provider)
    client = APIClient()

    response = client.get(
        reverse("v1:location-search"),
        {
            "quick_keyword_code": "COFFEE",
            "latitude": 34.341,
            "longitude": 108.941,
            "coordinate_system": "WGS84",
        },
        **auth_headers(user),
    )

    assert response.status_code == 200
    assert response.json()["data"]["quick_keyword_code"] == "COFFEE"
    assert provider.calls[0]["latitude"] != pytest.approx(34.341)


def test_admin_quick_keyword_create_is_idempotent_and_rejects_unsafe_query() -> None:
    admin = create_user(staff=True)
    client = APIClient()
    headers = auth_headers(admin)
    create_url = reverse("v1:admin-location-quick-keywords")

    first = client.post(
        create_url,
        {
            "code": "NEW_CAFE",
            "label": "新咖啡店",
            "query_keyword": "咖啡",
            "sort_order": 1,
        },
        format="json",
        HTTP_IDEMPOTENCY_KEY="location-keyword-1",
        **headers,
    )
    replay = client.post(
        create_url,
        {
            "code": "NEW_CAFE",
            "label": "新咖啡店",
            "query_keyword": "咖啡",
            "sort_order": 1,
        },
        format="json",
        HTTP_IDEMPOTENCY_KEY="location-keyword-1",
        **headers,
    )
    conflict = client.post(
        create_url,
        {
            "code": "NEW_CAFE",
            "label": "不同名称",
            "query_keyword": "咖啡",
            "sort_order": 1,
        },
        format="json",
        HTTP_IDEMPOTENCY_KEY="location-keyword-1",
        **headers,
    )
    unsafe = client.post(
        create_url,
        {
            "code": "UNSAFE_HOTEL",
            "label": "酒店",
            "query_keyword": "酒店",
        },
        format="json",
        **headers,
    )

    assert first.status_code == 201
    assert replay.status_code == 201
    assert replay.json()["data"]["reused"] is True
    assert conflict.status_code == 409
    assert unsafe.status_code == 422
    assert unsafe.json()["code"] == "LOCATION_KEYWORD_NOT_ALLOWED"


def test_admin_quick_keyword_update_uses_expected_version() -> None:
    admin = create_user(staff=True)
    client = APIClient()
    headers = auth_headers(admin)
    created = client.post(
        reverse("v1:admin-location-quick-keywords"),
        {
            "code": "VERSIONED_CAFE",
            "label": "咖啡店",
            "query_keyword": "咖啡",
        },
        format="json",
        **headers,
    )
    detail_url = reverse(
        "v1:admin-location-quick-keyword-detail",
        args=[created.json()["data"]["keyword_id"]],
    )
    updated = client.patch(
        detail_url,
        {"expected_version": 1, "label": "精品咖啡店"},
        format="json",
        **headers,
    )
    stale = client.patch(
        detail_url,
        {"expected_version": 1, "label": "再次修改"},
        format="json",
        **headers,
    )

    assert updated.status_code == 200
    assert stale.status_code == 409
    assert stale.json()["code"] == "LOCATION_QUICK_KEYWORD_VERSION_CONFLICT"


def test_location_provider_failure_maps_to_service_unavailable(monkeypatch) -> None:
    user = create_user()

    def raise_unavailable():
        raise GeoProviderUnavailable("test")

    monkeypatch.setattr("backend.locations.services.get_geo_provider", raise_unavailable)
    response = APIClient().get(
        reverse("v1:location-search"),
        {
            "keyword": "咖啡",
            "latitude": 34.341,
            "longitude": 108.941,
        },
        **auth_headers(user),
    )

    assert response.status_code == 503
    assert response.json()["code"] == "LOCATION_PROVIDER_UNAVAILABLE"


def test_location_search_seed_configuration_is_available() -> None:
    assert LocationSearchKeyword.objects.filter(code="COFFEE", enabled=True).exists()


def test_provider_location_is_encrypted_and_normal_user_location_is_not_saved() -> None:
    provider = create_user(provider=True)
    normal_user = create_user()
    client = APIClient()

    provider_response = client.put(
        reverse("v1:provider-location"),
        {
            "latitude": 34.341234,
            "longitude": 108.941234,
            "coordinate_system": "GCJ02",
            "accuracy_m": 20,
            "source": "LOGIN",
        },
        format="json",
        **auth_headers(provider),
    )
    denied = client.put(
        reverse("v1:provider-location"),
        {"latitude": 34.341, "longitude": 108.941},
        format="json",
        **auth_headers(normal_user),
    )
    state = ProviderLocationState.objects.get(user=provider)

    assert provider_response.status_code == 200
    assert denied.status_code == 403
    assert denied.json()["code"] == "PROVIDER_NOT_ENABLED"
    assert "34.341" not in state.latitude_encrypted
    assert "108.941" not in state.longitude_encrypted
    assert not ProviderLocationState.objects.filter(user=normal_user).exists()


def test_home_feed_uses_transient_viewer_location_and_returns_one_decimal_distance() -> None:
    provider = create_user(provider=True)
    viewer = create_user()
    UserProfile.objects.create(user=provider, nickname="附近服务者", city_code="LZ")
    ProviderProfile.objects.create(
        user=provider,
        nickname="附近服务者",
        signature="耐心陪伴",
        introduction="提供公开场所的轻松陪伴服务。",
    )
    category, _ = ServiceCategory.objects.get_or_create(code="SPORT", defaults={"name": "运动"})
    ProviderService.objects.create(
        provider_user=provider,
        category=category,
        title="运动陪伴",
        price_amount_minor=6800,
        duration_minutes=60,
        introduction="适合公开运动场所的陪伴服务。",
        cover_media_id=str(uuid.uuid4()),
        status=ProviderService.Status.ONLINE,
        request_fingerprint="home-location-service",
    )
    client = APIClient()
    client.put(
        reverse("v1:provider-location"),
        {"latitude": 34.341, "longitude": 108.941},
        format="json",
        **auth_headers(provider),
    )

    response = client.post(
        reverse("v1:home-feed"),
        {
            "city_code": "LZ",
            "latitude": 34.340,
            "longitude": 108.940,
            "coordinate_system": "GCJ02",
        },
        format="json",
        **auth_headers(viewer),
    )
    without_location = client.get(
        reverse("v1:home-feed"),
        {"city_code": "LZ"},
        **auth_headers(viewer),
    )

    assert response.status_code == 200
    item = response.json()["data"][0]
    assert item["distance_km"] == pytest.approx(0.1, abs=0.1)
    assert item["distance_text"].endswith("公里")
    assert without_location.json()["data"][0]["distance_km"] is None
    assert not ProviderLocationState.objects.filter(user=viewer).exists()
