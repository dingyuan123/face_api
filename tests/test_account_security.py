"""账号密码、忘记密码和更换手机号 API 测试。"""

from __future__ import annotations

import sys
import types

import pytest
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from backend.accounts.models import (
    AccountSecurityEvent,
    PasswordLoginAttempt,
    User,
    UserAuth,
    VerificationCode,
    VerificationSendGuard,
)
from backend.accounts.services import (
    encrypt_text,
    hash_phone,
    mask_phone,
    send_sms_code,
)
from tests.test_booking_flow import auth_headers, create_user

pytestmark = pytest.mark.django_db


def _bind_phone(user: User, phone: str) -> None:
    user.phone_hash = hash_phone(phone)
    user.phone_masked = mask_phone(phone)
    user.phone_encrypted = encrypt_text(phone)
    user.save(update_fields=["phone_hash", "phone_masked", "phone_encrypted"])
    UserAuth.objects.create(
        user=user,
        auth_type=UserAuth.Type.PHONE,
        auth_identifier=hash_phone(phone),
    )


def _allow_immediate_sms(phone: str) -> None:
    """测试中跳过真实的 60 秒短信频率等待。"""
    VerificationSendGuard.objects.filter(phone_hash=hash_phone(phone)).update(
        next_allowed_at=timezone.now()
    )


@override_settings(
    SMS_MOCK_ENABLED=True,
    DEV_PASSWORD_LOGIN_ENABLED=True,
)
def test_password_set_change_reset_and_phone_change() -> None:
    client = APIClient()
    user = create_user("account-security-user")
    _bind_phone(user, "13800001111")
    headers = auth_headers(user)

    set_sms = client.post(
        reverse("v1:users-me-password-sms-code"),
        format="json",
        **headers,
    )
    first_set = client.post(
        reverse("v1:users-me-password"),
        {
            "new_password": "Aa1234567",
            "code": set_sms.json()["data"]["debug_code"],
        },
        format="json",
        **headers,
    )
    assert first_set.status_code == 200, first_set.json()
    _allow_immediate_sms("13800001111")
    change_sms = client.post(
        reverse("v1:users-me-password-sms-code"),
        format="json",
        **headers,
    )
    changed = client.post(
        reverse("v1:users-me-password"),
        {
            "current_password": "Aa1234567",
            "new_password": "Bb2345678",
            "code": change_sms.json()["data"]["debug_code"],
        },
        format="json",
        **headers,
    )
    _allow_immediate_sms("13800001111")
    _allow_immediate_sms("13800002222")
    phone_request = client.post(
        reverse("v1:users-me-phone-change"),
        {"new_phone": "13800002222"},
        format="json",
        **headers,
    )
    phone_confirmed = client.post(
        reverse("v1:users-me-phone-change-confirm"),
        {
            "request_no": phone_request.json()["data"]["request_no"],
            "old_code": phone_request.json()["data"]["old_debug_code"],
            "new_code": phone_request.json()["data"]["new_debug_code"],
        },
        format="json",
        **headers,
    )
    password_login = client.post(
        reverse("v1:auth-dev-password-login"),
        {
            "phone": "13800002222",
            "password": "Bb2345678",
        },
        format="json",
    )

    assert first_set.status_code == 200
    assert first_set.json()["data"]["password_set"] is True
    assert changed.status_code == 200
    assert changed.json()["data"]["password_changed"] is True
    assert phone_request.status_code == 200
    assert phone_confirmed.status_code == 200
    assert password_login.status_code == 200
    user.refresh_from_db()
    assert user.phone_masked == mask_phone("13800002222")
    assert user.check_password("Bb2345678")
    assert (
        AccountSecurityEvent.objects.filter(
            user=user,
            event_type="PASSWORD_SET",
        ).count()
        == 1
    )
    assert (
        AccountSecurityEvent.objects.filter(
            user=user,
            event_type="PHONE_CHANGED",
        ).count()
        == 1
    )


@override_settings(
    SMS_MOCK_ENABLED=True,
    DEV_PASSWORD_LOGIN_ENABLED=True,
)
def test_password_reset_revokes_sessions_and_rejects_invalid_codes() -> None:
    client = APIClient()
    user = create_user("account-reset-user")
    _bind_phone(user, "13800003333")
    headers = auth_headers(user)
    forgot = client.post(
        reverse("v1:auth-password-forgot-sms-code"),
        {"phone": "13800003333"},
        format="json",
    )
    invalid = client.post(
        reverse("v1:auth-password-reset"),
        {
            "phone": "13800003333",
            "code": "000000",
            "new_password": "Cc3456789",
        },
        format="json",
    )
    reset = client.post(
        reverse("v1:auth-password-reset"),
        {
            "phone": "13800003333",
            "code": forgot.json()["data"]["debug_code"],
            "new_password": "Cc3456789",
        },
        format="json",
    )
    reused_session = client.get(reverse("v1:users-me"), **headers)

    assert forgot.status_code == 200
    assert invalid.status_code == 400
    assert reset.status_code == 200
    assert reset.json()["data"]["password_reset"] is True
    assert reused_session.status_code == 401
    user.refresh_from_db()
    assert user.check_password("Cc3456789")


def test_phone_change_rejects_number_already_bound() -> None:
    client = APIClient()
    user = create_user("account-phone-change-source")
    target = create_user("account-phone-change-target")
    _bind_phone(user, "13800004444")
    _bind_phone(target, "13800005555")
    headers = auth_headers(user)

    response = client.post(
        reverse("v1:users-me-phone-change"),
        {"new_phone": "13800005555"},
        format="json",
        **headers,
    )

    assert response.status_code == 409
    assert response.json()["code"] == "AUTH_PHONE_ALREADY_BOUND"


@override_settings(
    SMS_PROVIDER="ALIYUN",
    SMS_MOCK_ENABLED=False,
)
def test_aliyun_sms_provider_sends_real_code(monkeypatch) -> None:
    sent = {}

    class FakeAliyunGateway:
        def send_sms(self, *, phone: str, code: str):
            sent["phone"] = phone
            sent["code"] = code
            return object()

    fake_module = types.ModuleType("backend.integrations.sms.aliyun")
    fake_module.AliyunSmsGateway = FakeAliyunGateway
    monkeypatch.setitem(
        sys.modules,
        "backend.integrations.sms.aliyun",
        fake_module,
    )
    user = create_user("account-aliyun-sms")
    _bind_phone(user, "13800008888")

    result = send_sms_code(
        phone_value="13800008888",
        purpose=VerificationCode.Purpose.LOGIN,
    )

    assert result.debug_code is None
    assert sent["phone"] == "13800008888"
    assert sent["code"].isdigit()
    assert len(sent["code"]) == 6


@override_settings(
    SMS_MOCK_ENABLED=True,
    DEV_PASSWORD_LOGIN_ENABLED=False,
)
def test_production_password_login_and_failure_lock() -> None:
    client = APIClient()
    user = create_user("account-production-login")
    _bind_phone(user, "13800006666")
    headers = auth_headers(user)
    sms = client.post(
        reverse("v1:users-me-password-sms-code"),
        format="json",
        **headers,
    )
    set_password = client.post(
        reverse("v1:users-me-password"),
        {
            "new_password": "Aa1234567",
            "code": sms.json()["data"]["debug_code"],
        },
        format="json",
        **headers,
    )
    login = client.post(
        reverse("v1:auth-password-login"),
        {
            "phone": "13800006666",
            "password": "Aa1234567",
            "referral_context": {"invite_code": "TESTCODE"},
        },
        format="json",
        HTTP_IDEMPOTENCY_KEY="production-password-login",
    )
    replay = client.post(
        reverse("v1:auth-password-login"),
        {
            "phone": "13800006666",
            "password": "Aa1234567",
            "referral_context": {"invite_code": "TESTCODE"},
        },
        format="json",
        HTTP_IDEMPOTENCY_KEY="production-password-login",
    )

    locked_phone = "13800007777"
    failure_responses = []
    for _ in range(5):
        failure_responses.append(
            client.post(
                reverse("v1:auth-password-login"),
                {"phone": locked_phone, "password": "WrongPassword1"},
                format="json",
            )
        )
    attempt = PasswordLoginAttempt.objects.filter(phone_hash=hash_phone(locked_phone)).first()
    assert attempt is not None, (
        [(item.status_code, item.json()) for item in failure_responses],
        list(PasswordLoginAttempt.objects.values("phone_hash", "failed_count")),
    )
    assert attempt.failed_count >= 5, (attempt.failed_count, attempt.locked_until)
    locked = client.post(
        reverse("v1:auth-password-login"),
        {"phone": locked_phone, "password": "WrongPassword1"},
        format="json",
    )

    assert set_password.status_code == 200
    assert login.status_code == 200
    assert login.json()["data"]["access_token"]
    assert login.json()["data"]["requires_phone_binding"] is False
    assert replay.status_code == 200
    assert replay.json()["data"]["access_token"] == login.json()["data"]["access_token"]
    assert locked.status_code == 423
    assert locked.json()["code"] == "AUTH_LOGIN_LOCKED"
