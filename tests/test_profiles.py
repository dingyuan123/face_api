from __future__ import annotations

import uuid
from datetime import timedelta

import pytest
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from backend.accounts.models import AuthToken, User
from backend.accounts.services import _token_raw, hash_token
from backend.media.models import MediaAsset
from backend.profiles.models import InterestTag

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


def profile_get(client: APIClient, user: User):
    return client.get(reverse("v1:users-me-profile"), **auth_headers(user))


def profile_patch(client: APIClient, user: User, payload: dict, version: int):
    return client.patch(
        reverse("v1:users-me-profile"),
        {"expected_version": version, **payload},
        format="json",
        **auth_headers(user),
    )


def test_profile_query_returns_safe_defaults_and_configurable_options() -> None:
    client = APIClient()
    user = create_user("profile-default-user")

    response = profile_get(client, user)
    options = client.get(reverse("v1:profile-interest-tags"))
    cities = client.get(reverse("v1:profile-city-options"))

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["version"] == 0
    assert data["city_code"] == "LZ"
    assert data["city_name"] == "泸州"
    assert data["trust_level"]["code"] == "UNSET"
    assert data["profile_completeness"] == 0
    assert options.status_code == cities.status_code == 200
    assert "TRAVEL" in [item["code"] for item in options.json()["data"]]
    assert cities.json()["data"] == [{"code": "LZ", "name": "泸州", "sort_order": 10}]


def test_profile_update_supports_partial_fields_and_interest_tags() -> None:
    client = APIClient()
    user = create_user("profile-update-user")

    first = profile_patch(
        client,
        user,
        {
            "nickname": "小王",
            "gender": "MALE",
            "age": 24,
            "signature": "很高兴认识大家",
            "interest_tag_codes": ["TRAVEL", "PHOTOGRAPHY"],
        },
        version=0,
    )
    second = profile_patch(client, user, {"signature": "新的签名"}, version=1)
    unchanged = profile_patch(client, user, {"signature": "新的签名"}, version=2)

    assert first.status_code == 200
    assert first.json()["data"]["changed"] is True
    assert first.json()["data"]["version"] == 1
    assert [tag["code"] for tag in first.json()["data"]["interest_tags"]] == [
        "TRAVEL",
        "PHOTOGRAPHY",
    ]
    assert second.status_code == 200
    assert second.json()["data"]["version"] == 2
    assert unchanged.status_code == 200
    assert unchanged.json()["data"]["changed"] is False
    assert unchanged.json()["data"]["version"] == 2


def test_profile_rejects_invalid_values_and_case_insensitive_duplicate_nickname() -> None:
    client = APIClient()
    first_user = create_user("profile-valid-user")
    second_user = create_user("profile-conflict-user")
    profile_patch(client, first_user, {"nickname": "Alice"}, version=0)

    duplicate = profile_patch(client, second_user, {"nickname": "alice"}, version=0)
    too_short = profile_patch(client, second_user, {"nickname": ""}, version=0)
    bad_age = profile_patch(client, second_user, {"age": 17}, version=0)
    bad_gender = profile_patch(client, second_user, {"gender": "SECRET"}, version=0)
    long_signature = profile_patch(client, second_user, {"signature": "x" * 101}, version=0)
    six_tags = profile_patch(
        client,
        second_user,
        {"interest_tag_codes": [f"TAG_{index}" for index in range(6)]},
        version=0,
    )

    assert duplicate.status_code == 409
    assert duplicate.json()["code"] == "PROFILE_NICKNAME_CONFLICT"
    assert too_short.status_code == bad_age.status_code == bad_gender.status_code == 400
    assert long_signature.status_code == 400
    assert six_tags.status_code == 400


def test_profile_update_rejects_stale_version_and_unknown_or_inactive_tags() -> None:
    client = APIClient()
    user = create_user("profile-version-user")
    profile_patch(client, user, {"nickname": "版本用户"}, version=0)

    stale = profile_patch(client, user, {"signature": "旧版本"}, version=0)
    unknown_tag = profile_patch(
        client,
        user,
        {"interest_tag_codes": ["UNKNOWN"]},
        version=1,
    )
    tag = InterestTag.objects.get(code="TRAVEL")
    tag.is_active = False
    tag.save(update_fields=["is_active"])
    inactive_tag = profile_patch(
        client,
        user,
        {"interest_tag_codes": ["TRAVEL"]},
        version=1,
    )

    assert stale.status_code == 409
    assert stale.json()["code"] == "PROFILE_VERSION_CONFLICT"
    assert unknown_tag.status_code == inactive_tag.status_code == 400
    assert unknown_tag.json()["code"] == inactive_tag.json()["code"] == "PROFILE_OPTION_UNAVAILABLE"


def test_profile_avatar_must_be_owned_profile_avatar_media() -> None:
    client = APIClient()
    owner = create_user("profile-avatar-owner")
    applicant = create_user("profile-avatar-applicant")
    media_id = str(uuid.UUID(int=101))
    MediaAsset.objects.create(
        public_id=media_id,
        owner=owner,
        purpose=MediaAsset.Purpose.USER_PROFILE_AVATAR,
        storage_key=f"test/profile/{media_id}",
        content_type="image/jpeg",
        extension="jpg",
        byte_size=1024,
        width=800,
        height=800,
        sha256="a" * 64,
        request_fingerprint="b" * 64,
    )

    denied = profile_patch(client, applicant, {"avatar_media_id": media_id}, version=0)
    accepted = profile_patch(client, owner, {"avatar_media_id": media_id}, version=0)

    assert denied.status_code == 400
    assert denied.json()["code"] == "MEDIA_NOT_FOUND"
    assert accepted.status_code == 200
    assert accepted.json()["data"]["avatar_media"]["media_id"] == media_id
    assert accepted.json()["data"]["avatar_media"]["display_url"]
