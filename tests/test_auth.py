from __future__ import annotations

import uuid
from datetime import timedelta

import pytest
from django.contrib.auth.hashers import make_password
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from backend.accounts.models import AuthToken, User, VerificationCode
from backend.accounts.services import _token_raw, hash_phone, hash_token
from backend.common.crypto import decrypt_text

pytestmark = pytest.mark.django_db


PHONE = "13800138000"


def _send(client: APIClient, key: str | None = None, phone: str = PHONE):
    headers = {"HTTP_IDEMPOTENCY_KEY": key} if key else {}
    return client.post(reverse("v1:auth-sms-code"), {"phone": phone}, format="json", **headers)


def _login(client: APIClient, code: str, key: str | None = None, phone: str = PHONE):
    headers = {"HTTP_IDEMPOTENCY_KEY": key} if key else {}
    return client.post(
        reverse("v1:auth-login"),
        {"phone": phone, "code": code},
        format="json",
        **headers,
    )


def _password_login(
    client: APIClient,
    *,
    phone: str = PHONE,
    password: str = "DevLogin!2026",
    key: str | None = None,
):
    headers = {"HTTP_IDEMPOTENCY_KEY": key} if key else {}
    return client.post(
        reverse("v1:auth-dev-password-login"),
        {"phone": phone, "password": password},
        format="json",
        **headers,
    )


@override_settings(DEV_PASSWORD_LOGIN_ENABLED=True)
def test_dev_password_login_returns_standard_bearer_tokens() -> None:
    user = User.objects.create(
        phone_hash=hash_phone(PHONE),
        phone_masked="138****8000",
        password=make_password("DevLogin!2026"),
        status=User.Status.ACTIVE,
        initial_role_selected=True,
    )
    client = APIClient()

    response = _password_login(client)
    data = response.json()["data"]

    assert response.status_code == 200
    assert data["token_type"] == "Bearer"
    assert data["access_token"]
    assert data["refresh_token"]
    assert data["user_public_id"] == str(user.public_id)
    assert "password" not in response.content.decode()
    me_response = client.get(
        reverse("v1:users-me"),
        HTTP_AUTHORIZATION=f"Bearer {data['access_token']}",
    )
    assert me_response.status_code == 200


@override_settings(DEV_PASSWORD_LOGIN_ENABLED=True)
def test_dev_password_login_rejects_wrong_or_missing_password() -> None:
    User.objects.create(
        phone_hash=hash_phone(PHONE),
        phone_masked="138****8000",
        password=make_password("DevLogin!2026"),
        status=User.Status.ACTIVE,
    )

    wrong_password = _password_login(APIClient(), password="wrong-password")
    unknown_account = _password_login(APIClient(), phone="13800138001")

    assert wrong_password.status_code == 401
    assert wrong_password.json()["code"] == "AUTH_INVALID_CREDENTIALS"
    assert unknown_account.status_code == 401
    assert unknown_account.json()["code"] == "AUTH_INVALID_CREDENTIALS"
    assert AuthToken.objects.count() == 0


@override_settings(DEV_PASSWORD_LOGIN_ENABLED=True)
def test_dev_password_login_supports_idempotent_token_replay() -> None:
    User.objects.create(
        phone_hash=hash_phone(PHONE),
        phone_masked="138****8000",
        password=make_password("DevLogin!2026"),
        status=User.Status.ACTIVE,
    )
    client = APIClient()

    first = _password_login(client, key="dev-password-login")
    replay = _password_login(client, key="dev-password-login")
    conflict = _password_login(client, key="dev-password-login", password="another-password")

    assert first.status_code == 200
    assert replay.status_code == 200
    assert replay.json()["data"]["access_token"] == first.json()["data"]["access_token"]
    assert replay.json()["data"]["refresh_token"] == first.json()["data"]["refresh_token"]
    assert conflict.status_code == 409
    assert conflict.json()["code"] == "AUTH_IDEMPOTENCY_CONFLICT"


@override_settings(DEV_PASSWORD_LOGIN_ENABLED=False)
def test_dev_password_login_is_hidden_when_disabled() -> None:
    response = _password_login(APIClient())

    assert response.status_code == 404
    assert response.json()["code"] == "SYSTEM_NOT_FOUND"
    assert AuthToken.objects.count() == 0


@override_settings(SMS_CODE_RESEND_SECONDS=0)
def test_sms_code_is_mocked_and_login_auto_registers_user() -> None:
    client = APIClient()

    send_response = _send(client)

    assert send_response.status_code == 200
    send_data = send_response.json()["data"]
    assert send_data["debug_code"].isdigit()
    assert len(send_data["debug_code"]) == 6
    assert PHONE not in send_response.content.decode()

    login_response = _login(client, send_data["debug_code"])

    assert login_response.status_code == 200
    login_data = login_response.json()["data"]
    assert login_data["is_new_user"] is True
    assert login_data["requires_identity_selection"] is True
    assert login_data["access_token"]
    assert login_data["refresh_token"]
    assert login_data["user_public_id"]
    assert "user_id" not in login_data
    assert User.objects.count() == 1
    assert decrypt_text(User.objects.get().phone_encrypted) == PHONE

    me_response = client.get(
        reverse("v1:users-me"),
        HTTP_AUTHORIZATION=f"Bearer {login_data['access_token']}",
    )
    assert me_response.status_code == 200
    assert me_response.json()["data"]["phone_masked"] == "138****8000"
    assert me_response.json()["data"]["requires_identity_selection"] is True


def test_invalid_phone_uses_stable_error() -> None:
    response = _send(APIClient(), phone="123")

    assert response.status_code == 400
    assert response.json()["code"] == "AUTH_INVALID_PHONE"


@override_settings(SMS_MOCK_ENABLED=False)
def test_sms_mock_is_disabled_explicitly() -> None:
    response = _send(APIClient())

    assert response.status_code == 503
    assert response.json()["code"] == "AUTH_SMS_UNAVAILABLE"
    assert "debug_code" not in response.content.decode()


@override_settings(SMS_CODE_RESEND_SECONDS=0)
def test_verification_code_is_not_persisted_as_plaintext() -> None:
    client = APIClient()
    debug_code = _send(client).json()["data"]["debug_code"]

    stored = VerificationCode.objects.get()
    assert stored.code_hash != debug_code
    assert debug_code not in repr(stored)


@override_settings(SMS_CODE_RESEND_SECONDS=0)
def test_sms_code_idempotency_replays_same_debug_code() -> None:
    client = APIClient()

    first = _send(client, key="sms-1")
    second = _send(client, key="sms-1")

    assert first.status_code == second.status_code == 200
    assert first.json()["data"]["debug_code"] == second.json()["data"]["debug_code"]
    assert second.json()["data"]["reused"] is True


def test_sms_code_idempotency_key_rejects_changed_request() -> None:
    client = APIClient()

    first = _send(client, key="same-key", phone=PHONE)
    second = _send(client, key="same-key", phone="13900139000")

    assert first.status_code == 200
    assert second.status_code == 409
    assert second.json()["code"] == "AUTH_IDEMPOTENCY_CONFLICT"


def test_sms_code_resend_rate_limit() -> None:
    client = APIClient()

    first = _send(client)
    second = _send(client)

    assert first.status_code == 200
    assert second.status_code == 429
    assert second.json()["code"] == "AUTH_CODE_RESEND_TOO_EARLY"


@override_settings(SMS_CODE_RESEND_SECONDS=0)
def test_code_is_single_use_and_login_is_idempotent() -> None:
    client = APIClient()
    code = _send(client).json()["data"]["debug_code"]

    first = _login(client, code, key="login-1")
    replay = _login(client, code, key="login-1")
    rejected = _login(client, code)

    assert first.status_code == 200
    assert replay.status_code == 200
    assert first.json()["data"]["access_token"] == replay.json()["data"]["access_token"]
    assert rejected.status_code == 409
    assert rejected.json()["code"] == "AUTH_CODE_CONSUMED"


@override_settings(SMS_CODE_RESEND_SECONDS=0)
def test_existing_user_login_does_not_create_duplicate_user() -> None:
    client = APIClient()
    first_code = _send(client).json()["data"]["debug_code"]
    first_login = _login(client, first_code)
    second_code = _send(client).json()["data"]["debug_code"]
    second_login = _login(client, second_code)

    assert first_login.status_code == second_login.status_code == 200
    assert second_login.json()["data"]["is_new_user"] is False
    assert User.objects.count() == 1


@override_settings(SMS_CODE_RESEND_SECONDS=0)
def test_wrong_code_counts_attempts_and_rejects_expired_code() -> None:
    client = APIClient()
    code = _send(client).json()["data"]["debug_code"]
    wrong = "000000" if code != "000000" else "111111"

    response = _login(client, wrong)
    assert response.status_code == 400
    assert response.json()["code"] == "AUTH_CODE_INVALID"
    assert VerificationCode.objects.get().attempts == 1

    VerificationCode.objects.update(expires_at=timezone.now() - timedelta(seconds=1))
    response = _login(client, code)
    assert response.status_code == 400
    assert response.json()["code"] == "AUTH_CODE_EXPIRED"


@override_settings(SMS_CODE_RESEND_SECONDS=0)
def test_max_attempts_is_enforced() -> None:
    client = APIClient()
    code = _send(client).json()["data"]["debug_code"]
    wrong = "000000" if code != "000000" else "111111"

    for _ in range(5):
        assert _login(client, wrong).json()["code"] == "AUTH_CODE_INVALID"
    response = _login(client, code)
    assert response.status_code == 423
    assert response.json()["code"] == "AUTH_CODE_ATTEMPTS_EXCEEDED"


@override_settings(SMS_CODE_RESEND_SECONDS=0)
def test_refresh_rotates_tokens_and_invalidates_old_refresh_token() -> None:
    client = APIClient()
    code = _send(client).json()["data"]["debug_code"]
    login_data = _login(client, code).json()["data"]

    refresh_response = client.post(
        reverse("v1:auth-refresh"),
        {"refresh_token": login_data["refresh_token"]},
        format="json",
    )
    assert refresh_response.status_code == 200
    rotated = refresh_response.json()["data"]
    assert rotated["access_token"] != login_data["access_token"]
    assert rotated["refresh_token"] != login_data["refresh_token"]

    old_access = client.get(
        reverse("v1:users-me"),
        HTTP_AUTHORIZATION=f"Bearer {login_data['access_token']}",
    )
    assert old_access.status_code == 401
    old_refresh = client.post(
        reverse("v1:auth-refresh"),
        {"refresh_token": login_data["refresh_token"]},
        format="json",
    )
    assert old_refresh.status_code == 401


@override_settings(SMS_CODE_RESEND_SECONDS=0)
def test_logout_revokes_only_the_current_session() -> None:
    client = APIClient()
    first_code = _send(client).json()["data"]["debug_code"]
    first_login = _login(client, first_code).json()["data"]
    second_code = _send(client).json()["data"]["debug_code"]
    second_login = _login(client, second_code).json()["data"]

    logout_response = client.post(
        reverse("v1:auth-logout"),
        HTTP_AUTHORIZATION=f"Bearer {first_login['access_token']}",
    )
    old_access = client.get(
        reverse("v1:users-me"),
        HTTP_AUTHORIZATION=f"Bearer {first_login['access_token']}",
    )
    old_refresh = client.post(
        reverse("v1:auth-refresh"),
        {"refresh_token": first_login["refresh_token"]},
        format="json",
    )
    other_session = client.get(
        reverse("v1:users-me"),
        HTTP_AUTHORIZATION=f"Bearer {second_login['access_token']}",
    )

    assert logout_response.status_code == 200
    assert logout_response.json()["data"] == {"logged_out": True}
    assert old_access.status_code == 401
    assert old_refresh.status_code == 401
    assert other_session.status_code == 200


def test_logout_requires_authentication() -> None:
    response = APIClient().post(reverse("v1:auth-logout"))

    assert response.status_code == 401
    assert response.json()["code"] == "AUTH_AUTHENTICATION_REQUIRED"


def test_invalid_and_expired_tokens_are_rejected() -> None:
    client = APIClient()
    invalid = client.get(
        reverse("v1:users-me"),
        HTTP_AUTHORIZATION="Bearer invalid-token",
    )
    assert invalid.status_code == 401
    assert invalid.json()["code"] == "AUTH_TOKEN_INVALID"

    user = User.objects.create(phone_hash="hash", phone_masked="138****8000")
    token_id = uuid.uuid4()
    raw_token = _token_raw(AuthToken.TokenType.ACCESS, token_id)
    token = AuthToken.objects.create(
        public_id=token_id,
        user=user,
        token_type=AuthToken.TokenType.ACCESS,
        token_hash=hash_token(raw_token),
        expires_at=timezone.now() - timedelta(seconds=1),
    )
    assert token.expires_at < timezone.now()

    expired = client.get(
        reverse("v1:users-me"),
        HTTP_AUTHORIZATION=f"Bearer {raw_token}",
    )
    assert expired.status_code == 401
    assert expired.json()["code"] == "AUTH_TOKEN_EXPIRED"


@override_settings(SMS_CODE_RESEND_SECONDS=0)
def test_unique_auth_identifier_is_database_backed() -> None:
    from django.db import IntegrityError, transaction

    from backend.accounts.models import UserAuth

    user = User.objects.create(phone_hash="unique-phone-hash", phone_masked="138****8000")
    UserAuth.objects.create(
        user=user,
        auth_type=UserAuth.Type.PHONE,
        auth_identifier="unique-phone-hash",
    )
    with pytest.raises(IntegrityError), transaction.atomic():
        UserAuth.objects.create(
            user=user,
            auth_type=UserAuth.Type.PHONE,
            auth_identifier="unique-phone-hash",
        )
