"""资讯公开、管理员维护和外部来源同步 URL 路由。"""

from django.urls import path

from backend.content.api.news_views import (
    AdminNewsDetailView,
    AdminNewsListCreateView,
    AdminNewsPublishView,
    AdminNewsRejectView,
    AdminNewsSourceDetailView,
    AdminNewsSourceListCreateView,
    AdminNewsSyncDetailView,
    AdminNewsSyncView,
    NewsCategoryListView,
    NewsShareView,
    PublicNewsDetailView,
    PublicNewsListView,
)

urlpatterns = [
    path("news/", PublicNewsListView.as_view(), name="public-news"),
    path("news/categories/", NewsCategoryListView.as_view(), name="news-categories"),
    path("news/<uuid:news_id>/", PublicNewsDetailView.as_view(), name="public-news-detail"),
    path("news/<uuid:news_id>/share/", NewsShareView.as_view(), name="news-share"),
    path("admin/news/", AdminNewsListCreateView.as_view(), name="admin-news"),
    path("admin/news/sources/", AdminNewsSourceListCreateView.as_view(), name="admin-news-sources"),
    path(
        "admin/news/sources/<str:source_code>/",
        AdminNewsSourceDetailView.as_view(),
        name="admin-news-source-detail",
    ),
    path("admin/news/sync/", AdminNewsSyncView.as_view(), name="admin-news-sync"),
    path(
        "admin/news/sync/<uuid:run_no>/",
        AdminNewsSyncDetailView.as_view(),
        name="admin-news-sync-detail",
    ),
    path("admin/news/<uuid:news_id>/", AdminNewsDetailView.as_view(), name="admin-news-detail"),
    path(
        "admin/news/<uuid:news_id>/publish/",
        AdminNewsPublishView.as_view(),
        name="admin-news-publish",
    ),
    path(
        "admin/news/<uuid:news_id>/reject/",
        AdminNewsRejectView.as_view(),
        name="admin-news-reject",
    ),
]
