from __future__ import annotations

from django.test import TestCase
from django.urls import reverse


class CorsTests(TestCase):
    def test_development_allows_lan_frontend_origin(self) -> None:
        origin = "http://192.168.10.3:5173"
        response = self.client.options(
            reverse("v1:health-live"),
            HTTP_ORIGIN=origin,
            HTTP_ACCESS_CONTROL_REQUEST_METHOD="GET",
            HTTP_ACCESS_CONTROL_REQUEST_HEADERS="authorization,content-type",
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn(response["Access-Control-Allow-Origin"], {origin, "*"})
        self.assertIn("authorization", response["Access-Control-Allow-Headers"].lower())
        self.assertIn("content-type", response["Access-Control-Allow-Headers"].lower())
