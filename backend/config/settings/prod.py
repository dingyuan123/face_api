from django.core.exceptions import ImproperlyConfigured

from backend.common.env import get_list, get_text, require_envs

from .base import *  # noqa: F403

require_envs(
    [
        "DJANGO_SECRET_KEY",
        "DJANGO_ALLOWED_HOSTS",
        "POSTGRES_DB",
        "POSTGRES_USER",
        "POSTGRES_PASSWORD",
        "POSTGRES_HOST",
        "REDIS_URL",
        "CELERY_BROKER_URL",
        "CELERY_RESULT_BACKEND",
        "AUTH_TOKEN_SIGNING_KEY",
        "PHONE_HASH_KEY",
        "CORS_ALLOWED_ORIGINS",
        "IDENTITY_ENCRYPTION_KEY",
        "MEDIA_URL_SIGNING_KEY",
        "PAYMENT_MODE",
        "PAYOUT_MODE",
        "PAYOUT_VERIFICATION_MODE",
        "WITHDRAWAL_MIN_AMOUNT_MINOR",
    ]
)

DEBUG = False
SECRET_KEY = get_text("DJANGO_SECRET_KEY") or ""
if SECRET_KEY in {"", "dev-only-secret-key-change-me"}:
    raise ImproperlyConfigured("生产环境 DJANGO_SECRET_KEY 不能使用开发默认值。")

SMS_MOCK_ENABLED = False
if AUTH_TOKEN_SIGNING_KEY in {"", "dev-only-token-signing-key"}:  # noqa: F405
    raise ImproperlyConfigured("生产环境 AUTH_TOKEN_SIGNING_KEY 不能使用开发默认值。")
if PHONE_HASH_KEY in {"", "dev-only-phone-hash-key"}:  # noqa: F405
    raise ImproperlyConfigured("生产环境 PHONE_HASH_KEY 不能使用开发默认值。")
if IDENTITY_ENCRYPTION_KEY in {"", "dev-only-identity-encryption-key-change-me"}:  # noqa: F405
    raise ImproperlyConfigured("生产环境 IDENTITY_ENCRYPTION_KEY 不能使用开发默认值。")
if IDENTITY_MOCK_ENABLED:  # noqa: F405
    raise ImproperlyConfigured("生产环境禁止启用身份认证 Mock。")
if MEDIA_URL_SIGNING_KEY in {"", "dev-only-media-url-signing-key-change-me"}:  # noqa: F405
    raise ImproperlyConfigured("生产环境 MEDIA_URL_SIGNING_KEY 不能使用开发默认值。")
if PAYMENT_MODE == "MOCK_BALANCE" or ENABLE_DEV_WALLET_TOPUP:  # noqa: F405
    raise ImproperlyConfigured("生产环境禁止启用测试余额充值或 MOCK 支付模式。")
if PAYOUT_MODE != "REAL" or PAYOUT_VERIFICATION_MODE != "REAL":  # noqa: F405
    raise ImproperlyConfigured("生产环境禁止使用模拟收款验证或模拟打款。")

ALLOWED_HOSTS = get_list("DJANGO_ALLOWED_HOSTS")
CSRF_TRUSTED_ORIGINS = get_list("DJANGO_CSRF_TRUSTED_ORIGINS")
if not ALLOWED_HOSTS:
    raise ImproperlyConfigured("生产环境 DJANGO_ALLOWED_HOSTS 不能为空。")
if CORS_ALLOW_ALL_ORIGINS:  # noqa: F405
    raise ImproperlyConfigured("生产环境禁止 CORS_ALLOW_ALL_ORIGINS=true。")
if not CORS_ALLOWED_ORIGINS:  # noqa: F405
    raise ImproperlyConfigured("生产环境必须配置 CORS_ALLOWED_ORIGINS。")

SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_SSL_REDIRECT = True
SECURE_HSTS_SECONDS = 31536000
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
