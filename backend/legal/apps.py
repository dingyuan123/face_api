"""用户服务协议和隐私政策公开页面应用配置。"""

from django.apps import AppConfig


class LegalConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "backend.legal"
    label = "legal"
