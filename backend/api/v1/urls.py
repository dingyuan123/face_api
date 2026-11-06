from django.urls import include, path
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema
from drf_spectacular.views import SpectacularAPIView, SpectacularRedocView, SpectacularSwaggerView
from rest_framework.decorators import api_view
from rest_framework.request import Request
from rest_framework.response import Response


@extend_schema(auth=[], responses={200: OpenApiTypes.OBJECT})
@api_view(["GET"])
def api_root(request: Request) -> Response:
    return Response(
        {
            "name": "见面聊后端 API",
            "version": "v1",
            "links": {
                "health_live": request.build_absolute_uri("/api/v1/health/live/"),
                "health_ready": request.build_absolute_uri("/api/v1/health/ready/"),
                "schema": request.build_absolute_uri("/api/v1/schema/"),
                "docs": request.build_absolute_uri("/api/v1/docs/"),
            },
        }
    )


urlpatterns = [
    path("", api_root, name="api-root"),
    path("", include("backend.accounts.api.urls")),
    path("", include("backend.media.api.urls")),
    path("", include("backend.wallets.api.urls")),
    path("", include("backend.catalog.api.urls")),
    path("", include("backend.content.api.urls")),
    path("", include("backend.content.api.news_urls")),
    path("", include("backend.discovery.api.urls")),
    path("", include("backend.profiles.api.urls")),
    path("", include("backend.social.api.urls")),
    path("", include("backend.scheduling.api.urls")),
    path("", include("backend.orders.api.urls")),
    path("", include("backend.reviews.api.urls")),
    path("", include("backend.payouts.api.urls")),
    path("", include("backend.providers.api.profile_urls")),
    path("", include("backend.providers.api.public_urls")),
    path("", include("backend.providers.api.urls")),
    path("health/", include("backend.health.urls")),
    path("schema/", SpectacularAPIView.as_view(), name="schema"),
    path("docs/", SpectacularSwaggerView.as_view(url_name="v1:schema"), name="swagger-ui"),
    path("redoc/", SpectacularRedocView.as_view(url_name="v1:schema"), name="redoc"),
]
