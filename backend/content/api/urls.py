from django.urls import path

from backend.content.api.views import (
    AdminMomentApproveView,
    AdminMomentDetailView,
    AdminMomentListView,
    AdminMomentRejectView,
    MomentCategoryOptionsView,
    MountableServicesView,
    ProviderMomentDetailView,
    ProviderMomentListCreateView,
    ProviderMomentPublishView,
    PublicMomentDetailView,
    PublicMomentListView,
    PublicMomentNeighborsView,
)

urlpatterns = [
    path(
        "provider-moments/",
        ProviderMomentListCreateView.as_view(),
        name="provider-moments",
    ),
    path(
        "provider-moments/mountable-services/",
        MountableServicesView.as_view(),
        name="moment-mountable-services",
    ),
    path(
        "provider-moments/<uuid:moment_id>/",
        ProviderMomentDetailView.as_view(),
        name="provider-moment-detail",
    ),
    path(
        "provider-moments/<uuid:moment_id>/publish/",
        ProviderMomentPublishView.as_view(),
        name="provider-moment-publish",
    ),
    path("moments/", PublicMomentListView.as_view(), name="public-moments"),
    path(
        "moment-options/categories/",
        MomentCategoryOptionsView.as_view(),
        name="moment-categories",
    ),
    path(
        "moments/<uuid:moment_id>/", PublicMomentDetailView.as_view(), name="public-moment-detail"
    ),
    path(
        "moments/<uuid:moment_id>/neighbors/",
        PublicMomentNeighborsView.as_view(),
        name="public-moment-neighbors",
    ),
    path("admin/moments/", AdminMomentListView.as_view(), name="admin-moments"),
    path(
        "admin/moments/<uuid:moment_id>/",
        AdminMomentDetailView.as_view(),
        name="admin-moment-detail",
    ),
    path(
        "admin/moments/<uuid:moment_id>/approve/",
        AdminMomentApproveView.as_view(),
        name="admin-moment-approve",
    ),
    path(
        "admin/moments/<uuid:moment_id>/reject/",
        AdminMomentRejectView.as_view(),
        name="admin-moment-reject",
    ),
]
