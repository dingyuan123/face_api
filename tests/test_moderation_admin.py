"""内容举报和敏感词管理测试。"""

from __future__ import annotations

import pytest
from django.urls import reverse
from rest_framework.test import APIClient

from backend.moderation.models import ContentReport, SensitiveWord
from backend.moderation.services import create_content_report
from tests.test_admin_v1 import create_admin, login_headers

pytestmark = pytest.mark.django_db


def test_user_can_submit_report_and_admin_can_review_it() -> None:
    client = APIClient()
    admin = create_admin("13800130020")
    reporter = create_admin("13800130021")
    report = create_content_report(
        user=reporter,
        payload={
            "target_type": "MOMENT",
            "target_id": "moment-1",
            "reason": "内容不合规",
            "evidence_urls": [],
        },
    )
    headers = login_headers(client, "13800130020")

    listing = client.get(reverse("admin-v1-reports"), **headers)
    reviewed = client.post(
        reverse("admin-v1-report-review", args=[report.report_no, "resolve"]),
        {"expected_version": report.version, "resolution": "已下架内容"},
        format="json",
        **headers,
    )

    assert listing.status_code == reviewed.status_code == 200
    assert listing.json()["data"]["total"] == 1
    assert reviewed.json()["data"]["status"] == "RESOLVED"
    assert ContentReport.objects.get(pk=report.pk).handled_by == admin.id


def test_admin_can_create_update_and_disable_sensitive_word() -> None:
    client = APIClient()
    create_admin("13800130022")
    headers = login_headers(client, "13800130022")

    created = client.post(
        reverse("admin-v1-sensitive-words"),
        {"word": "测试敏感词", "category": "TEST", "action": "REVIEW"},
        format="json",
        **headers,
    )
    updated = client.patch(
        reverse("admin-v1-sensitive-word-detail", args=[created.json()["data"]["word_id"]]),
        {
            "expected_version": created.json()["data"]["version"],
            "action": "BLOCK",
        },
        format="json",
        **headers,
    )
    deleted = client.delete(
        reverse("admin-v1-sensitive-word-detail", args=[created.json()["data"]["word_id"]]),
        {"expected_version": updated.json()["data"]["version"]},
        format="json",
        **headers,
    )

    assert created.status_code == 201
    assert updated.status_code == deleted.status_code == 200
    assert created.json()["data"]["action"] == "REVIEW"
    assert updated.json()["data"]["action"] == "BLOCK"
    assert SensitiveWord.objects.get(pk=created.json()["data"]["word_id"]).status == "DISABLED"
