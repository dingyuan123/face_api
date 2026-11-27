"""优惠券模块应用配置。"""

from django.apps import AppConfig


class CouponsConfig(AppConfig):
    """注册优惠券模板、发放、核销和订单优惠业务。"""

    default_auto_field = "django.db.models.BigAutoField"
    name = "backend.coupons"
    verbose_name = "优惠券"
