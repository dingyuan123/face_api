from django.urls import path

from backend.providers.api.public_views import PublicProviderProfileView

urlpatterns = [
    path(
        "providers/<uuid:provider_public_id>/",
        PublicProviderProfileView.as_view(),
        name="public-provider-profile",
    ),
]
