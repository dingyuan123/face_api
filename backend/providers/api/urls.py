from django.urls import path

from backend.providers.api.views import (
    AdminProviderApplicationApproveView,
    AdminProviderApplicationDetailView,
    AdminProviderApplicationListView,
    AdminProviderApplicationRejectView,
    MyProviderApplicationView,
    ProviderApplicationCreateView,
)

urlpatterns = [
    path(
        "provider-applications/",
        ProviderApplicationCreateView.as_view(),
        name="provider-applications",
    ),
    path(
        "provider-applications/me/",
        MyProviderApplicationView.as_view(),
        name="provider-application-me",
    ),
    path(
        "admin/provider-applications/",
        AdminProviderApplicationListView.as_view(),
        name="admin-provider-applications",
    ),
    path(
        "admin/provider-applications/<str:application_no>/",
        AdminProviderApplicationDetailView.as_view(),
        name="admin-provider-application-detail",
    ),
    path(
        "admin/provider-applications/<str:application_no>/approve/",
        AdminProviderApplicationApproveView.as_view(),
        name="admin-provider-application-approve",
    ),
    path(
        "admin/provider-applications/<str:application_no>/reject/",
        AdminProviderApplicationRejectView.as_view(),
        name="admin-provider-application-reject",
    ),
]
