from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/v1/", include(("backend.api.v1.urls", "api-v1"), namespace="v1")),
]
