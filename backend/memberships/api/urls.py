"""普通用户会员套餐、状态和购买接口路由。"""

from django.urls import path

from backend.memberships.api.views import (
    MembershipPlanListView,
    MembershipPurchaseDetailView,
    MembershipPurchaseListCreateView,
    MembershipSummaryView,
)

urlpatterns = [
    path("membership/plans/", MembershipPlanListView.as_view(), name="membership-plans"),
    path("membership/", MembershipSummaryView.as_view(), name="membership-summary"),
    path(
        "membership/purchases/",
        MembershipPurchaseListCreateView.as_view(),
        name="membership-purchases",
    ),
    path(
        "membership/purchases/<uuid:purchase_no>/",
        MembershipPurchaseDetailView.as_view(),
        name="membership-purchase-detail",
    ),
]
