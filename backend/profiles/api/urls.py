from django.urls import path

from backend.profiles.api.views import (
    CityOptionsView,
    InterestTagOptionsView,
    ProfileSharePosterView,
    ProfileSummaryView,
    ProfileView,
)

urlpatterns = [
    path("users/me/profile/", ProfileView.as_view(), name="users-me-profile"),
    path("users/me/summary/", ProfileSummaryView.as_view(), name="users-me-summary"),
    path(
        "users/me/share-poster/",
        ProfileSharePosterView.as_view(),
        name="users-me-share-poster",
    ),
    path(
        "profile-options/interest-tags/",
        InterestTagOptionsView.as_view(),
        name="profile-interest-tags",
    ),
    path("profile-options/cities/", CityOptionsView.as_view(), name="profile-city-options"),
]
