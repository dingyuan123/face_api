"""普通用户实名认证接口路由。"""

from django.urls import path

from backend.identity.api.views import (
    AdminIdentityVerificationListView,
    AdminIdentityVerificationReviewView,
    MyRealNameVerificationView,
    RealNameVerificationSubmitView,
)

urlpatterns = [
    path(
        "identity/real-name/me/",
        MyRealNameVerificationView.as_view(),
        name="identity-real-name-me",
    ),
    path(
        "identity/real-name/submit/",
        RealNameVerificationSubmitView.as_view(),
        name="identity-real-name-submit",
    ),
    path(
        "admin/identity/verifications/",
        AdminIdentityVerificationListView.as_view(),
        name="admin-identity-verifications",
    ),
    path(
        "admin/identity/verifications/<uuid:verification_no>/actions/<str:action>/",
        AdminIdentityVerificationReviewView.as_view(),
        name="admin-identity-verification-review",
    ),
]
