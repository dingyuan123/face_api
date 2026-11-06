"""收款方式、收入账户和提现应用配置。"""

from django.apps import AppConfig


class PayoutsConfig(AppConfig):
    """注册收款、收入和提现业务模型。"""

    default_auto_field = "django.db.models.BigAutoField"
    name = "backend.payouts"
