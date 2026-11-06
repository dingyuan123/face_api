from __future__ import annotations

import pytest
from django.contrib.auth.hashers import make_password
from django.test import Client
from django.urls import reverse

from backend.accounts.models import User
from backend.accounts.services import hash_phone, mask_phone

pytestmark = pytest.mark.django_db


def test_django_admin_uses_phone_login_and_opens_read_only_dashboard() -> None:
    phone = "13800000001"
    User.objects.create(
        phone_hash=hash_phone(phone),
        phone_masked=mask_phone(phone),
        password=make_password("AdminTest!2026Secure"),
        status=User.Status.ACTIVE,
        is_staff=True,
    )
    client = Client()

    response = client.post(
        reverse("admin:login"),
        {
            "username": phone,
            "password": "AdminTest!2026Secure",
            "next": reverse("admin:index"),
        },
        HTTP_HOST="localhost",
    )
    dashboard = client.get(reverse("admin:index"), HTTP_HOST="localhost")

    assert response.status_code == 302
    assert dashboard.status_code == 200
    assert "见面聊运营管理" in dashboard.content.decode("utf-8")
