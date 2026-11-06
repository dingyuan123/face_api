from django.urls import path

from backend.media.api.views import MediaContentView, MediaDisplayView, MediaUploadView

urlpatterns = [
    path("media/uploads/", MediaUploadView.as_view(), name="media-uploads"),
    path(
        "media/<uuid:media_id>/content/",
        MediaContentView.as_view(),
        name="media-content",
    ),
    path(
        "media/display/<uuid:media_id>/",
        MediaDisplayView.as_view(),
        name="media-display",
    ),
]
