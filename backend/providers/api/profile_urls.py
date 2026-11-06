from django.urls import path

from backend.providers.api.profile_views import ProviderProfileView

urlpatterns = [
    path("provider-profile/me/", ProviderProfileView.as_view(), name="provider-profile-me"),
]
