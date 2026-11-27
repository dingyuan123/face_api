"""管理后台会员套餐和购买记录查询路由。"""

from django.urls import path

from backend.memberships.api.views import (
    AdminMembershipPlanDetailView,
    AdminMembershipPlanListCreateView,
    AdminMembershipPurchaseListView,
)

urlpatterns = [
    path(
        "membership/plans/",
        AdminMembershipPlanListCreateView.as_view(),
        name="admin-v1-membership-plans",
    ),
    path(
        "membership/plans/<uuid:plan_no>/",
        AdminMembershipPlanDetailView.as_view(),
        name="admin-v1-membership-plan-detail",
    ),
    path(
        "membership/purchases/",
        AdminMembershipPurchaseListView.as_view(),
        name="admin-v1-membership-purchases",
    ),
]
