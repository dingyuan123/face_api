"""内容风控管理模块应用配置。"""

from django.apps import AppConfig


class ModerationConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "backend.moderation"
    verbose_name = "内容风控"
