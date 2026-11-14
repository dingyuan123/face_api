"""分享推广模块应用配置。"""

from django.apps import AppConfig


class ReferralsConfig(AppConfig):
    """注册分享推广模块并设置稳定应用名称。"""

    default_auto_field = "django.db.models.BigAutoField"
    name = "backend.referrals"
    verbose_name = "分享推广"
