"""普通用户优惠券接口路由。"""

from django.urls import path

from backend.coupons.api.views import CouponClaimView, CouponDetailView, CouponListView

urlpatterns = [
    path("coupons/", CouponListView.as_view(), name="coupon-list"),
    path("coupons/<uuid:coupon_no>/", CouponDetailView.as_view(), name="coupon-detail"),
    path(
        "coupon-templates/<uuid:template_no>/claim/",
        CouponClaimView.as_view(),
        name="coupon-claim",
    ),
]
