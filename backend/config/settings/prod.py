from django.core.exceptions import ImproperlyConfigured

from backend.common.env import get_bool, get_list, get_text, require_envs

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
        "LOCATION_ENCRYPTION_KEY",
        "LOCATION_SELECTION_SIGNING_KEY",
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
if LOCATION_ENCRYPTION_KEY in {"", "dev-only-location-encryption-key-change-me"}:  # noqa: F405
    raise ImproperlyConfigured("生产环境 LOCATION_ENCRYPTION_KEY 不能使用开发默认值。")
if LOCATION_SELECTION_SIGNING_KEY in {  # noqa: F405
    "",
    "dev-only-location-selection-key-change-me",
}:
    raise ImproperlyConfigured("生产环境 LOCATION_SELECTION_SIGNING_KEY 不能使用开发默认值。")
if IDENTITY_MOCK_ENABLED:  # noqa: F405
    raise ImproperlyConfigured("生产环境禁止启用身份认证 Mock。")
if MEDIA_URL_SIGNING_KEY in {"", "dev-only-media-url-signing-key-change-me"}:  # noqa: F405
    raise ImproperlyConfigured("生产环境 MEDIA_URL_SIGNING_KEY 不能使用开发默认值。")
if PAYMENT_MODE == "MOCK_BALANCE" or ENABLE_DEV_WALLET_TOPUP:  # noqa: F405
    raise ImproperlyConfigured("生产环境禁止启用测试余额充值或 MOCK 支付模式。")
if PAYMENT_GATEWAY_MODE not in {"MOCK", "REAL"}:  # noqa: F405
    raise ImproperlyConfigured("PAYMENT_GATEWAY_MODE 只能是 MOCK 或 REAL。")
if PAYMENT_GATEWAY_MODE == "MOCK":  # noqa: F405
    raise ImproperlyConfigured("生产环境禁止使用模拟外部支付渠道。")
conditional_required = []
if PAYMENT_GATEWAY_MODE == "REAL":  # noqa: F405
    conditional_required.extend(
        [
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
        ]
    )
if get_bool("APPLE_LOGIN_ENABLED", True):
    conditional_required.append("APPLE_CLIENT_ID")
if get_bool("WECHAT_LOGIN_ENABLED", True):
    conditional_required.extend(["WECHAT_LOGIN_APP_ID", "WECHAT_LOGIN_APP_SECRET"])
require_envs(conditional_required)
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
