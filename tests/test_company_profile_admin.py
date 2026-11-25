"""管理后台公司简介和营业执照维护 API 测试。"""

from __future__ import annotations

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from django.urls import reverse
from rest_framework.test import APIClient

from backend.adminops.models import AdminOperationLog, CompanyProfile
from backend.media.models import MediaAsset
from tests.test_admin_v1 import create_admin, login_headers
from tests.test_media_upload import image_bytes

pytestmark = pytest.mark.django_db


def test_public_company_profile_is_empty_before_configuration() -> None:
    client = APIClient()

    response = client.get(reverse("v1:company-profile"))

    assert response.status_code == 200
    assert response.json()["data"] == {
        "company_name": "",
        "introduction": "",
        "business_license_media": None,
        "has_business_license": False,
    }


@override_settings(MEDIA_ROOT="var/test-company-profile-media")
def test_admin_can_create_update_and_upload_company_profile_license() -> None:
    client = APIClient()
    create_admin("13800130030")
    headers = login_headers(client, "13800130030")

    initial = client.get(reverse("admin-v1-company-profile"), **headers)
    created = client.patch(
        reverse("admin-v1-company-profile"),
        {
            "expected_version": 0,
            "company_name": "见面聊科技有限公司",
            "introduction": "专注于安全、真实、有边界的线下社交服务平台。",
        },
        format="json",
        HTTP_IDEMPOTENCY_KEY="company-profile-create",
        **headers,
    )
    replayed_create = client.patch(
        reverse("admin-v1-company-profile"),
        {
            "expected_version": 0,
            "company_name": "见面聊科技有限公司",
            "introduction": "专注于安全、真实、有边界的线下社交服务平台。",
        },
        format="json",
        HTTP_IDEMPOTENCY_KEY="company-profile-create",
        **headers,
    )
    conflicting_replay = client.patch(
        reverse("admin-v1-company-profile"),
        {
            "expected_version": 0,
            "company_name": "另一家公司",
            "introduction": "同一幂等键不能提交不同公司资料。",
        },
        format="json",
        HTTP_IDEMPOTENCY_KEY="company-profile-create",
        **headers,
    )
    uploaded = client.post(
        reverse("admin-v1-company-license-upload"),
        {
            "file": SimpleUploadedFile(
                "business-license.jpg",
                image_bytes(),
                "image/jpeg",
            )
        },
        format="multipart",
        HTTP_IDEMPOTENCY_KEY="company-license-upload",
        **headers,
    )
    replayed_upload = client.post(
        reverse("admin-v1-company-license-upload"),
        {
            "file": SimpleUploadedFile(
                "business-license.jpg",
                image_bytes(),
                "image/jpeg",
            )
        },
        format="multipart",
        HTTP_IDEMPOTENCY_KEY="company-license-upload",
        **headers,
    )
    media_id = uploaded.json()["data"]["media_id"]
    attached = client.patch(
        reverse("admin-v1-company-profile"),
        {
            "expected_version": created.json()["data"]["version"],
            "business_license_media_id": media_id,
        },
        format="json",
        **headers,
    )
    stale_update = client.patch(
        reverse("admin-v1-company-profile"),
        {
            "expected_version": created.json()["data"]["version"],
            "introduction": "并发写入应被拒绝。",
        },
        format="json",
        **headers,
    )

    assert initial.status_code == 200
    assert initial.json()["data"]["version"] == 0
    assert initial.json()["data"]["business_license_media"] is None
    assert created.status_code == 200
    assert created.json()["data"]["version"] == 1
    assert replayed_create.status_code == 200
    assert replayed_create.json()["data"]["version"] == 1
    assert conflicting_replay.status_code == 409
    assert conflicting_replay.json()["code"] == "ADMIN_IDEMPOTENCY_CONFLICT"
    assert uploaded.status_code == 201
    assert replayed_upload.status_code == 200
    assert replayed_upload.json()["data"]["reused"] is True
    assert attached.status_code == 200
    assert attached.json()["data"]["has_business_license"] is True
    assert attached.json()["data"]["business_license_media"]["display_url"]
    assert stale_update.status_code == 409
    assert CompanyProfile.objects.count() == 1
    assert MediaAsset.objects.get(public_id=media_id).purpose == (
        MediaAsset.Purpose.COMPANY_BUSINESS_LICENSE
    )
    assert (
        AdminOperationLog.objects.filter(
            action__in={"COMPANY_PROFILE_CREATE", "COMPANY_PROFILE_UPDATE"},
            target_type="COMPANY_PROFILE",
        ).count()
        == 2
    )
    assert (
        AdminOperationLog.objects.filter(
            action="COMPANY_LICENSE_UPLOAD",
            target_type="COMPANY_LICENSE",
        ).count()
        == 1
    )
    assert "storage_key" not in str(attached.json())


def test_company_profile_rejects_invalid_create_media_and_permissions() -> None:
    client = APIClient()
    create_admin("13800130031")
    unauthorized = client.get(reverse("admin-v1-company-profile"))
    headers = login_headers(client, "13800130031")
    missing_introduction = client.patch(
        reverse("admin-v1-company-profile"),
        {
            "expected_version": 0,
            "company_name": "见面聊科技有限公司",
        },
        format="json",
        **headers,
    )
    created = client.patch(
        reverse("admin-v1-company-profile"),
        {
            "expected_version": 0,
            "company_name": "见面聊科技有限公司",
            "introduction": "公司简介",
        },
        format="json",
        **headers,
    )
    invalid_media = client.patch(
        reverse("admin-v1-company-profile"),
        {
            "expected_version": created.json()["data"]["version"],
            "business_license_media_id": "not-a-uuid",
        },
        format="json",
        **headers,
    )

    assert unauthorized.status_code in {401, 403}
    assert missing_introduction.status_code == 400
    assert created.status_code == 200
    assert invalid_media.status_code == 400
    assert invalid_media.json()["code"] == "SYSTEM_VALIDATION_ERROR"


def test_public_company_profile_returns_safe_license_display_url() -> None:
    client = APIClient()
    admin = create_admin("13800130032")
    license_asset = MediaAsset.objects.create(
        owner=admin,
        purpose=MediaAsset.Purpose.COMPANY_BUSINESS_LICENSE,
        storage_key="public-company-license/test-license.jpg",
        content_type="image/jpeg",
        extension="jpg",
        byte_size=1024,
        width=800,
        height=600,
        sha256="a" * 64,
        request_fingerprint="b" * 64,
    )
    CompanyProfile.objects.create(
        company_name="见面聊科技有限公司",
        introduction="公开的公司简介。",
        business_license_media_id=str(license_asset.public_id),
        updated_by=admin.id,
    )

    response = client.get(reverse("v1:company-profile"))
    data = response.json()["data"]

    assert response.status_code == 200
    assert data["company_name"] == "见面聊科技有限公司"
    assert data["introduction"] == "公开的公司简介。"
    assert data["has_business_license"] is True
    assert data["business_license_media"]["media_id"] == str(license_asset.public_id)
    assert data["business_license_media"]["display_url"]
    assert data["business_license_media"]["display_url_expires_at"]
    assert "content_url" not in data["business_license_media"]
    assert "storage_key" not in str(data)
    assert "updated_by" not in data
    assert "version" not in data
