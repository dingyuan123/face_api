"""管理后台优惠券模板、发放和核销审计路由。"""

from django.urls import path

from backend.coupons.api.views import (
    AdminCouponIssueView,
    AdminCouponRedemptionListView,
    AdminCouponRevokeView,
    AdminCouponTemplateDetailView,
    AdminCouponTemplateListCreateView,
)

urlpatterns = [
    path(
        "coupons/templates/",
        AdminCouponTemplateListCreateView.as_view(),
        name="admin-v1-coupon-templates",
    ),
    path(
        "coupons/templates/<uuid:template_no>/",
        AdminCouponTemplateDetailView.as_view(),
        name="admin-v1-coupon-template-detail",
    ),
    path("coupons/issue/", AdminCouponIssueView.as_view(), name="admin-v1-coupon-issue"),
    path(
        "coupons/<uuid:coupon_no>/revoke/",
        AdminCouponRevokeView.as_view(),
        name="admin-v1-coupon-revoke",
    ),
    path(
        "coupons/redemptions/",
        AdminCouponRedemptionListView.as_view(),
        name="admin-v1-coupon-redemptions",
    ),
]
