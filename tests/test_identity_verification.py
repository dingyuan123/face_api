"""普通用户实名认证提交和人工审核接口测试。"""

from __future__ import annotations

import hashlib
import uuid
from datetime import timedelta

import pytest
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from backend.accounts.models import AuthToken, User
from backend.accounts.services import _token_raw, hash_token
from backend.identity.models import IdentityVerification
from backend.media.models import MediaAsset

pytestmark = pytest.mark.django_db

REAL_NAME = "李四"
ID_CARD_NUMBER = "11010519491231002X"
FRONT_MEDIA_ID = str(uuid.UUID(int=2001))
BACK_MEDIA_ID = str(uuid.UUID(int=2002))


def create_user(phone_hash: str, *, is_staff: bool = False) -> User:
    return User.objects.create(
        phone_hash=phone_hash,
        phone_masked="138****8000",
        is_staff=is_staff,
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


def create_identity_media(user: User) -> None:
    for media_id, purpose in (
        (FRONT_MEDIA_ID, MediaAsset.Purpose.IDENTITY_CARD_FRONT),
        (BACK_MEDIA_ID, MediaAsset.Purpose.IDENTITY_CARD_BACK),
    ):
        MediaAsset.objects.create(
            public_id=media_id,
            owner=user,
            purpose=purpose,
            storage_key=f"test/identity/{user.id}/{media_id}",
            content_type="image/jpeg",
            extension="jpg",
            byte_size=1024,
            width=800,
            height=800,
            sha256=hashlib.sha256(f"{user.id}:{media_id}".encode()).hexdigest(),
            request_fingerprint=hashlib.sha256(
                f"{user.id}:{media_id}:request".encode()
            ).hexdigest(),
        )


def submit_body() -> dict[str, str]:
    return {
        "real_name": REAL_NAME,
        "id_card_number": ID_CARD_NUMBER,
        "id_card_front_media_id": FRONT_MEDIA_ID,
        "id_card_back_media_id": BACK_MEDIA_ID,
    }


def test_user_can_submit_real_name_and_admin_can_approve_it() -> None:
    client = APIClient()
    user = create_user("identity-submit-user")
    admin = create_user("identity-submit-admin", is_staff=True)
    create_identity_media(user)

    submitted = client.post(
        reverse("v1:identity-real-name-submit"),
        submit_body(),
        format="json",
        **auth_headers(user),
    )
    mine = client.get(reverse("v1:identity-real-name-me"), **auth_headers(user))
    listing = client.get(reverse("v1:admin-identity-verifications"), **auth_headers(admin))
    verification_no = mine.json()["data"]["verification_no"]
    approved = client.post(
        reverse(
            "v1:admin-identity-verification-review",
            args=[verification_no, "approve"],
        ),
        {"expected_version": 1},
        format="json",
        **auth_headers(admin),
    )

    assert submitted.status_code == 201
    assert submitted.json()["data"]["status"] == "PENDING"
    assert mine.status_code == 200
    assert mine.json()["data"]["id_card_front_media"]["media_id"] == FRONT_MEDIA_ID
    assert REAL_NAME not in submitted.content.decode()
    assert ID_CARD_NUMBER not in submitted.content.decode()
    assert listing.status_code == 200
    assert listing.json()["data"]["items"][0]["status"] == "PENDING"
    assert approved.status_code == 200
    assert approved.json()["data"]["status"] == "PASSED"


def test_rejected_identity_can_be_resubmitted_with_version_check() -> None:
    client = APIClient()
    user = create_user("identity-resubmit-user")
    admin = create_user("identity-resubmit-admin", is_staff=True)
    create_identity_media(user)
    submitted = client.post(
        reverse("v1:identity-real-name-submit"),
        submit_body(),
        format="json",
        **auth_headers(user),
    )
    verification_no = submitted.json()["data"]["verification_no"]
    rejected = client.post(
        reverse(
            "v1:admin-identity-verification-review",
            args=[verification_no, "reject"],
        ),
        {"expected_version": 1, "reason": "照片不清晰"},
        format="json",
        **auth_headers(admin),
    )
    stale = client.post(
        reverse("v1:identity-real-name-submit"),
        {**submit_body(), "expected_version": 1},
        format="json",
        **auth_headers(user),
    )
    resubmitted = client.post(
        reverse("v1:identity-real-name-submit"),
        {**submit_body(), "expected_version": 2},
        format="json",
        **auth_headers(user),
    )

    assert rejected.status_code == 200
    assert rejected.json()["data"]["status"] == "REJECTED"
    assert stale.status_code == 409
    assert stale.json()["code"] == "IDENTITY_VERIFICATION_VERSION_CONFLICT"
    assert resubmitted.status_code == 201
    assert resubmitted.json()["data"]["status"] == "PENDING"


def test_identity_requires_owned_purpose_specific_media() -> None:
    client = APIClient()
    user = create_user("identity-media-user")
    other = create_user("identity-media-other")
    create_identity_media(other)

    response = client.post(
        reverse("v1:identity-real-name-submit"),
        submit_body(),
        format="json",
        **auth_headers(user),
    )

    assert response.status_code == 400
    assert response.json()["code"] == "MEDIA_NOT_FOUND"
    assert not IdentityVerification.objects.filter(user=user).exists()
