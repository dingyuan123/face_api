"""分享推广接口路由。"""

from django.urls import path

from backend.referrals.api.views import (
    AdminReferralAttributionListView,
    AdminReferralPolicyListView,
    AdminReferralPolicyRetireView,
    AdminReferralRewardAdjustView,
    AdminReferralRewardListView,
    AdminReferralRewardStateView,
    ReferralOverviewView,
    ReferralQRView,
    ReferralRewardListView,
    ReferralRewardSummaryView,
    ReferralShareLinkView,
    ReferralVisitView,
)

urlpatterns = [
    path("referrals/visits/", ReferralVisitView.as_view(), name="referral-visits"),
    path("referrals/qr/<uuid:share_no>/", ReferralQRView.as_view(), name="referral-qr"),
    path("referrals/me/", ReferralOverviewView.as_view(), name="referral-overview"),
    path(
        "referrals/me/share-links/",
        ReferralShareLinkView.as_view(),
        name="referral-share-links",
    ),
    path(
        "referrals/me/rewards/summary/",
        ReferralRewardSummaryView.as_view(),
        name="referral-reward-summary",
    ),
    path(
        "referrals/me/rewards/",
        ReferralRewardListView.as_view(),
        name="referral-rewards",
    ),
    path(
        "admin/referral-policies/",
        AdminReferralPolicyListView.as_view(),
        name="admin-referral-policies",
    ),
    path(
        "admin/referral-policies/<uuid:policy_no>/retire/",
        AdminReferralPolicyRetireView.as_view(),
        name="admin-referral-policy-retire",
    ),
    path(
        "admin/referrals/attributions/",
        AdminReferralAttributionListView.as_view(),
        name="admin-referral-attributions",
    ),
    path(
        "admin/referrals/rewards/",
        AdminReferralRewardListView.as_view(),
        name="admin-referral-rewards",
    ),
    path(
        "admin/referrals/rewards/<uuid:reward_no>/actions/<str:action>/",
        AdminReferralRewardStateView.as_view(),
        name="admin-referral-reward-state",
    ),
    path(
        "admin/referrals/rewards/<uuid:reward_no>/adjust/",
        AdminReferralRewardAdjustView.as_view(),
        name="admin-referral-reward-adjust",
    ),
]
