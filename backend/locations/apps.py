"""地点搜索 Django 应用配置。"""

from django.apps import AppConfig


class LocationsConfig(AppConfig):
    """注册地点搜索应用和数据库迁移入口。"""

    default_auto_field = "django.db.models.BigAutoField"
    name = "backend.locations"
