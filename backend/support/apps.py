"""客服工单应用配置。"""

from django.apps import AppConfig


class SupportConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "backend.support"
    verbose_name = "客服支持"
