from __future__ import annotations

import hashlib
import uuid
from datetime import timedelta

import pytest
from django.db import IntegrityError, transaction
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from backend.accounts.models import AuthToken, User
from backend.accounts.services import _token_raw, hash_token
from backend.identity.models import IdentityVerification
from backend.identity.services import review_real_name_verification
from backend.media.models import MediaAsset
from backend.providers.models import ProviderApplication, ProviderApplicationEvent

pytestmark = pytest.mark.django_db

REAL_NAME = "张三"
ID_CARD_NUMBER = "11010519491231002X"
AVATAR_MEDIA_ID = str(uuid.UUID(int=1))
LIFE_PHOTO_MEDIA_IDS = [str(uuid.UUID(int=value)) for value in (2, 3, 4)]
ID_CARD_FRONT_MEDIA_ID = str(uuid.UUID(int=1001))
ID_CARD_BACK_MEDIA_ID = str(uuid.UUID(int=1002))
EMERGENCY_CONTACT_NAME = "王五"
EMERGENCY_CONTACT_PHONE = "13900001234"
APPLICATION_BODY = {
    "introduction": "我有丰富的陪伴服务经验, 沟通耐心。",
    "real_name": REAL_NAME,
    "id_card_number": ID_CARD_NUMBER,
    "id_card_front_media_id": ID_CARD_FRONT_MEDIA_ID,
    "id_card_back_media_id": ID_CARD_BACK_MEDIA_ID,
    "emergency_contact_name": EMERGENCY_CONTACT_NAME,
    "emergency_contact_phone": EMERGENCY_CONTACT_PHONE,
    "avatar_media_id": AVATAR_MEDIA_ID,
    "life_photo_media_ids": LIFE_PHOTO_MEDIA_IDS,
}


def create_user(phone_hash: str, *, is_staff: bool = False) -> User:
    return User.objects.create(
        phone_hash=phone_hash,
        phone_masked="138****8000",
        is_staff=is_staff,
    )


def auth_headers(user: User, key: str | None = None) -> dict[str, str]:
    token_id = uuid.uuid4()
    raw_token = _token_raw(AuthToken.TokenType.ACCESS, token_id)
    AuthToken.objects.create(
        public_id=token_id,
        user=user,
        token_type=AuthToken.TokenType.ACCESS,
        token_hash=hash_token(raw_token),
        expires_at=timezone.now() + timedelta(hours=1),
    )
    headers = {"HTTP_AUTHORIZATION": f"Bearer {raw_token}"}
    if key:
        headers["HTTP_IDEMPOTENCY_KEY"] = key
    return headers


def select_role(client: APIClient, user: User, role: str):
    return client.post(
        reverse("v1:users-me-initial-role"),
        {"role": role},
        format="json",
        **auth_headers(user),
    )


def ensure_media_assets(user: User, body: dict) -> None:
    references = [
        (
            body["avatar_media_id"],
            MediaAsset.Purpose.PROVIDER_APPLICATION_AVATAR,
        ),
        (
            body["id_card_front_media_id"],
            MediaAsset.Purpose.IDENTITY_CARD_FRONT,
        ),
        (
            body["id_card_back_media_id"],
            MediaAsset.Purpose.IDENTITY_CARD_BACK,
        ),
        *[
            (
                media_id,
                MediaAsset.Purpose.PROVIDER_APPLICATION_LIFE_PHOTO,
            )
            for media_id in body["life_photo_media_ids"]
        ],
    ]
    for media_id, purpose in references:
        MediaAsset.objects.get_or_create(
            owner=user,
            public_id=media_id,
            purpose=purpose,
            defaults={
                "storage_key": f"test/{user.id}/{purpose}/{media_id}",
                "content_type": "image/jpeg",
                "extension": "jpg",
                "byte_size": 1024,
                "width": 800,
                "height": 800,
                "sha256": hashlib.sha256(f"{user.id}:{purpose}:{media_id}".encode()).hexdigest(),
                "request_fingerprint": hashlib.sha256(
                    f"{user.id}:{purpose}:{media_id}:request".encode()
                ).hexdigest(),
            },
        )


def submit_application(client: APIClient, user: User, body=None, key: str | None = None):
    body = body or APPLICATION_BODY
    ensure_media_assets(user, body)
    return client.post(
        reverse("v1:provider-applications"),
        body,
        format="json",
        **auth_headers(user, key),
    )


def approve_identity(user: User, admin: User) -> None:
    """将当前用户的实名认证人工审核通过。"""
    verification = IdentityVerification.objects.get(
        user=user,
        verification_type=IdentityVerification.Type.REAL_NAME,
    )
    review_real_name_verification(
        verification_no=str(verification.verification_no),
        approve=True,
        reason="",
        expected_version=verification.version,
        reviewer=admin,
    )


def test_initial_role_selection_is_idempotent_and_cannot_switch() -> None:
    client = APIClient()
    user = create_user("role-user")

    first = select_role(client, user, "USER")
    replay = select_role(client, user, "USER")
    conflict = select_role(client, user, "PROVIDER")
    me = client.get(reverse("v1:users-me"), **auth_headers(user))

    assert first.status_code == replay.status_code == 200
    assert first.json()["data"]["default_workspace"] == "USER_HOME"
    assert replay.json()["data"]["requires_identity_selection"] is False
    assert conflict.status_code == 409
    assert conflict.json()["code"] == "USER_INITIAL_ROLE_CONFLICT"
    assert me.json()["data"]["primary_role"] == "USER"
    assert me.json()["data"]["current_role"] == "USER"
    assert me.json()["data"]["roles"] == ["USER"]


def test_provider_initial_role_routes_to_onboarding() -> None:
    client = APIClient()
    user = create_user("provider-role-user")

    response = select_role(client, user, "PROVIDER")

    assert response.status_code == 200
    assert response.json()["data"]["default_workspace"] == "PROVIDER_ONBOARDING"
    assert response.json()["data"]["next_route"] == "PROVIDER_ONBOARDING"


def test_approved_provider_role_is_promoted_but_initial_role_remains_user() -> None:
    client = APIClient()
    user = create_user("promote-user-role")
    admin = create_user("promote-role-admin", is_staff=True)
    select_role(client, user, "USER")
    application_no = submit_application(client, user).json()["data"]["application_no"]
    approve_identity(user, admin)
    client.post(
        reverse("v1:admin-provider-application-approve", args=[application_no]),
        {"expected_version": 1},
        format="json",
        **auth_headers(admin),
    )

    me = client.get(reverse("v1:users-me"), **auth_headers(user))
    replay = select_role(client, user, "USER")
    user.refresh_from_db()

    assert me.status_code == replay.status_code == 200
    assert user.initial_role == User.InitialRole.USER
    assert user.primary_role == User.InitialRole.PROVIDER
    assert me.json()["data"]["current_role"] == "PROVIDER"
    assert me.json()["data"]["roles"] == ["USER", "PROVIDER"]
    assert replay.json()["data"]["current_role"] == "PROVIDER"


def test_provider_application_uses_manual_identity_and_does_not_expose_sensitive_data() -> None:
    client = APIClient()
    user = create_user("application-user")
    select_role(client, user, "PROVIDER")

    response = submit_application(client, user)
    content = response.content.decode()

    assert response.status_code == 201
    data = response.json()["data"]
    assert data["status"] == "PENDING"
    assert data["real_name_status"] == "PENDING"
    assert data["face_status"] == "NOT_SUBMITTED"
    assert data["avatar_media"]["media_id"] == AVATAR_MEDIA_ID
    assert data["id_card_front_media"]["media_id"] == ID_CARD_FRONT_MEDIA_ID
    assert data["id_card_back_media"]["media_id"] == ID_CARD_BACK_MEDIA_ID
    assert data["emergency_contact_name"] == EMERGENCY_CONTACT_NAME
    assert data["emergency_contact_phone_masked"] == "139****1234"
    assert len(data["life_photo_media"]) == 3
    assert data["avatar_media"]["display_url"].startswith("http://testserver/api/v1/media/display/")
    assert REAL_NAME not in content
    assert ID_CARD_NUMBER not in content
    assert EMERGENCY_CONTACT_PHONE not in content
    assert "real_name" not in data
    assert "id_card_number" not in data

    application = ProviderApplication.objects.get()
    assert REAL_NAME not in application.real_name_encrypted
    assert ID_CARD_NUMBER not in application.id_card_encrypted
    assert REAL_NAME not in repr(application)
    assert IdentityVerification.objects.filter(user=user).count() == 1
    real_name_verification = IdentityVerification.objects.get(
        user=user,
        verification_type=IdentityVerification.Type.REAL_NAME,
    )
    assert real_name_verification.id_card_front_media_id == ID_CARD_FRONT_MEDIA_ID
    assert real_name_verification.id_card_back_media_id == ID_CARD_BACK_MEDIA_ID
    assert REAL_NAME not in real_name_verification.real_name_encrypted
    assert ID_CARD_NUMBER not in real_name_verification.id_card_number_encrypted
    me_response = client.get(reverse("v1:users-me"), **auth_headers(user))
    me_data = me_response.json()["data"]
    assert me_data["provider_application"]["application_no"] == data["application_no"]
    assert (
        me_data["provider_application"]["avatar_media"]["display_url"]
        == data["avatar_media"]["display_url"]
    )


def test_provider_application_rejects_media_owned_by_another_user() -> None:
    client = APIClient()
    owner = create_user("media-reference-owner")
    applicant = create_user("media-reference-applicant")
    select_role(client, applicant, "USER")
    body = {
        **APPLICATION_BODY,
        "avatar_media_id": str(uuid.UUID(int=20)),
        "life_photo_media_ids": [str(uuid.UUID(int=value)) for value in (21, 22, 23)],
    }
    ensure_media_assets(owner, body)

    response = client.post(
        reverse("v1:provider-applications"),
        body,
        format="json",
        **auth_headers(applicant),
    )

    assert response.status_code == 400
    assert response.json()["code"] == "MEDIA_NOT_FOUND"


def test_provider_application_rejects_id_card_media_with_wrong_purpose() -> None:
    client = APIClient()
    user = create_user("id-card-purpose-applicant")
    select_role(client, user, "USER")
    ensure_media_assets(user, APPLICATION_BODY)
    MediaAsset.objects.filter(
        owner=user,
        public_id=ID_CARD_FRONT_MEDIA_ID,
    ).update(purpose=MediaAsset.Purpose.USER_PROFILE_AVATAR)

    response = client.post(
        reverse("v1:provider-applications"),
        APPLICATION_BODY,
        format="json",
        **auth_headers(user),
    )

    assert response.status_code == 400
    assert response.json()["code"] == "MEDIA_NOT_FOUND"


@override_settings(PROVIDER_APPLICATION_MIN_LIFE_PHOTOS=3)
def test_life_photo_minimum_is_enforced() -> None:
    client = APIClient()
    user = create_user("photo-minimum-user")
    select_role(client, user, "USER")
    body = {
        **APPLICATION_BODY,
        "life_photo_media_ids": LIFE_PHOTO_MEDIA_IDS[:2],
    }

    response = submit_application(client, user, body)

    assert response.status_code == 400
    assert response.json()["code"] == "PROVIDER_APPLICATION_INVALID"
    assert "life_photo_media_ids" in response.json()["details"]


@override_settings(
    PROVIDER_APPLICATION_MIN_LIFE_PHOTOS=2,
    PROVIDER_APPLICATION_MAX_LIFE_PHOTOS=9,
)
def test_life_photo_minimum_is_configurable() -> None:
    client = APIClient()
    user = create_user("photo-config-user")
    select_role(client, user, "USER")
    body = {
        **APPLICATION_BODY,
        "life_photo_media_ids": LIFE_PHOTO_MEDIA_IDS[:2],
    }

    response = submit_application(client, user, body)

    assert response.status_code == 201
    assert len(response.json()["data"]["life_photo_media_ids"]) == 2


def test_duplicate_life_photos_and_invalid_id_card_are_rejected() -> None:
    client = APIClient()
    user = create_user("invalid-input-user")
    select_role(client, user, "USER")

    duplicate = submit_application(
        client,
        user,
        {
            **APPLICATION_BODY,
            "life_photo_media_ids": [
                LIFE_PHOTO_MEDIA_IDS[0],
                LIFE_PHOTO_MEDIA_IDS[0],
                LIFE_PHOTO_MEDIA_IDS[2],
            ],
        },
    )
    invalid_id = submit_application(
        client,
        user,
        {**APPLICATION_BODY, "id_card_number": "110105194912310021"},
    )

    assert duplicate.status_code == invalid_id.status_code == 400
    assert duplicate.json()["details"]["life_photo_media_ids"]
    assert invalid_id.json()["details"]["id_card_number"] == "身份证号格式不正确"


def test_application_idempotency_replays_same_application() -> None:
    client = APIClient()
    user = create_user("idempotent-application-user")
    select_role(client, user, "PROVIDER")

    first = submit_application(client, user, key="application-1")
    replay = submit_application(client, user, key="application-1")
    changed = submit_application(
        client,
        user,
        {**APPLICATION_BODY, "introduction": "这是一份内容不同的申请说明。"},
        key="application-1",
    )

    assert first.status_code == 201
    assert replay.status_code == 200
    assert first.json()["data"]["application_no"] == replay.json()["data"]["application_no"]
    assert changed.status_code == 409
    assert changed.json()["code"] == "AUTH_IDEMPOTENCY_CONFLICT"


def test_idempotency_keys_are_scoped_to_each_user() -> None:
    client = APIClient()
    first_user = create_user("idempotency-owner-1")
    second_user = create_user("idempotency-owner-2")
    select_role(client, first_user, "USER")
    select_role(client, second_user, "USER")

    first = submit_application(client, first_user, key="shared-key")
    second = submit_application(
        client,
        second_user,
        {
            **APPLICATION_BODY,
            "avatar_media_id": str(uuid.UUID(int=10)),
            "id_card_front_media_id": str(uuid.UUID(int=1003)),
            "id_card_back_media_id": str(uuid.UUID(int=1004)),
            "life_photo_media_ids": [str(uuid.UUID(int=value)) for value in (11, 12, 13)],
        },
        key="shared-key",
    )

    assert first.status_code == second.status_code == 201
    assert first.json()["data"]["application_no"] != second.json()["data"]["application_no"]


def test_only_one_active_application_is_allowed_and_database_constraint_backs_it() -> None:
    client = APIClient()
    user = create_user("active-application-user")
    select_role(client, user, "USER")
    assert submit_application(client, user).status_code == 201

    conflict = submit_application(
        client,
        user,
        {**APPLICATION_BODY, "avatar_media_id": str(uuid.UUID(int=5))},
    )

    assert conflict.status_code == 409
    assert conflict.json()["code"] == "PROVIDER_APPLICATION_CONFLICT"
    with pytest.raises(IntegrityError), transaction.atomic():
        ProviderApplication.objects.create(
            application_no=ProviderApplication.make_application_no(),
            user=user,
            status=ProviderApplication.Status.PENDING,
            introduction="数据库约束测试",
            real_name_encrypted="encrypted",
            id_card_encrypted="encrypted",
            id_card_hash="hash",
            avatar_media_id=str(uuid.UUID(int=6)),
            life_photo_media_ids=LIFE_PHOTO_MEDIA_IDS,
            request_fingerprint="different-fingerprint",
        )


def test_regular_user_cannot_access_admin_review_api() -> None:
    client = APIClient()
    user = create_user("regular-review-user")

    response = client.get(reverse("v1:admin-provider-applications"), **auth_headers(user))

    assert response.status_code == 403
    assert response.json()["code"] == "AUTH_PERMISSION_DENIED"


def test_admin_list_and_detail_are_paginated_and_redacted() -> None:
    client = APIClient()
    user = create_user("admin-read-applicant")
    admin = create_user("admin-reader", is_staff=True)
    select_role(client, user, "USER")
    application_no = submit_application(client, user).json()["data"]["application_no"]

    listing = client.get(reverse("v1:admin-provider-applications"), **auth_headers(admin))
    detail = client.get(
        reverse("v1:admin-provider-application-detail", args=[application_no]),
        **auth_headers(admin),
    )
    content = listing.content.decode() + detail.content.decode()

    assert listing.status_code == detail.status_code == 200
    assert listing.json()["meta"]["has_more"] is False
    assert listing.json()["data"][0]["application_no"] == application_no
    assert detail.json()["data"]["user_public_id"] == str(user.public_id)
    assert REAL_NAME not in content
    assert ID_CARD_NUMBER not in content


def test_admin_can_approve_and_application_event_is_recorded() -> None:
    client = APIClient()
    user = create_user("approve-applicant")
    admin = create_user("approve-admin", is_staff=True)
    select_role(client, user, "PROVIDER")
    application_no = submit_application(client, user).json()["data"]["application_no"]
    approve_identity(user, admin)

    response = client.post(
        reverse("v1:admin-provider-application-approve", args=[application_no]),
        {"expected_version": 1},
        format="json",
        **auth_headers(admin),
    )

    assert response.status_code == 200
    assert response.json()["data"]["status"] == "APPROVED"
    user.refresh_from_db()
    assert user.provider_enabled is True
    assert user.provider_status == User.ProviderStatus.APPROVED
    assert user.primary_role == User.InitialRole.PROVIDER
    assert user.default_workspace == User.Workspace.PROVIDER_WORKSPACE
    assert ProviderApplicationEvent.objects.filter(
        event_type=ProviderApplicationEvent.EventType.APPROVED,
        actor=admin,
    ).exists()


def test_admin_rejects_with_reason_then_user_resubmits_with_version_check() -> None:
    client = APIClient()
    user = create_user("reject-applicant")
    admin = create_user("reject-admin", is_staff=True)
    select_role(client, user, "PROVIDER")
    application_no = submit_application(client, user).json()["data"]["application_no"]

    missing_reason = client.post(
        reverse("v1:admin-provider-application-reject", args=[application_no]),
        {"expected_version": 1},
        format="json",
        **auth_headers(admin),
    )
    rejected = client.post(
        reverse("v1:admin-provider-application-reject", args=[application_no]),
        {"expected_version": 1, "reason": "照片不符合要求"},
        format="json",
        **auth_headers(admin),
    )
    stale_update = client.patch(
        reverse("v1:provider-application-me"),
        {**APPLICATION_BODY, "expected_version": 1},
        format="json",
        **auth_headers(user),
    )
    resubmitted = client.patch(
        reverse("v1:provider-application-me"),
        {**APPLICATION_BODY, "expected_version": 2},
        format="json",
        **auth_headers(user),
    )

    assert missing_reason.status_code == 400
    assert rejected.status_code == 200
    assert rejected.json()["data"]["status"] == "REJECTED"
    assert rejected.json()["data"]["reject_reason"] == "照片不符合要求"
    assert stale_update.status_code == 409
    assert stale_update.json()["code"] == "PROVIDER_APPLICATION_VERSION_CONFLICT"
    assert resubmitted.status_code == 200
    assert resubmitted.json()["data"]["status"] == "PENDING"
    assert resubmitted.json()["data"]["version"] == 3
    assert ProviderApplicationEvent.objects.filter(
        event_type=ProviderApplicationEvent.EventType.RESUBMITTED
    ).exists()


def test_review_cannot_be_applied_twice() -> None:
    client = APIClient()
    user = create_user("double-review-applicant")
    admin = create_user("double-review-admin", is_staff=True)
    select_role(client, user, "USER")
    application_no = submit_application(client, user).json()["data"]["application_no"]
    approve_identity(user, admin)
    approve_url = reverse("v1:admin-provider-application-approve", args=[application_no])

    first = client.post(
        approve_url,
        {"expected_version": 1},
        format="json",
        **auth_headers(admin),
    )
    second = client.post(
        approve_url,
        {"expected_version": 2},
        format="json",
        **auth_headers(admin),
    )

    assert first.status_code == 200
    assert second.status_code == 409
    assert second.json()["code"] == "PROVIDER_APPLICATION_STATE_INVALID"


@override_settings(IDENTITY_MOCK_ENABLED=False)
def test_manual_identity_submission_does_not_depend_on_mock_mode() -> None:
    client = APIClient()
    user = create_user("mock-disabled-user")
    select_role(client, user, "USER")

    response = submit_application(client, user)

    assert response.status_code == 201
    assert response.json()["data"]["real_name_status"] == "PENDING"
    assert ProviderApplication.objects.exists()
