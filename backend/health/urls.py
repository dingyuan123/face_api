from django.urls import path

from backend.health.views import LiveHealthView, ReadyHealthView

urlpatterns = [
    path("live/", LiveHealthView.as_view(), name="health-live"),
    path("ready/", ReadyHealthView.as_view(), name="health-ready"),
]
