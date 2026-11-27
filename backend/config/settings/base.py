from __future__ import annotations

from datetime import timedelta
from pathlib import Path

from backend.common.env import get_bool, get_int, get_list, get_text, load_environment

PROJECT_ROOT = Path(__file__).resolve().parents[3]
BACKEND_ROOT = Path(__file__).resolve().parents[2]

load_environment(PROJECT_ROOT / ".env")

ENVIRONMENT = get_text("DJANGO_ENV", "development") or "development"
ADMIN_CAPTCHA_ENABLED = get_bool("ADMIN_CAPTCHA_ENABLED", ENVIRONMENT != "production")
APP_VERSION = get_text("APP_VERSION", "0.1.0") or "0.1.0"
SECRET_KEY = get_text("DJANGO_SECRET_KEY", "dev-only-secret-key-change-me") or ""
DEBUG = get_bool("DJANGO_DEBUG", ENVIRONMENT != "production")
ALLOWED_HOSTS = get_list("DJANGO_ALLOWED_HOSTS", ["localhost", "127.0.0.1", "testserver"])
CSRF_TRUSTED_ORIGINS = get_list("DJANGO_CSRF_TRUSTED_ORIGINS", [])
CORS_ALLOWED_ORIGINS = get_list("CORS_ALLOWED_ORIGINS", [])
CORS_ALLOW_ALL_ORIGINS = get_bool(
    "CORS_ALLOW_ALL_ORIGINS",
    ENVIRONMENT != "production" and not CORS_ALLOWED_ORIGINS,
)
CORS_ALLOW_CREDENTIALS = get_bool("CORS_ALLOW_CREDENTIALS", False)
CORS_ALLOW_HEADERS = [
    "accept",
    "authorization",
    "content-type",
    "dnt",
    "idempotency-key",
    "origin",
    "user-agent",
    "x-csrftoken",
    "x-request-id",
    "x-requested-with",
    "x-visitor-id",
]
CORS_EXPOSE_HEADERS = ["X-Request-ID", "X-Trace-ID"]

INSTALLED_APPS = [
    "django.contrib.contenttypes",
    "django.contrib.auth",
    "django.contrib.staticfiles",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.admin",
    "corsheaders",
    "channels",
    "rest_framework",
    "drf_spectacular",
    "backend.common",
    "backend.health",
    "backend.accounts",
    "backend.identity",
    "backend.profiles",
    "backend.catalog",
    "backend.discovery",
    "backend.content",
    "backend.wallets",
    "backend.payments",
    "backend.social",
    "backend.scheduling",
    "backend.orders",
    "backend.reviews",
    "backend.payouts",
    "backend.providers",
    "backend.media",
    "backend.locations",
    "backend.legal",
    "backend.messaging",
    "backend.referrals",
    "backend.coupons",
    "backend.memberships",
    "backend.adminops",
    "backend.moderation",
    "backend.support",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "backend.common.middleware.RequestContextMiddleware",
    "backend.common.middleware.ExceptionHandlingMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "backend.common.middleware.RequestLoggingMiddleware",
]

ROOT_URLCONF = "backend.config.urls"
WSGI_APPLICATION = "backend.config.wsgi.application"
ASGI_APPLICATION = "backend.config.asgi.application"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": get_text("POSTGRES_DB", "jianmianliao") or "jianmianliao",
        "USER": get_text("POSTGRES_USER", "jianmianliao") or "jianmianliao",
        "PASSWORD": get_text("POSTGRES_PASSWORD", "development-password") or "",
        "HOST": get_text("POSTGRES_HOST", "localhost") or "localhost",
        "PORT": get_text("POSTGRES_PORT", "5432") or "5432",
        "CONN_MAX_AGE": get_int("POSTGRES_CONN_MAX_AGE", 60),
        "CONN_HEALTH_CHECKS": True,
    }
}

CACHES = {
    "default": {
        "BACKEND": "django_redis.cache.RedisCache",
        "LOCATION": get_text("REDIS_URL", "redis://localhost:6379/0") or "redis://localhost:6379/0",
        "OPTIONS": {"CLIENT_CLASS": "django_redis.client.DefaultClient"},
    }
}

CELERY_BROKER_URL = get_text("CELERY_BROKER_URL", "redis://localhost:6379/1") or ""
CELERY_RESULT_BACKEND = get_text("CELERY_RESULT_BACKEND", "redis://localhost:6379/2") or ""
CELERY_TASK_SERIALIZER = "json"
CELERY_RESULT_SERIALIZER = "json"
CELERY_ACCEPT_CONTENT = ["json"]
CELERY_TASK_TIME_LIMIT = 60 * 20
CELERY_TASK_SOFT_TIME_LIMIT = 60 * 15
CELERY_BEAT_SCHEDULE = {
    "settle-due-referral-rewards": {
        "task": "backend.referrals.tasks.settle_referral_rewards_task",
        "schedule": timedelta(minutes=5),
    },
    "cleanup-expired-referral-visits": {
        "task": "backend.referrals.tasks.cleanup_referral_visits_task",
        "schedule": timedelta(hours=24),
    },
}
CHANNEL_LAYERS = {
    "default": {
        "BACKEND": "channels_redis.core.RedisChannelLayer",
        "CONFIG": {
            "hosts": [get_text("REDIS_URL", "redis://localhost:6379/0")],
        },
    }
}

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

AUTH_USER_MODEL = "accounts.User"
AUTH_TOKEN_SIGNING_KEY = get_text("AUTH_TOKEN_SIGNING_KEY", "dev-only-token-signing-key") or ""
OAUTH_SUBJECT_HASH_KEY = get_text("OAUTH_SUBJECT_HASH_KEY", "dev-only-oauth-subject-hash-key") or ""
PHONE_HASH_KEY = get_text("PHONE_HASH_KEY", "dev-only-phone-hash-key") or ""
SMS_MOCK_SIGNING_KEY = get_text("SMS_MOCK_SIGNING_KEY", "dev-only-sms-mock-signing-key") or ""
SMS_MOCK_ENABLED = get_bool("SMS_MOCK_ENABLED", ENVIRONMENT != "production")
SMS_PROVIDER = (get_text("SMS_PROVIDER", "MOCK") or "MOCK").upper()
ALIYUN_SMS_ACCESS_KEY_ID = get_text("ALIYUN_SMS_ACCESS_KEY_ID", "") or ""
ALIYUN_SMS_ACCESS_KEY_SECRET = get_text("ALIYUN_SMS_ACCESS_KEY_SECRET", "") or ""
ALIYUN_SMS_REGION_ID = get_text("ALIYUN_SMS_REGION_ID", "cn-hangzhou") or "cn-hangzhou"
ALIYUN_SMS_ENDPOINT = (
    get_text(
        "ALIYUN_SMS_ENDPOINT",
        "https://dysmsapi.aliyuncs.com",
    )
    or "https://dysmsapi.aliyuncs.com"
)
ALIYUN_SMS_SIGN_NAME = get_text("ALIYUN_SMS_SIGN_NAME", "") or ""
ALIYUN_SMS_TEMPLATE_CODE = get_text("ALIYUN_SMS_TEMPLATE_CODE", "") or ""
ALIYUN_SMS_TEMPLATE_PARAM_KEY = get_text("ALIYUN_SMS_TEMPLATE_PARAM_KEY", "code") or "code"
DEV_PASSWORD_LOGIN_ENABLED = ENVIRONMENT != "production" and get_bool(
    "ENABLE_DEV_PASSWORD_LOGIN",
    ENVIRONMENT != "production",
)
PASSWORD_LOGIN_MAX_FAILURES = get_int("PASSWORD_LOGIN_MAX_FAILURES", 5)
PASSWORD_LOGIN_LOCK_SECONDS = get_int("PASSWORD_LOGIN_LOCK_SECONDS", 15 * 60)
SMS_CODE_TTL_SECONDS = get_int("SMS_CODE_TTL_SECONDS", 300)
SMS_CODE_RESEND_SECONDS = get_int("SMS_CODE_RESEND_SECONDS", 60)
SMS_CODE_MAX_ATTEMPTS = get_int("SMS_CODE_MAX_ATTEMPTS", 5)
IDENTITY_ENCRYPTION_KEY = (
    get_text(
        "IDENTITY_ENCRYPTION_KEY",
        "dev-only-identity-encryption-key-change-me",
    )
    or ""
)
LOCATION_ENCRYPTION_KEY = (
    get_text("LOCATION_ENCRYPTION_KEY", "dev-only-location-encryption-key-change-me") or ""
)
LOCATION_SELECTION_SIGNING_KEY = (
    get_text("LOCATION_SELECTION_SIGNING_KEY", "dev-only-location-selection-key-change-me") or ""
)
LOCATION_PROVIDER_TTL_SECONDS = get_int("LOCATION_PROVIDER_TTL_SECONDS", 24 * 60 * 60)
LOCATION_SELECTION_TTL_SECONDS = get_int("LOCATION_SELECTION_TTL_SECONDS", 30 * 60)
IDENTITY_MOCK_ENABLED = get_bool("IDENTITY_MOCK_ENABLED", ENVIRONMENT != "production")
PROVIDER_APPLICATION_MIN_LIFE_PHOTOS = get_int("PROVIDER_APPLICATION_MIN_LIFE_PHOTOS", 3)
PROVIDER_APPLICATION_MAX_LIFE_PHOTOS = get_int("PROVIDER_APPLICATION_MAX_LIFE_PHOTOS", 9)
PROVIDER_APPLICATION_INTRODUCTION_MIN_LENGTH = get_int(
    "PROVIDER_APPLICATION_INTRODUCTION_MIN_LENGTH", 10
)
PROVIDER_APPLICATION_INTRODUCTION_MAX_LENGTH = get_int(
    "PROVIDER_APPLICATION_INTRODUCTION_MAX_LENGTH", 500
)
MEDIA_ROOT = Path(
    get_text("MEDIA_ROOT", str(PROJECT_ROOT / "var" / "media")) or PROJECT_ROOT / "var" / "media"
)
H5_ROOT = Path(get_text("H5_ROOT", str(PROJECT_ROOT / "h5")) or PROJECT_ROOT / "h5")
MEDIA_URL = get_text("MEDIA_URL", "/api/v1/media/") or "/api/v1/media/"
MEDIA_MAX_UPLOAD_BYTES = get_int("MEDIA_MAX_UPLOAD_BYTES", 5 * 1024 * 1024)
MEDIA_MIN_IMAGE_DIMENSION = get_int("MEDIA_MIN_IMAGE_DIMENSION", 64)
MEDIA_MAX_IMAGE_DIMENSION = get_int("MEDIA_MAX_IMAGE_DIMENSION", 8000)
MEDIA_MAX_IMAGE_PIXELS = get_int("MEDIA_MAX_IMAGE_PIXELS", 20_000_000)
SERVICE_TITLE_MAX_LENGTH = get_int("SERVICE_TITLE_MAX_LENGTH", 30)
SERVICE_INTRODUCTION_MIN_LENGTH = get_int("SERVICE_INTRODUCTION_MIN_LENGTH", 10)
SERVICE_INTRODUCTION_MAX_LENGTH = get_int("SERVICE_INTRODUCTION_MAX_LENGTH", 500)
SERVICE_GALLERY_MIN_COUNT = get_int("SERVICE_GALLERY_MIN_COUNT", 1)
SERVICE_GALLERY_MAX_COUNT = get_int("SERVICE_GALLERY_MAX_COUNT", 6)
SERVICE_TAG_MAX_COUNT = get_int("SERVICE_TAG_MAX_COUNT", 8)
HOME_FEED_GUEST_LIMIT = get_int("HOME_FEED_GUEST_LIMIT", 10)
HOME_FEED_AUTHENTICATED_LIMIT = get_int("HOME_FEED_AUTHENTICATED_LIMIT", 20)
HOME_FEED_RECENT_PHOTO_COUNT = get_int("HOME_FEED_RECENT_PHOTO_COUNT", 5)
HOME_FEED_SERVICE_COUNT = get_int("HOME_FEED_SERVICE_COUNT", 3)
SEARCH_KEYWORD_MAX_LENGTH = get_int("SEARCH_KEYWORD_MAX_LENGTH", 100)
SEARCH_PREVIEW_LIMIT = get_int("SEARCH_PREVIEW_LIMIT", 3)
SEARCH_TRENDING_DEFAULT_LIMIT = get_int("SEARCH_TRENDING_DEFAULT_LIMIT", 10)
SEARCH_TRENDING_MAX_LIMIT = get_int("SEARCH_TRENDING_MAX_LIMIT", 50)
SEARCH_TRENDING_WINDOW_DAYS = get_int("SEARCH_TRENDING_WINDOW_DAYS", 7)
SEARCH_TRENDING_SCORE_MODE = (get_text("SEARCH_TRENDING_SCORE_MODE", "COUNT") or "COUNT").upper()
SEARCH_TRENDING_RECENCY_DECAY_PERCENT = get_int(
    "SEARCH_TRENDING_RECENCY_DECAY_PERCENT",
    80,
)
SEARCH_TRENDING_MIN_SEARCH_COUNT = get_int("SEARCH_TRENDING_MIN_SEARCH_COUNT", 1)
SEARCH_TRENDING_SHOW_SCORE = get_bool("SEARCH_TRENDING_SHOW_SCORE", False)
TENCENT_MAP_KEY = get_text("TENCENT_MAP_KEY", "") or ""
TENCENT_MAP_API_BASE_URL = (
    get_text("TENCENT_MAP_API_BASE_URL", "https://apis.map.qq.com/ws/place/v1/search")
    or "https://apis.map.qq.com/ws/place/v1/search"
)
TENCENT_MAP_TIMEOUT_SECONDS = get_int("TENCENT_MAP_TIMEOUT_SECONDS", 5)
LOCATION_SEARCH_KEYWORD_MAX_LENGTH = get_int("LOCATION_SEARCH_KEYWORD_MAX_LENGTH", 50)
LOCATION_SEARCH_RADIUS_DEFAULT_M = get_int("LOCATION_SEARCH_RADIUS_DEFAULT_M", 2000)
LOCATION_SEARCH_RADIUS_MAX_M = get_int("LOCATION_SEARCH_RADIUS_MAX_M", 5000)
LOCATION_SEARCH_LIMIT_MAX = get_int("LOCATION_SEARCH_LIMIT_MAX", 20)
LOCATION_SEARCH_CACHE_TTL_SECONDS = get_int("LOCATION_SEARCH_CACHE_TTL_SECONDS", 30)
PUBLIC_SHARE_BASE_URL = (
    get_text("PUBLIC_SHARE_BASE_URL", "https://app.example.com") or "https://app.example.com"
)
SHARE_POSTER_BRAND_NAME = (
    get_text("SHARE_POSTER_BRAND_NAME", "FaceTo · 见面聊") or "FaceTo · 见面聊"
)
SHARE_POSTER_BRAND_LABEL = (
    get_text("SHARE_POSTER_BRAND_LABEL", "你的见面破冰者") or "你的见面破冰者"
)
SHARE_POSTER_SLOGAN_LINE_1 = get_text("SHARE_POSTER_SLOGAN_LINE_1", "想见面，") or "想见面，"
SHARE_POSTER_SLOGAN_LINE_2 = (
    get_text("SHARE_POSTER_SLOGAN_LINE_2", "却怕没话聊？") or "却怕没话聊？"
)
SHARE_POSTER_SLOGAN_SUBTITLE = (
    get_text("SHARE_POSTER_SLOGAN_SUBTITLE", "从共同兴趣开始，让每次见面都有话聊。")
    or "从共同兴趣开始，让每次见面都有话聊。"
)
SHARE_POSTER_CARD_FOOTER = (
    get_text("SHARE_POSTER_CARD_FOOTER", "先聊兴趣，再约公共场所见面")
    or "先聊兴趣，再约公共场所见面"
)
SHARE_POSTER_BOTTOM_SLOGAN = (
    get_text("SHARE_POSTER_BOTTOM_SLOGAN", "不必硬聊 · 兴趣就是你的破冰者")
    or "不必硬聊 · 兴趣就是你的破冰者"
)
SHARE_POSTER_SHARE_TITLE = (
    get_text("SHARE_POSTER_SHARE_TITLE", "FaceTo · 见面聊｜你的见面破冰者")
    or "FaceTo · 见面聊｜你的见面破冰者"
)
SHARE_POSTER_SHARE_DESCRIPTION = (
    get_text("SHARE_POSTER_SHARE_DESCRIPTION", "先聊兴趣，再约公共场所见面")
    or "先聊兴趣，再约公共场所见面"
)
NEWS_SYNC_ASYNC = get_bool("NEWS_SYNC_ASYNC", True)
NEWS_FETCH_TIMEOUT_SECONDS = get_int("NEWS_FETCH_TIMEOUT_SECONDS", 15)
NEWS_FETCH_MAX_ITEMS = get_int("NEWS_FETCH_MAX_ITEMS", 20)
MOMENT_REVIEW_MODE = get_text("MOMENT_REVIEW_MODE", "IMMEDIATE") or "IMMEDIATE"
MOMENT_CONTENT_MAX_LENGTH = get_int("MOMENT_CONTENT_MAX_LENGTH", 2000)
MOMENT_IMAGE_MIN_COUNT = get_int("MOMENT_IMAGE_MIN_COUNT", 1)
MOMENT_IMAGE_MAX_COUNT = get_int("MOMENT_IMAGE_MAX_COUNT", 9)
MOMENT_TAG_MAX_COUNT = get_int("MOMENT_TAG_MAX_COUNT", 5)
PAYMENT_MODE = get_text("PAYMENT_MODE", "MOCK_BALANCE") or "MOCK_BALANCE"
PAYMENT_GATEWAY_MODE = (get_text("PAYMENT_GATEWAY_MODE", "MOCK") or "MOCK").upper()
PAYMENT_CURRENCY = get_text("PAYMENT_CURRENCY", "CNY") or "CNY"
PAYMENT_CLIENT_PAYLOAD_TTL_SECONDS = get_int("PAYMENT_CLIENT_PAYLOAD_TTL_SECONDS", 600)
WECHAT_PAY_MCH_ID = get_text("WECHAT_PAY_MCH_ID", "") or ""
WECHAT_PAY_APP_ID = get_text("WECHAT_PAY_APP_ID", "") or ""
WECHAT_PAY_API_V3_KEY = get_text("WECHAT_PAY_API_V3_KEY", "") or ""
WECHAT_PAY_MERCHANT_SERIAL_NO = get_text("WECHAT_PAY_MERCHANT_SERIAL_NO", "") or ""
WECHAT_PAY_PRIVATE_KEY = get_text("WECHAT_PAY_PRIVATE_KEY", "") or ""
WECHAT_PAY_PLATFORM_PUBLIC_KEY = get_text("WECHAT_PAY_PLATFORM_PUBLIC_KEY", "") or ""
WECHAT_PAY_PLATFORM_PUBLIC_KEY_ID = get_text("WECHAT_PAY_PLATFORM_PUBLIC_KEY_ID", "") or ""
WECHAT_PAY_NOTIFY_URL = get_text("WECHAT_PAY_NOTIFY_URL", "") or ""
WECHAT_PAY_API_BASE_URL = get_text("WECHAT_PAY_API_BASE_URL", "https://api.mch.weixin.qq.com") or ""
WECHAT_PAY_TIMEOUT_SECONDS = get_int("WECHAT_PAY_TIMEOUT_SECONDS", 8)
ALIPAY_APP_ID = get_text("ALIPAY_APP_ID", "") or ""
ALIPAY_PRIVATE_KEY = get_text("ALIPAY_PRIVATE_KEY", "") or ""
ALIPAY_PUBLIC_KEY = get_text("ALIPAY_PUBLIC_KEY", "") or ""
ALIPAY_NOTIFY_URL = get_text("ALIPAY_NOTIFY_URL", "") or ""
ALIPAY_GATEWAY_URL = get_text("ALIPAY_GATEWAY_URL", "https://openapi.alipay.com/gateway.do") or ""
ALIPAY_TIMEOUT_SECONDS = get_int("ALIPAY_TIMEOUT_SECONDS", 8)
ENABLE_DEV_WALLET_TOPUP = get_bool(
    "ENABLE_DEV_WALLET_TOPUP",
    ENVIRONMENT != "production",
)
REVIEW_WINDOW_DAYS = get_int("REVIEW_WINDOW_DAYS", 7)
REVIEW_AUTO_POSITIVE_ENABLED = get_bool("REVIEW_AUTO_POSITIVE_ENABLED", False)
PAYOUT_VERIFICATION_MODE = get_text("PAYOUT_VERIFICATION_MODE", "MOCK") or "MOCK"
PAYOUT_MODE = get_text("PAYOUT_MODE", "MOCK_MANUAL_REVIEW") or "MOCK_MANUAL_REVIEW"
WITHDRAWAL_MIN_AMOUNT_MINOR = get_int("WITHDRAWAL_MIN_AMOUNT_MINOR", 1000)
WITHDRAWAL_FEE_AMOUNT_MINOR = get_int("WITHDRAWAL_FEE_AMOUNT_MINOR", 0)
PROVIDER_INCOME_SETTLEMENT_DELAY_DAYS = get_int(
    "PROVIDER_INCOME_SETTLEMENT_DELAY_DAYS",
    0,
)
PROVIDER_PLATFORM_COMMISSION_RATE_BPS = get_int(
    "PROVIDER_PLATFORM_COMMISSION_RATE_BPS",
    1000,
)
MEDIA_URL_SIGNING_KEY = (
    get_text("MEDIA_URL_SIGNING_KEY", "dev-only-media-url-signing-key-change-me") or ""
)
MEDIA_URL_SIGNING_KEY_VERSION = get_text("MEDIA_URL_SIGNING_KEY_VERSION", "v1") or "v1"
MEDIA_DISPLAY_URL_TTL_SECONDS = get_int("MEDIA_DISPLAY_URL_TTL_SECONDS", 600)
MEDIA_DISPLAY_URL_REFRESH_BUFFER_SECONDS = get_int(
    "MEDIA_DISPLAY_URL_REFRESH_BUFFER_SECONDS",
    30,
)
PROFILE_DEFAULT_CITY_CODE = get_text("PROFILE_DEFAULT_CITY_CODE", "LZ") or "LZ"
PROFILE_NICKNAME_MAX_LENGTH = get_int("PROFILE_NICKNAME_MAX_LENGTH", 30)
PROFILE_SIGNATURE_MAX_LENGTH = get_int("PROFILE_SIGNATURE_MAX_LENGTH", 100)
PROFILE_INTEREST_TAG_MAX_COUNT = get_int("PROFILE_INTEREST_TAG_MAX_COUNT", 5)
REFERRAL_REWARD_RATE_BPS = get_int("REFERRAL_REWARD_RATE_BPS", 0)
REFERRAL_REWARD_MAX_AMOUNT_MINOR = get_int("REFERRAL_REWARD_MAX_AMOUNT_MINOR", 0)
REFERRAL_REWARD_DELAY_DAYS = get_int("REFERRAL_REWARD_DELAY_DAYS", 7)
REFERRAL_REWARD_FUNDING_CAP_TO_PLATFORM_FEE = get_bool(
    "REFERRAL_REWARD_FUNDING_CAP_TO_PLATFORM_FEE",
    True,
)
REFERRAL_VISIT_RETENTION_DAYS = get_int("REFERRAL_VISIT_RETENTION_DAYS", 180)
SCHEDULE_DEFAULT_TIMEZONE = (
    get_text("SCHEDULE_DEFAULT_TIMEZONE", "Asia/Shanghai") or "Asia/Shanghai"
)
SCHEDULE_SLOT_UNIT_MINUTES = get_int("SCHEDULE_SLOT_UNIT_MINUTES", 60)
SCHEDULE_DEFAULT_START_MINUTE = get_int("SCHEDULE_DEFAULT_START_MINUTE", 0)
SCHEDULE_DEFAULT_END_MINUTE = get_int("SCHEDULE_DEFAULT_END_MINUTE", 24 * 60)
SCHEDULE_MAX_BOOKING_MINUTES = get_int("SCHEDULE_MAX_BOOKING_MINUTES", 0)
REFUND_REQUEST_MIN_HOURS_BEFORE_START = get_int(
    "REFUND_REQUEST_MIN_HOURS_BEFORE_START",
    6,
)
API_DISPLAY_TIMEZONE = get_text("API_DISPLAY_TIMEZONE", "Asia/Shanghai") or "Asia/Shanghai"
API_DATETIME_FORMAT = "%Y-%m-%d %H:%M:%S"
AUTH_ACCESS_TOKEN_LIFETIME = get_int("AUTH_ACCESS_TOKEN_LIFETIME", 60 * 60 * 2)
AUTH_REFRESH_TOKEN_LIFETIME = get_int("AUTH_REFRESH_TOKEN_LIFETIME", 60 * 60 * 24 * 30)
APPLE_LOGIN_ENABLED = get_bool("APPLE_LOGIN_ENABLED", True)
APPLE_CLIENT_ID = get_text("APPLE_CLIENT_ID", "") or ""
APPLE_JWKS_URL = get_text("APPLE_JWKS_URL", "https://appleid.apple.com/auth/keys") or ""
APPLE_JWKS_TIMEOUT_SECONDS = get_int("APPLE_JWKS_TIMEOUT_SECONDS", 5)
WECHAT_LOGIN_ENABLED = get_bool("WECHAT_LOGIN_ENABLED", True)
WECHAT_LOGIN_APP_ID = get_text("WECHAT_LOGIN_APP_ID", "") or ""
WECHAT_LOGIN_APP_SECRET = get_text("WECHAT_LOGIN_APP_SECRET", "") or ""
WECHAT_LOGIN_API_BASE_URL = get_text("WECHAT_LOGIN_API_BASE_URL", "https://api.weixin.qq.com") or ""
WECHAT_LOGIN_TIMEOUT_SECONDS = get_int("WECHAT_LOGIN_TIMEOUT_SECONDS", 5)
MESSAGING_WS_TICKET_TTL_SECONDS = get_int("MESSAGING_WS_TICKET_TTL_SECONDS", 60)
MESSAGING_MESSAGE_MAX_LENGTH = get_int("MESSAGING_MESSAGE_MAX_LENGTH", 2000)
MESSAGING_COMPLETED_SEND_WINDOW_DAYS = get_int("MESSAGING_COMPLETED_SEND_WINDOW_DAYS", 7)
MESSAGING_RECORD_RETENTION_DAYS = get_int("MESSAGING_RECORD_RETENTION_DAYS", 180)
MESSAGING_MAX_PAGE_SIZE = get_int("MESSAGING_MAX_PAGE_SIZE", 100)

LANGUAGE_CODE = "zh-hans"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True
STATIC_URL = "static/"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

REST_FRAMEWORK = {
    "DEFAULT_RENDERER_CLASSES": ["backend.common.renderers.ApiJSONRenderer"],
    "DEFAULT_PARSER_CLASSES": [
        "rest_framework.parsers.JSONParser",
        "rest_framework.parsers.FormParser",
        "rest_framework.parsers.MultiPartParser",
    ],
    "DEFAULT_AUTHENTICATION_CLASSES": [],
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.AllowAny"],
    "DEFAULT_PAGINATION_CLASS": "backend.common.pagination.ApiCursorPagination",
    "PAGE_SIZE": 20,
    "EXCEPTION_HANDLER": "backend.common.exceptions.custom_exception_handler",
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    "DEFAULT_THROTTLE_RATES": {
        "location_search": "30/minute",
    },
}

SPECTACULAR_SETTINGS = {
    "TITLE": "见面聊后端 API",
    "DESCRIPTION": "见面聊模块化后端工程基础接口。业务接口将按模块逐步补充。",
    "VERSION": APP_VERSION,
    "SERVE_INCLUDE_SCHEMA": False,
    "SCHEMA_PATH_PREFIX": "/api/",
    "COMPONENT_SPLIT_REQUEST": True,
    "SERVE_PERMISSIONS": ["rest_framework.permissions.AllowAny"],
    "SWAGGER_UI_SETTINGS": {
        "persistAuthorization": True,
    },
    "ENUM_NAME_OVERRIDES": {
        "ScheduleSlotStatusEnum": ["OPEN", "CLOSED", "LOCKED", "BOOKED"],
        "ScheduleDayStatusEnum": ["AVAILABLE", "PARTIAL", "BOOKED", "REST", "CLOSED"],
        "OrderContactTargetRoleEnum": ["USER", "PROVIDER"],
        "OrderActorRoleEnum": ["USER", "PROVIDER", "SYSTEM"],
        "OrderNextActionRoleEnum": ["USER", "PROVIDER", "NONE"],
        "MessagingConversationStatusEnum": ["OPEN", "READ_ONLY", "CLOSED"],
        "MessagingMemberRoleEnum": ["CUSTOMER", "PROVIDER", "SYSTEM"],
        "MessagingMessageTypeEnum": ["TEXT", "IMAGE", "SYSTEM"],
    },
}

LOG_LEVEL = get_text("DJANGO_LOG_LEVEL", "INFO") or "INFO"
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "filters": {
        "request_trace": {"()": "backend.common.logging.RequestTraceFilter"},
        "sensitive_data": {"()": "backend.common.logging.SensitiveDataFilter"},
    },
    "formatters": {
        "json": {"()": "backend.common.logging.RedactingJsonFormatter"},
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "filters": ["request_trace", "sensitive_data"],
            "formatter": "json",
        }
    },
    "root": {"handlers": ["console"], "level": LOG_LEVEL},
    "loggers": {
        "django": {"handlers": ["console"], "level": LOG_LEVEL, "propagate": False},
        "django.request": {"handlers": ["console"], "level": LOG_LEVEL, "propagate": False},
        "celery": {"handlers": ["console"], "level": LOG_LEVEL, "propagate": False},
    },
}
