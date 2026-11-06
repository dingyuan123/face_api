from __future__ import annotations

import io
import time
import uuid
from datetime import timedelta

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone
from PIL import Image
from rest_framework.test import APIClient

from backend.accounts.models import AuthToken, User
from backend.accounts.services import _token_raw, hash_token
from backend.media.models import MediaAsset
from backend.media.storage import open_bytes

pytestmark = pytest.mark.django_db


def create_user(phone_hash: str) -> User:
    return User.objects.create(
        phone_hash=phone_hash,
        phone_masked="138****8000",
    )


def auth_headers(user: User) -> dict[str, str]:
    token_id = uuid.uuid4()
    raw_token = _token_raw(AuthToken.TokenType.ACCESS, token_id)
    AuthToken.objects.create(
        public_id=token_id,
        user=user,
        token_type=AuthToken.TokenType.ACCESS,
        token_hash=hash_token(raw_token),
        expires_at=timezone.now() + timedelta(hours=1),
    )
    return {"HTTP_AUTHORIZATION": f"Bearer {raw_token}"}


def image_bytes(
    color: tuple[int, int, int] = (220, 30, 30),
    *,
    image_format: str = "JPEG",
    with_exif: bool = False,
    size: tuple[int, int] = (800, 600),
) -> bytes:
    image = Image.new("RGB", size, color)
    if with_exif:
        exif = Image.Exif()
        exif[0x010E] = "private image description"
        output = io.BytesIO()
        image.save(output, format=image_format, exif=exif)
        return output.getvalue()
    output = io.BytesIO()
    image.save(output, format=image_format)
    return output.getvalue()


def upload(
    client: APIClient,
    user: User,
    *,
    data: bytes | None = None,
    key: str | None = None,
):
    headers = auth_headers(user)
    if key:
        headers["HTTP_IDEMPOTENCY_KEY"] = key
    return client.post(
        reverse("v1:media-uploads"),
        {
            "purpose": MediaAsset.Purpose.PROVIDER_APPLICATION_AVATAR,
            "file": SimpleUploadedFile("avatar.jpg", data or image_bytes(), "image/jpeg"),
        },
        format="multipart",
        **headers,
    )


@override_settings(MEDIA_ROOT="var/test-media")
def test_upload_image_strips_exif_and_serves_private_content() -> None:
    client = APIClient()
    user = create_user("media-upload-user")

    response = upload(client, user, data=image_bytes(with_exif=True))
    data = response.json()["data"]
    media_id = data["media_id"]
    asset = MediaAsset.objects.get(public_id=media_id)
    with open_bytes(asset.storage_key) as stored_file:
        stored = Image.open(stored_file)
        stored.load()
        stored_exif = stored.getexif()

    assert response.status_code == 201
    assert data["reused"] is False
    assert data["content_type"] == "image/jpeg"
    assert data["content_url"].endswith(f"/media/{media_id}/content/")
    assert data["display_url"].startswith("http://testserver/api/v1/media/display/")
    assert data["display_url_expires_at"]
    assert not stored_exif

    content = client.get(
        reverse("v1:media-content", args=[media_id]),
        **auth_headers(user),
    )
    assert content.status_code == 200
    assert content["Content-Type"] == "image/jpeg"
    assert content["Cache-Control"] == "private, no-store"

    display = client.get(data["display_url"])
    assert display.status_code == 200
    assert display["Content-Type"] == "image/jpeg"


@override_settings(
    MEDIA_ROOT="var/test-media",
    MEDIA_URL_SIGNING_KEY="test-display-signing-key",
    MEDIA_URL_SIGNING_KEY_VERSION="v1",
)
def test_display_url_rejects_tampered_signature_and_expired_token() -> None:
    from backend.media.services import sign_media_display_path

    client = APIClient()
    user = create_user("media-display-token-user")
    media_id = upload(client, user).json()["data"]["media_id"]
    display_url = upload(client, user).json()["data"]["display_url"]

    tampered = display_url.replace("signature=", "signature=bad")
    expired_path = sign_media_display_path(
        media_id,
        expires_at=int(time.time()) - 1,
    )
    expired_url = f"http://testserver{expired_path}"

    assert client.get(tampered).status_code == 403
    assert client.get(expired_url).status_code == 410


@override_settings(MEDIA_ROOT="var/test-media")
def test_display_url_is_reused_until_refresh_buffer() -> None:
    client = APIClient()
    user = create_user("media-display-reuse-user")
    first = upload(client, user).json()["data"]
    second = upload(client, user).json()["data"]

    assert first["display_url"] == second["display_url"]
    assert first["display_url_expires_at"] == second["display_url_expires_at"]


@override_settings(MEDIA_ROOT="var/test-media", MEDIA_MAX_UPLOAD_BYTES=10)
def test_upload_rejects_invalid_and_oversized_images() -> None:
    client = APIClient()
    user = create_user("media-invalid-user")

    invalid = upload(client, user, data=b"bad")
    oversized = upload(client, user, data=image_bytes())

    assert invalid.status_code == 400
    assert invalid.json()["code"] == "MEDIA_UPLOAD_INVALID"
    assert oversized.status_code == 413
    assert oversized.json()["code"] == "MEDIA_UPLOAD_TOO_LARGE"


@override_settings(MEDIA_ROOT="var/test-media")
def test_upload_idempotency_replays_and_rejects_changed_content() -> None:
    client = APIClient()
    user = create_user("media-idempotency-user")

    first = upload(client, user, data=image_bytes(), key="media-1")
    replay = upload(client, user, data=image_bytes(), key="media-1")
    changed = upload(client, user, data=image_bytes((20, 180, 40)), key="media-1")

    assert first.status_code == 201
    assert replay.status_code == 200
    assert replay.json()["data"]["media_id"] == first.json()["data"]["media_id"]
    assert replay.json()["data"]["reused"] is True
    assert changed.status_code == 409
    assert changed.json()["code"] == "MEDIA_IDEMPOTENCY_CONFLICT"


@override_settings(MEDIA_ROOT="var/test-media")
@pytest.mark.parametrize(
    ("image_format", "content_type"),
    [("PNG", "image/png"), ("WEBP", "image/webp")],
)
def test_upload_supports_png_and_webp(
    image_format: str,
    content_type: str,
) -> None:
    client = APIClient()
    user = create_user(f"media-format-{image_format.lower()}")

    response = upload(
        client,
        user,
        data=image_bytes(image_format=image_format),
    )

    assert response.status_code == 201
    assert response.json()["data"]["content_type"] == content_type


@override_settings(MEDIA_ROOT="var/test-media")
def test_upload_rejects_too_small_image() -> None:
    client = APIClient()
    user = create_user("media-small-image")

    response = upload(
        client,
        user,
        data=image_bytes(size=(32, 32)),
    )

    assert response.status_code == 400
    assert response.json()["code"] == "MEDIA_UPLOAD_INVALID"


@override_settings(MEDIA_ROOT="var/test-media")
def test_upload_deduplicates_same_owner_and_purpose_content() -> None:
    client = APIClient()
    user = create_user("media-dedupe-user")

    first = upload(client, user, data=image_bytes())
    second = upload(client, user, data=image_bytes())

    assert first.status_code == 201
    assert second.status_code == 200
    assert second.json()["data"]["reused"] is True
    assert MediaAsset.objects.count() == 1


@override_settings(MEDIA_ROOT="var/test-media")
def test_media_content_denies_other_users() -> None:
    client = APIClient()
    owner = create_user("media-owner")
    other = create_user("media-other")
    media_id = upload(client, owner).json()["data"]["media_id"]

    denied = client.get(
        reverse("v1:media-content", args=[media_id]),
        **auth_headers(other),
    )

    assert denied.status_code == 403
    assert denied.json()["code"] == "MEDIA_ACCESS_DENIED"
