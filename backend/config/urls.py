from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("admin/v1/", include("backend.adminops.api.urls")),
    path("admin/", admin.site.urls),
    path("management/", include("backend.adminops.urls")),
    path("api/v1/", include(("backend.api.v1.urls", "api-v1"), namespace="v1")),
    path("", include("backend.referrals.landing_urls")),
    path("", include("backend.legal.urls")),
]
