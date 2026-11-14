from __future__ import annotations

import os
import subprocess
import sys

import pytest
from django.core.exceptions import ImproperlyConfigured

from backend.common.env import get_bool, get_int, require_envs


def test_require_envs_reports_all_missing_names(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("FIRST_REQUIRED", raising=False)
    monkeypatch.delenv("SECOND_REQUIRED", raising=False)

    with pytest.raises(ImproperlyConfigured, match="FIRST_REQUIRED、SECOND_REQUIRED"):
        require_envs(["FIRST_REQUIRED", "SECOND_REQUIRED"])


@pytest.mark.parametrize("name,value", [("BOOL_VALUE", "true"), ("BOOL_VALUE", "off")])
def test_boolean_environment_values_are_validated(
    monkeypatch: pytest.MonkeyPatch,
    name: str,
    value: str,
) -> None:
    monkeypatch.setenv(name, value)

    assert get_bool(name) is (value == "true")


def test_invalid_integer_environment_value_fails_clearly(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("INT_VALUE", "not-an-integer")

    with pytest.raises(ImproperlyConfigured, match="INT_VALUE"):
        get_int("INT_VALUE", 10)


def test_production_configuration_rejects_identity_mock() -> None:
    env = {
        **os.environ,
        "DJANGO_ENV": "production",
        "DJANGO_SETTINGS_MODULE": "backend.config.settings.prod",
        "DJANGO_SECRET_KEY": "production-test-secret-key",
        "DJANGO_ALLOWED_HOSTS": "api.example.test",
        "POSTGRES_DB": "test",
        "POSTGRES_USER": "test",
        "POSTGRES_PASSWORD": "test",
        "POSTGRES_HOST": "localhost",
        "REDIS_URL": "redis://localhost:6379/0",
        "CELERY_BROKER_URL": "redis://localhost:6379/1",
        "CELERY_RESULT_BACKEND": "redis://localhost:6379/2",
        "AUTH_TOKEN_SIGNING_KEY": "production-test-token-key",
        "PHONE_HASH_KEY": "production-test-phone-key",
        "CORS_ALLOWED_ORIGINS": "https://app.example.test",
        "IDENTITY_ENCRYPTION_KEY": "production-test-identity-key",
        "LOCATION_ENCRYPTION_KEY": "production-test-location-key",
        "LOCATION_SELECTION_SIGNING_KEY": "production-test-location-signing-key",
        "IDENTITY_MOCK_ENABLED": "true",
        "MEDIA_URL_SIGNING_KEY": "production-test-media-signing-key",
        "PAYMENT_MODE": "REAL",
        "ENABLE_DEV_WALLET_TOPUP": "false",
        "PAYOUT_MODE": "REAL",
        "PAYOUT_VERIFICATION_MODE": "REAL",
        "WITHDRAWAL_MIN_AMOUNT_MINOR": "1000",
    }

    result = subprocess.run(
        [sys.executable, "manage.py", "check"],
        env=env,
        capture_output=True,
        check=False,
        text=True,
    )

    assert result.returncode != 0
    assert "禁止启用身份认证 Mock" in result.stderr


def test_production_configuration_reports_missing_oauth_and_payment_credentials() -> None:
    external_credential_names = (
        "WECHAT_PAY_MCH_ID",
        "WECHAT_PAY_APP_ID",
        "WECHAT_PAY_API_V3_KEY",
        "WECHAT_PAY_MERCHANT_SERIAL_NO",
        "WECHAT_PAY_PRIVATE_KEY",
        "WECHAT_PAY_PLATFORM_PUBLIC_KEY",
        "WECHAT_PAY_PLATFORM_PUBLIC_KEY_ID",
        "WECHAT_PAY_NOTIFY_URL",
        "ALIPAY_APP_ID",
        "ALIPAY_PRIVATE_KEY",
        "ALIPAY_PUBLIC_KEY",
        "ALIPAY_NOTIFY_URL",
        "APPLE_CLIENT_ID",
        "WECHAT_LOGIN_APP_ID",
        "WECHAT_LOGIN_APP_SECRET",
    )
    env = {
        **os.environ,
        **dict.fromkeys(external_credential_names, ""),
        "DJANGO_ENV": "production",
        "DJANGO_SETTINGS_MODULE": "backend.config.settings.prod",
        "DJANGO_SECRET_KEY": "production-test-secret-key",
        "DJANGO_ALLOWED_HOSTS": "api.example.test",
        "POSTGRES_DB": "test",
        "POSTGRES_USER": "test",
        "POSTGRES_PASSWORD": "test",
        "POSTGRES_HOST": "localhost",
        "REDIS_URL": "redis://localhost:6379/0",
        "CELERY_BROKER_URL": "redis://localhost:6379/1",
        "CELERY_RESULT_BACKEND": "redis://localhost:6379/2",
        "AUTH_TOKEN_SIGNING_KEY": "production-test-token-key",
        "PHONE_HASH_KEY": "production-test-phone-key",
        "CORS_ALLOWED_ORIGINS": "https://app.example.test",
        "IDENTITY_ENCRYPTION_KEY": "production-test-identity-key",
        "LOCATION_ENCRYPTION_KEY": "production-test-location-key",
        "LOCATION_SELECTION_SIGNING_KEY": "production-test-location-signing-key",
        "IDENTITY_MOCK_ENABLED": "false",
        "MEDIA_URL_SIGNING_KEY": "production-test-media-signing-key",
        "PAYMENT_MODE": "REAL",
        "PAYMENT_GATEWAY_MODE": "REAL",
        "ENABLE_DEV_WALLET_TOPUP": "false",
        "PAYOUT_MODE": "REAL",
        "PAYOUT_VERIFICATION_MODE": "REAL",
        "WITHDRAWAL_MIN_AMOUNT_MINOR": "1000",
    }

    result = subprocess.run(
        [sys.executable, "manage.py", "check"],
        env=env,
        capture_output=True,
        check=False,
        text=True,
    )

    assert result.returncode != 0
    assert "WECHAT_PAY_MCH_ID" in result.stderr
    assert "ALIPAY_APP_ID" in result.stderr
    assert "APPLE_CLIENT_ID" in result.stderr
    assert "WECHAT_LOGIN_APP_SECRET" in result.stderr
