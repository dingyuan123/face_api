from __future__ import annotations

import json
from datetime import datetime
from zoneinfo import ZoneInfo

from django.test import override_settings
from django.urls import reverse
from rest_framework.test import APIClient

from backend.common.renderers import ApiJSONRenderer


def test_api_root_returns_versioned_links_and_trace_id() -> None:
    client = APIClient()

    response = client.get(reverse("v1:api-root"))

    assert response.status_code == 200
    payload = response.json()
    assert payload["code"] == 0
    assert payload["data"]["version"] == "v1"
    assert payload["trace_id"] == payload["meta"]["trace_id"]
    assert response["X-Request-ID"] == payload["trace_id"]


def test_api_datetimes_use_fixed_local_display_format() -> None:
    payload = json.loads(
        ApiJSONRenderer().render(
            {
                "occurred_at": datetime(
                    2026,
                    11,
                    4,
                    1,
                    30,
                    5,
                    tzinfo=ZoneInfo("UTC"),
                ),
                "date": "2026-11-04",
            }
        )
    )

    assert payload["data"]["occurred_at"] == "2026-11-04 09:30:05"
    assert payload["data"]["date"] == "2026-11-04"


@override_settings(ROOT_URLCONF="tests.test_urls")
def test_validation_error_uses_stable_envelope() -> None:
    client = APIClient()

    response = client.get("/validation-error/")

    assert response.status_code == 400
    payload = response.json()
    assert payload["code"] == "SYSTEM_VALIDATION_ERROR"
    assert payload["details"] == {"field": ["该字段无效"]}
    assert payload["trace_id"] == response["X-Trace-ID"]


@override_settings(ROOT_URLCONF="tests.test_urls")
def test_authentication_error_uses_stable_envelope() -> None:
    client = APIClient()

    response = client.get("/authentication-error/")

    assert response.status_code == 401
    assert response.json()["code"] == "AUTH_AUTHENTICATION_REQUIRED"


@override_settings(ROOT_URLCONF="tests.test_urls")
def test_unhandled_error_is_redacted_and_traceable() -> None:
    client = APIClient(raise_request_exception=False)

    response = client.get("/unexpected-error/")

    assert response.status_code == 500
    payload = json.loads(response.content)
    assert payload["code"] == "SYSTEM_INTERNAL_ERROR"
    assert "password" not in response.content.decode()
    assert payload["trace_id"] == response["X-Trace-ID"]


def test_openapi_schema_and_documentation_are_available() -> None:
    client = APIClient()

    schema_response = client.get(reverse("v1:schema"))
    docs_response = client.get(reverse("v1:swagger-ui"))
    redoc_response = client.get(reverse("v1:redoc"))

    assert schema_response.status_code == 200
    assert schema_response["Content-Type"].startswith("application/vnd.oai.openapi")
    assert docs_response.status_code == 200
    assert redoc_response.status_code == 200
