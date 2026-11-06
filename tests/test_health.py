from __future__ import annotations

import pytest
from django.urls import reverse
from rest_framework.test import APIClient


def test_live_health_uses_api_envelope() -> None:
    client = APIClient()

    response = client.get(reverse("v1:health-live"))

    assert response.status_code == 200
    assert response.json()["code"] == 0
    assert response.json()["trace_id"] == response["X-Trace-ID"]


@pytest.mark.django_db
def test_ready_health_checks_database_and_cache() -> None:
    client = APIClient()

    response = client.get(reverse("v1:health-ready"))

    assert response.status_code == 200
    assert response.json()["data"] == {
        "status": "ready",
        "checks": {"database": True, "cache": True},
    }
