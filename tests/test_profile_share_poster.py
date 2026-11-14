"""个人分享海报数据接口的响应、配置和隐私边界测试。"""

from __future__ import annotations

import uuid
from datetime import timedelta
from urllib.parse import parse_qs, urlparse

import pytest
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from backend.accounts.models import AuthToken, User
from backend.accounts.services import _token_raw, hash_token
from backend.media.models import MediaAsset
from backend.profiles.models import InterestTag, UserProfile, UserProfileInterest

pytestmark = pytest.mark.django_db


def create_user(phone_hash: str) -> User:
    return User.objects.create(phone_hash=phone_hash, phone_masked="138****8000")


def auth_headers(user: User) -> dict[str, str]:
    token_id = uuid.uuid4()
    raw_token = _token_raw(AuthToken.TokenType.ACCESS, token_id)
    AuthToken.objects.create(
        public_id=token_id,
        user=user,
        token_type=AuthToken.TokenType.ACCESS,
        token_hash=hash_token(raw_token),
        expires_at=timezone.now() + timedelta(hours=1),
    )
    return {"HTTP_AUTHORIZATION": f"Bearer {raw_token}"}


def create_avatar(user: User, media_id: str) -> None:
    MediaAsset.objects.create(
        public_id=media_id,
        owner=user,
        purpose=MediaAsset.Purpose.USER_PROFILE_AVATAR,
        storage_key=f"test/share/{media_id}",
        content_type="image/jpeg",
        extension="jpg",
        byte_size=2048,
        width=900,
        height=1200,
        sha256="c" * 64,
        request_fingerprint="d" * 64,
    )


@override_settings(
    PUBLIC_SHARE_BASE_URL="https://share.example.test/base/",
    SHARE_POSTER_BRAND_NAME="测试品牌",
    SHARE_POSTER_BRAND_LABEL="测试标签",
    SHARE_POSTER_SLOGAN_LINE_1="第一行",
    SHARE_POSTER_SLOGAN_LINE_2="第二行",
    SHARE_POSTER_SLOGAN_SUBTITLE="说明句",
    SHARE_POSTER_CARD_FOOTER="底部提示",
    SHARE_POSTER_BOTTOM_SLOGAN="底部标语",
    SHARE_POSTER_SHARE_TITLE="分享标题",
    SHARE_POSTER_SHARE_DESCRIPTION="分享描述",
)
def test_share_poster_returns_profile_media_tags_and_safe_share_fields() -> None:
    client = APIClient()
    user = create_user("share-poster-user")
    media_id = str(uuid.UUID(int=9001))
    create_avatar(user, media_id)
    profile = UserProfile.objects.create(
        user=user,
        nickname="海报用户",
        avatar_media_id=media_id,
        age=26,
        city_code="LZ",
        signature="一起发现生活",
    )
    tag = InterestTag.objects.get(code="TRAVEL")
    UserProfileInterest.objects.create(profile=profile, tag=tag)

    response = client.get(reverse("v1:users-me-share-poster"), **auth_headers(user))

    assert response.status_code == 200
    data = response.json()["data"]
    parsed_url = urlparse(data["profile_url"])
    query = parse_qs(parsed_url.query)
    assert data["brand_name"] == "测试品牌"
    assert data["cover"]["media_id"] == media_id
    assert data["cover"]["width"] == 900
    assert data["nickname"] == "海报用户"
    assert data["age"] == 26
    assert data["city"] == "泸州"
    assert data["signature"] == "一起发现生活"
    assert data["interest_tags"] == ["旅行"]
    assert parsed_url.path == "/base/invite/"
    assert query["invite_code"][0]
    assert query["share_no"][0]
    parsed_qr_url = urlparse(data["qr_image_url"])
    assert parsed_qr_url.path.startswith("/api/v1/referrals/qr/")
    assert data["qr_image_expires_at"]
    assert data["share"] == {
        "link_url": data["profile_url"],
        "title": "分享标题",
        "description": "分享描述",
    }
    assert "token" not in response.text.lower()
    assert "phone" not in response.text.lower()
    qr_response = client.get(parsed_qr_url.path + "?" + parsed_qr_url.query)
    assert qr_response.status_code == 200
    assert qr_response["Content-Type"] == "image/png"


def test_share_poster_uses_safe_defaults_without_profile_or_avatar() -> None:
    client = APIClient()
    user = create_user("share-poster-default-user")

    response = client.get(reverse("v1:users-me-share-poster"), **auth_headers(user))

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["cover"] is None
    assert data["nickname"] == "见面聊用户"
    assert data["age"] is None
    assert data["city"] == ""
    assert data["interest_tags"] == []
    assert urlparse(data["profile_url"]).path.endswith("/invite/")


def test_invite_landing_page_is_public_and_preserves_query_parameters() -> None:
    client = APIClient()

    response = client.get("/invite/?invite_code=ABC123&share_no=test&channel=POSTER")

    assert response.status_code == 200
    assert response["Content-Type"].startswith("text/html")
    content = b"".join(response.streaming_content)
    assert "见面聊".encode() in content


@override_settings(PUBLIC_SHARE_BASE_URL="https://old-share.example.test")
def test_existing_qr_image_is_regenerated_when_share_domain_changes() -> None:
    client = APIClient()
    user = create_user("share-qr-refresh-user")
    headers = auth_headers(user)
    old_poster = client.get(reverse("v1:users-me-share-poster"), **headers).json()["data"]
    old_qr_url = urlparse(old_poster["qr_image_url"])
    old_qr = client.get(old_qr_url.path + "?" + old_qr_url.query)
    old_bytes = b"".join(old_qr.streaming_content)

    with override_settings(PUBLIC_SHARE_BASE_URL="https://new-share.example.test"):
        new_poster = client.get(reverse("v1:users-me-share-poster"), **headers).json()["data"]
        new_qr_url = urlparse(new_poster["qr_image_url"])
        new_qr = client.get(new_qr_url.path + "?" + new_qr_url.query)
        new_bytes = b"".join(new_qr.streaming_content)

    assert old_bytes != new_bytes


def test_share_poster_requires_authentication_and_rejects_unsafe_share_base_url() -> None:
    client = APIClient()
    user = create_user("share-poster-auth-user")
    url = reverse("v1:users-me-share-poster")

    anonymous = client.get(url)
    with override_settings(PUBLIC_SHARE_BASE_URL="javascript:alert(1)"):
        invalid_config = client.get(url, **auth_headers(user))

    assert anonymous.status_code == 401
    assert invalid_config.status_code == 400
    assert invalid_config.json()["code"] == "REFERRAL_INVALID"
