from django.urls import path
from rest_framework.decorators import api_view
from rest_framework.exceptions import NotAuthenticated, ValidationError
from rest_framework.request import Request
from rest_framework.response import Response


@api_view(["GET"])
def validation_error_view(request: Request) -> Response:
    raise ValidationError({"field": ["该字段无效"]})


@api_view(["GET"])
def authentication_error_view(request: Request) -> Response:
    raise NotAuthenticated()


@api_view(["GET"])
def unexpected_error_view(request: Request) -> Response:
    raise RuntimeError("password=must-not-appear")


urlpatterns = [
    path("validation-error/", validation_error_view),
    path("authentication-error/", authentication_error_view),
    path("unexpected-error/", unexpected_error_view),
]
