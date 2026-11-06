from .base import *  # noqa: F403

DEBUG = False
ALLOWED_HOSTS = ["testserver", "localhost", "127.0.0.1"]

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": ":memory:",
    }
}

CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "jianmianliao-tests",
    }
}

CELERY_TASK_ALWAYS_EAGER = True
CELERY_TASK_EAGER_PROPAGATES = True
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
SMS_MOCK_ENABLED = True
AUTH_TOKEN_SIGNING_KEY = "test-token-signing-key"
PHONE_HASH_KEY = "test-phone-hash-key"
SMS_MOCK_SIGNING_KEY = "test-sms-mock-signing-key"
