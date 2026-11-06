from django.core.exceptions import ImproperlyConfigured

from .base import *  # noqa: F403

if ENVIRONMENT == "production":  # noqa: F405
    raise ImproperlyConfigured("开发配置禁止用于生产环境, 请使用 backend.config.settings.prod。")

DEBUG = True
ALLOWED_HOSTS = list(set([*ALLOWED_HOSTS, "localhost", "127.0.0.1"]))  # noqa: F405
