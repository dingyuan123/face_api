"""地点搜索接口路由。"""

from django.urls import path

from backend.locations.api.views import (
    AdminLocationQuickKeywordDetailView,
    AdminLocationQuickKeywordListCreateView,
    LocationQuickKeywordView,
    LocationSearchView,
    ProviderLocationView,
)

urlpatterns = [
    path(
        "location-search/quick-keywords/",
        LocationQuickKeywordView.as_view(),
        name="location-quick-keywords",
    ),
    path("location-search/", LocationSearchView.as_view(), name="location-search"),
    path("provider/location/", ProviderLocationView.as_view(), name="provider-location"),
    path(
        "admin/location-search/quick-keywords/",
        AdminLocationQuickKeywordListCreateView.as_view(),
        name="admin-location-quick-keywords",
    ),
    path(
        "admin/location-search/quick-keywords/<uuid:keyword_id>/",
        AdminLocationQuickKeywordDetailView.as_view(),
        name="admin-location-quick-keyword-detail",
    ),
]
