"""开发测试管理后台应用配置。"""

from django.apps import AppConfig


class AdminOpsConfig(AppConfig):
    """注册管理后台应用。"""

    default_auto_field = "django.db.models.BigAutoField"
    name = "backend.adminops"
    verbose_name = "测试管理后台"
