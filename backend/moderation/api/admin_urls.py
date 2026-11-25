"""管理后台内容举报和敏感词接口路由。"""

from django.urls import path

from backend.moderation.api.views import (
    AdminContentReportListView,
    AdminContentReportReviewView,
    AdminSensitiveWordDetailView,
    AdminSensitiveWordListView,
)

urlpatterns = [
    path("reports/", AdminContentReportListView.as_view(), name="admin-v1-reports"),
    path(
        "reports/<uuid:report_no>/actions/<str:action>/",
        AdminContentReportReviewView.as_view(),
        name="admin-v1-report-review",
    ),
    path(
        "sensitive-words/",
        AdminSensitiveWordListView.as_view(),
        name="admin-v1-sensitive-words",
    ),
    path(
        "sensitive-words/<int:word_id>/",
        AdminSensitiveWordDetailView.as_view(),
        name="admin-v1-sensitive-word-detail",
    ),
]
