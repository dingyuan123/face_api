"""订单实时聊天应用配置。"""

from django.apps import AppConfig


class MessagingConfig(AppConfig):
    """注册订单实时聊天应用。"""

    default_auto_field = "django.db.models.BigAutoField"
    name = "backend.messaging"
    verbose_name = "订单实时聊天"
