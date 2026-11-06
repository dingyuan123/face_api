from __future__ import annotations

import uuid
from datetime import timedelta

import pytest
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from backend.accounts.models import AuthToken, User
from backend.accounts.services import _token_raw, hash_token
from backend.catalog.models import ProviderService
from backend.media.models import MediaAsset
from backend.providers.models import ProviderApplication

pytestmark = pytest.mark.django_db


def create_user(phone_hash: str, *, is_staff: bool = False, provider: bool = True) -> User:
    return User.objects.create(
        phone_hash=phone_hash,
        phone_masked="138****8000",
        is_staff=is_staff,
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
        storage_key=f"test/{user.id}/{purpose}/{marker}",
        content_type="image/jpeg",
        extension="jpg",
        byte_size=1024,
        width=800,
        height=800,
        sha256=f"{marker:0<64}",
        request_fingerprint=f"{marker:0<64}",
    )
    return media_id


def create_provider_profile(client: APIClient, user: User) -> dict:
    avatar = create_media(user, MediaAsset.Purpose.PROVIDER_PROFILE_AVATAR, "avatar")
    photos = [
        create_media(user, MediaAsset.Purpose.PROVIDER_PROFILE_PHOTO, f"photo-{index}")
        for index in range(3)
    ]
    response = client.patch(
        reverse("v1:provider-profile-me"),
        {
            "expected_version": 0,
            "nickname": "服务者",
            "signature": "耐心细致",
            "introduction": "擅长台球基础教学和轻松陪练，适合新手入门练习。",
            "avatar_media_id": avatar,
            "photo_media_ids": photos,
            "category_codes": ["SPORT"],
            "tag_codes": ["PENDING_TEACHING", "FRIENDLY"],
        },
        format="json",
        **auth_headers(user),
    )
    assert response.status_code == 200
    return response.json()["data"]


def create_service_body(user: User) -> dict:
    return {
        "title": "台球助教 · 新手体验",
        "category_code": "SPORT",
        "currency": "CNY",
        "price_amount_minor": 6800,
        "duration_minutes": 60,
        "introduction": "适合新手学习基础动作。",
        "cover_media_id": create_media(user, MediaAsset.Purpose.PROVIDER_SERVICE_COVER, "cover"),
        "gallery_media_ids": [
            create_media(user, MediaAsset.Purpose.PROVIDER_SERVICE_GALLERY, "gallery-0"),
            create_media(user, MediaAsset.Purpose.PROVIDER_SERVICE_GALLERY, "gallery-1"),
        ],
        "tag_codes": ["BEGINNER", "PATIENT"],
        "location_type": "PUBLIC_PLACE",
    }


def test_provider_profile_and_service_options_are_configurable() -> None:
    client = APIClient()
    user = create_user("provider-config-user")
    profile = create_provider_profile(client, user)

    categories = client.get(reverse("v1:provider-service-categories"))
    service_tags = client.get(reverse("v1:provider-service-tags"))
    provider_tags = client.get(reverse("v1:provider-profile-tags"))

    assert profile["category_codes"] == ["SPORT"]
    assert categories.status_code == service_tags.status_code == provider_tags.status_code == 200
    assert "SPORT" in [item["code"] for item in categories.json()["data"]]
    assert "BEGINNER" in [item["code"] for item in service_tags.json()["data"]]
    assert "PENDING_TEACHING" in [item["code"] for item in provider_tags.json()["data"]]


def test_provider_profile_falls_back_to_application_avatar() -> None:
    client = APIClient()
    user = create_user("provider-application-avatar-user")
    avatar = create_media(
        user,
        MediaAsset.Purpose.PROVIDER_APPLICATION_AVATAR,
        "application-avatar",
    )
    ProviderApplication.objects.create(
        application_no=ProviderApplication.make_application_no(),
        user=user,
        status=ProviderApplication.Status.APPROVED,
        introduction="申请阶段已经上传头像。",
        real_name_encrypted="encrypted",
        id_card_encrypted="encrypted",
        id_card_hash="hash",
        avatar_media_id=avatar,
        life_photo_media_ids=[],
        request_fingerprint="fingerprint",
    )

    response = client.get(reverse("v1:provider-profile-me"), **auth_headers(user))

    assert response.status_code == 200
    assert response.json()["data"]["version"] == 0
    assert response.json()["data"]["avatar_media"]["media_id"] == avatar


def test_provider_profile_can_reuse_application_avatar_and_life_photos() -> None:
    client = APIClient()
    user = create_user("provider-application-media-user")
    avatar = create_media(
        user,
        MediaAsset.Purpose.PROVIDER_APPLICATION_AVATAR,
        "reuse-application-avatar",
    )
    photos = [
        create_media(
            user,
            MediaAsset.Purpose.PROVIDER_APPLICATION_LIFE_PHOTO,
            f"reuse-application-photo-{index}",
        )
        for index in range(3)
    ]
    ProviderApplication.objects.create(
        application_no=ProviderApplication.make_application_no(),
        user=user,
        status=ProviderApplication.Status.APPROVED,
        introduction="申请阶段已经上传头像和生活照。",
        real_name_encrypted="encrypted",
        id_card_encrypted="encrypted",
        id_card_hash="hash",
        avatar_media_id=avatar,
        life_photo_media_ids=photos,
        request_fingerprint="fingerprint",
    )

    response = client.patch(
        reverse("v1:provider-profile-me"),
        {
            "expected_version": 0,
            "nickname": "复用媒体",
            "introduction": "这里复用申请阶段上传的头像和生活照资料。",
            "avatar_media_id": avatar,
            "photo_media_ids": photos,
            "category_codes": ["SPORT"],
            "tag_codes": ["FRIENDLY"],
        },
        format="json",
        **auth_headers(user),
    )

    assert response.status_code == 200
    assert response.json()["data"]["avatar_media"]["media_id"] == avatar
    assert [item["media_id"] for item in response.json()["data"]["photo_media"]] == photos


def test_provider_profile_requires_complete_first_submission_and_is_versioned() -> None:
    client = APIClient()
    user = create_user("provider-profile-version-user")
    missing = client.patch(
        reverse("v1:provider-profile-me"),
        {"expected_version": 0, "nickname": "只填昵称"},
        format="json",
        **auth_headers(user),
    )
    created = create_provider_profile(client, user)
    stale = client.patch(
        reverse("v1:provider-profile-me"),
        {"expected_version": 0, "signature": "旧版本"},
        format="json",
        **auth_headers(user),
    )
    updated = client.patch(
        reverse("v1:provider-profile-me"),
        {"expected_version": 1, "signature": "新的签名"},
        format="json",
        **auth_headers(user),
    )

    assert missing.status_code == 400
    assert created["version"] == 1
    assert stale.status_code == 409
    assert updated.status_code == 200
    assert updated.json()["data"]["version"] == 2


def test_provider_profile_rejects_duplicate_nickname_and_invalid_media_rules() -> None:
    client = APIClient()
    first = create_user("provider-profile-first")
    second = create_user("provider-profile-second")
    create_provider_profile(client, first)
    avatar = create_media(second, MediaAsset.Purpose.PROVIDER_PROFILE_AVATAR, "second-avatar")
    photos = [
        create_media(second, MediaAsset.Purpose.PROVIDER_PROFILE_PHOTO, f"second-photo-{index}")
        for index in range(2)
    ]

    duplicate = client.patch(
        reverse("v1:provider-profile-me"),
        {
            "expected_version": 0,
            "nickname": "服务者",
            "introduction": "这是一个符合长度要求的服务者个人介绍，欢迎联系。",
            "avatar_media_id": avatar,
            "photo_media_ids": photos,
            "category_codes": ["SPORT"],
        },
        format="json",
        **auth_headers(second),
    )
    assert duplicate.status_code == 400
    assert duplicate.json()["code"] == "PROVIDER_PROFILE_INVALID"


def test_service_create_edit_and_money_format() -> None:
    client = APIClient()
    user = create_user("service-money-user")
    create_provider_profile(client, user)
    body = create_service_body(user)

    created = client.post(
        reverse("v1:provider-services"),
        body,
        format="json",
        **auth_headers(user),
    )
    service_id = created.json()["data"]["id"]
    edited = client.patch(
        reverse("v1:provider-service-detail", args=[service_id]),
        {
            "expected_version": 1,
            **body,
            "title": "台球助教 · 进阶训练",
            "price_amount_minor": 8800,
        },
        format="json",
        **auth_headers(user),
    )

    assert created.status_code == 201
    assert created.json()["data"]["status"] == "DRAFT"
    assert created.json()["data"]["price"] == {"currency": "CNY", "amount_minor": 6800}
    assert created.json()["data"]["price_display"] == "68.00"
    assert edited.status_code == 200
    assert edited.json()["data"]["price_display"] == "88.00"
    assert edited.json()["data"]["version"] == 2


def test_public_service_detail_only_exposes_online_service() -> None:
    client = APIClient()
    user = create_user("public-service-detail-user")
    create_provider_profile(client, user)
    created = client.post(
        reverse("v1:provider-services"),
        create_service_body(user),
        format="json",
        **auth_headers(user),
    )
    service_id = created.json()["data"]["id"]

    hidden = client.get(reverse("v1:public-service-detail", args=[service_id]))
    ProviderService.objects.filter(public_id=service_id).update(
        status=ProviderService.Status.ONLINE
    )
    published = client.get(reverse("v1:public-service-detail", args=[service_id]))

    assert hidden.status_code == 404
    assert published.status_code == 200
    assert published.json()["data"]["id"] == service_id
    assert published.json()["data"]["status"] == "ONLINE"
    assert published.json()["data"]["pricing_unit"] == "HOUR"


def test_service_idempotency_list_summary_and_state_transitions() -> None:
    client = APIClient()
    user = create_user("service-state-user")
    admin = create_user("service-admin", is_staff=True, provider=False)
    create_provider_profile(client, user)
    body = create_service_body(user)

    created = client.post(
        reverse("v1:provider-services"),
        body,
        format="json",
        HTTP_IDEMPOTENCY_KEY="service-1",
        **auth_headers(user),
    )
    replay = client.post(
        reverse("v1:provider-services"),
        body,
        format="json",
        HTTP_IDEMPOTENCY_KEY="service-1",
        **auth_headers(user),
    )
    service_id = created.json()["data"]["id"]
    listing = client.get(
        f"{reverse('v1:provider-services')}?page=1&page_size=20",
        **auth_headers(user),
    )
    submitted = client.post(
        reverse("v1:provider-service-submit-review", args=[service_id]),
        {"expected_version": 1},
        format="json",
        **auth_headers(user),
    )
    duplicate_submit = client.post(
        reverse("v1:provider-service-submit-review", args=[service_id]),
        {"expected_version": 2},
        format="json",
        **auth_headers(user),
    )
    approved = client.post(
        reverse("v1:admin-provider-service-approve", args=[service_id]),
        {"expected_version": 2},
        format="json",
        **auth_headers(admin),
    )
    online = client.post(
        reverse("v1:provider-service-online", args=[service_id]),
        {"expected_version": 3},
        format="json",
        **auth_headers(user),
    )
    offline = client.post(
        reverse("v1:provider-service-offline", args=[service_id]),
        {"expected_version": 4},
        format="json",
        **auth_headers(user),
    )

    assert created.status_code == 201
    assert replay.status_code == 200
    assert replay.json()["data"]["id"] == service_id
    assert listing.json()["data"]["summary"]["total"] == 1
    assert submitted.json()["data"]["status"] == "PENDING"
    assert duplicate_submit.status_code == 409
    assert approved.json()["data"]["status"] == "APPROVED"
    assert online.json()["data"]["status"] == "ONLINE"
    assert offline.json()["data"]["status"] == "OFFLINE"


def test_service_rejects_invalid_money_options_and_state_operations() -> None:
    client = APIClient()
    user = create_user("service-invalid-user")
    create_provider_profile(client, user)
    body = create_service_body(user)

    invalid_money = client.post(
        reverse("v1:provider-services"),
        {**body, "price_amount_minor": 0},
        format="json",
        **auth_headers(user),
    )
    created = client.post(
        reverse("v1:provider-services"), body, format="json", **auth_headers(user)
    )
    service_id = created.json()["data"]["id"]
    online_before_review = client.post(
        reverse("v1:provider-service-online", args=[service_id]),
        {"expected_version": 1},
        format="json",
        **auth_headers(user),
    )

    assert invalid_money.status_code == 400
    assert invalid_money.json()["code"] == "SERVICE_INVALID"
    assert online_before_review.status_code == 409
    assert online_before_review.json()["code"] == "SERVICE_STATE_INVALID"


def test_service_delete_is_limited_to_draft_or_rejected() -> None:
    client = APIClient()
    user = create_user("service-delete-user")
    create_provider_profile(client, user)
    body = create_service_body(user)
    created = client.post(
        reverse("v1:provider-services"), body, format="json", **auth_headers(user)
    )
    service_id = created.json()["data"]["id"]

    deleted = client.delete(
        reverse("v1:provider-service-detail", args=[service_id]),
        {"expected_version": 1},
        format="json",
        **auth_headers(user),
    )
    detail = client.get(
        reverse("v1:provider-service-detail", args=[service_id]),
        **auth_headers(user),
    )

    assert deleted.status_code == 200
    assert deleted.json()["data"] == {"deleted": True}
    assert detail.status_code == 404
