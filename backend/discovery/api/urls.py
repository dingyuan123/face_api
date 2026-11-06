from django.urls import path

from backend.discovery.api.views import (
    AdminTrendingListCreateView,
    AdminTrendingUpdateView,
    HomeFeedView,
    SearchAllView,
    SearchMomentsView,
    SearchNewsView,
    SearchProvidersView,
    TrendingSearchView,
)

urlpatterns = [
    path("home/feed/", HomeFeedView.as_view(), name="home-feed"),
    path("search/", SearchAllView.as_view(), name="search-all"),
    path("search/providers/", SearchProvidersView.as_view(), name="search-providers"),
    path("search/moments/", SearchMomentsView.as_view(), name="search-moments"),
    path("search/news/", SearchNewsView.as_view(), name="search-news"),
    path("search/trending/", TrendingSearchView.as_view(), name="search-trending"),
    path(
        "admin/search/trending/",
        AdminTrendingListCreateView.as_view(),
        name="admin-search-trending",
    ),
    path(
        "admin/search/trending/<uuid:trending_id>/",
        AdminTrendingUpdateView.as_view(),
        name="admin-search-trending-detail",
    ),
]
