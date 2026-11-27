"""会员模块应用配置。"""

from django.apps import AppConfig


class MembershipsConfig(AppConfig):
    """注册会员套餐、购买、有效期、权益和支付确认业务。"""

    default_auto_field = "django.db.models.BigAutoField"
    name = "backend.memberships"
    verbose_name = "会员"
