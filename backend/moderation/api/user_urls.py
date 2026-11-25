"""普通用户内容举报接口路由。"""

from django.urls import path

from backend.moderation.api.views import ContentReportCreateView

urlpatterns = [
    path("reports/", ContentReportCreateView.as_view(), name="content-reports"),
]
