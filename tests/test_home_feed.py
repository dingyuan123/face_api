from __future__ import annotations

import uuid
from datetime import timedelta

import pytest
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from backend.accounts.models import AuthToken, User
from backend.accounts.services import _token_raw, hash_token
from backend.catalog.models import (
    ProviderService,
    ProviderServiceGalleryMedia,
    ServiceCategory,
    ServiceTag,
)
from backend.media.models import MediaAsset
from backend.profiles.models import UserProfile
from backend.providers.models import (
    ProviderApplication,
    ProviderProfile,
    ProviderProfileCategory,
    ProviderProfileMedia,
    ProviderProfileTag,
)

pytestmark = pytest.mark.django_db


def create_user(phone_hash: str, *, gender: str = "MALE") -> User:
    user = User.objects.create(
        phone_hash=phone_hash,
        phone_masked="138****8000",
        initial_role_selected=True,
        primary_role=User.InitialRole.PROVIDER,
        default_workspace=User.Workspace.PROVIDER_WORKSPACE,
        provider_status=User.ProviderStatus.APPROVED,
        provider_enabled=True,
    )
    UserProfile.objects.create(
        user=user,
        nickname=f"user-{phone_hash}",
        gender=gender,
        age=28,
        city_code="LZ",
    )
    return user


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


def create_media(user: User, purpose: str, marker: str) -> str:
    media_id = str(uuid.uuid4())
    MediaAsset.objects.create(
        public_id=media_id,
        owner=user,
        purpose=purpose,
        storage_key=f"home/{user.id}/{purpose}/{marker}",
        content_type="image/jpeg",
        extension="jpg",
        byte_size=1024,
        width=800,
        height=800,
        sha256=f"{marker:0<64}",
        request_fingerprint=f"{marker:0<64}",
    )
    return media_id


def create_provider_card_data(user: User) -> tuple[ProviderProfile, ProviderService]:
    category = ServiceCategory.objects.get(code="SPORT")
    tag = ServiceTag.objects.get(code="BEGINNER")
    avatar = create_media(user, MediaAsset.Purpose.PROVIDER_PROFILE_AVATAR, "home-avatar")
    profile_photos = [
        create_media(user, MediaAsset.Purpose.PROVIDER_PROFILE_PHOTO, f"home-profile-{index}")
        for index in range(3)
    ]
    application_photos = [
        create_media(
            user,
            MediaAsset.Purpose.PROVIDER_APPLICATION_LIFE_PHOTO,
            f"home-application-{index}",
        )
        for index in range(3)
    ]
    application_avatar = create_media(
        user,
        MediaAsset.Purpose.PROVIDER_APPLICATION_AVATAR,
        "home-application-avatar",
    )
    ProviderApplication.objects.create(
        application_no=ProviderApplication.make_application_no(),
        user=user,
        status=ProviderApplication.Status.APPROVED,
        introduction="申请阶段已经上传生活照和头像。",
        real_name_encrypted="encrypted",
        id_card_encrypted="encrypted",
        id_card_hash="hash",
        avatar_media_id=application_avatar,
        life_photo_media_ids=application_photos,
        request_fingerprint="fingerprint",
    )
    profile = ProviderProfile.objects.create(
        user=user,
        nickname=f"provider-{user.id}",
        signature="耐心细致",
        introduction="擅长台球基础教学和轻松陪练，适合新手入门练习。",
        avatar_media_id=avatar,
    )
    ProviderProfileCategory.objects.create(profile=profile, category_code="SPORT")
    ProviderProfileTag.objects.create(profile=profile, tag_code="PENDING_TEACHING")
    for position, media_id in enumerate(profile_photos):
        ProviderProfileMedia.objects.create(
            profile=profile,
            media_id=media_id,
            position=position,
        )
    cover = create_media(user, MediaAsset.Purpose.PROVIDER_SERVICE_COVER, "home-cover")
    gallery = [
        create_media(user, MediaAsset.Purpose.PROVIDER_SERVICE_GALLERY, f"home-gallery-{index}")
        for index in range(2)
    ]
    service = ProviderService.objects.create(
        provider_user=user,
        category=category,
        title="台球助教",
        price_amount_minor=6800,
        duration_minutes=60,
        introduction="适合新手学习基础动作。",
        cover_media_id=cover,
        status=ProviderService.Status.ONLINE,
        request_fingerprint="fingerprint",
    )
    for position, media_id in enumerate(gallery):
        ProviderServiceGalleryMedia.objects.create(
            service=service,
            media_id=media_id,
            position=position,
        )
    from backend.catalog.models import ProviderServiceTag

    ProviderServiceTag.objects.create(service=service, tag=tag, position=0)
    return profile, service


def test_home_feed_returns_provider_gender_and_recent_related_photos() -> None:
    client = APIClient()
    user = create_user("home-feed-user")
    create_provider_card_data(user)

    response = client.get(
        f"{reverse('v1:home-feed')}?city_code=LZ&category_code=SPORT",
    )
    data = response.json()["data"]

    assert response.status_code == 200
    assert len(data) == 1
    card = data[0]
    assert card["provider"]["gender"] == "MALE"
    assert card["provider"]["age"] == 28
    assert card["provider_public_id"] == str(user.public_id)
    assert 3 <= card["recent_photo_count"] <= 5
    assert len(card["recent_photo_media"]) == card["recent_photo_count"]
    assert card["services"][0]["price"]["amount_minor"] == 6800
    assert card["online_status"] == "UNKNOWN"
    assert card["distance_km"] is None


def test_home_feed_filters_city_category_and_guest_limit() -> None:
    client = APIClient()
    user = create_user("home-feed-filter-user")
    create_provider_card_data(user)

    city_filtered = client.get(f"{reverse('v1:home-feed')}?city_code=OTHER")
    category_filtered = client.get(f"{reverse('v1:home-feed')}?city_code=LZ&category_code=TRAVEL")
    too_many = client.get(f"{reverse('v1:home-feed')}?limit=11")

    assert city_filtered.json()["data"] == []
    assert category_filtered.json()["data"] == []
    assert too_many.status_code == 400
    assert too_many.json()["code"] == "HOME_FEED_INVALID"


def test_admin_service_list_returns_provider_summary_and_status_counts() -> None:
    client = APIClient()
    user = create_user("admin-service-list-user")
    admin = create_user("admin-service-list-admin")
    admin.is_staff = True
    admin.save(update_fields=["is_staff"])
    create_provider_card_data(user)

    response = client.get(
        reverse("v1:admin-provider-services"),
        {"status": "ONLINE", "page": 1, "page_size": 20},
        **auth_headers(admin),
    )
    data = response.json()["data"]

    assert response.status_code == 200
    assert data["total"] == 1
    assert data["summary"]["online"] == 1
    assert data["items"][0]["provider"]["user_public_id"] == str(user.public_id)
    assert data["items"][0]["price"]["amount_minor"] == 6800
