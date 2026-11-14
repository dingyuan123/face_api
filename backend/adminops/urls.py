"""开发测试管理后台页面路由。"""

from django.urls import path

from backend.adminops.views import (
    dashboard,
    identity_detail,
    identity_list,
    identity_review,
    provider_application_detail,
    provider_application_list,
    provider_application_review,
)

urlpatterns = [
    path("", dashboard, name="management-dashboard"),
    path("identity/", identity_list, name="management-identity-list"),
    path(
        "identity/<uuid:verification_no>/",
        identity_detail,
        name="management-identity-detail",
    ),
    path(
        "identity/<uuid:verification_no>/review/",
        identity_review,
        name="management-identity-review",
    ),
    path(
        "provider-applications/",
        provider_application_list,
        name="management-provider-list",
    ),
    path(
        "provider-applications/<str:application_no>/",
        provider_application_detail,
        name="management-provider-detail",
    ),
    path(
        "provider-applications/<str:application_no>/review/",
        provider_application_review,
        name="management-provider-review",
    ),
]
