"""支付查询和微信、支付宝异步通知路由。"""

from django.urls import path

from backend.payments.api.views import (
    AlipayPaymentNotifyView,
    PaymentDetailView,
    WeChatPaymentNotifyView,
)

urlpatterns = [
    path("payments/<uuid:payment_no>/", PaymentDetailView.as_view(), name="payment-detail"),
    path(
        "payments/wechat/notify/",
        WeChatPaymentNotifyView.as_view(),
        name="payment-wechat-notify",
    ),
    path(
        "payments/alipay/notify/",
        AlipayPaymentNotifyView.as_view(),
        name="payment-alipay-notify",
    ),
]
