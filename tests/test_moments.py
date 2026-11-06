from __future__ import annotations

import uuid
from datetime import timedelta

import pytest
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from backend.accounts.models import AuthToken, User
from backend.accounts.services import _token_raw, hash_token
from backend.catalog.models import ProviderService, ServiceCategory
from backend.content.models import Moment
from backend.media.models import MediaAsset
from backend.profiles.models import UserProfile
from backend.providers.models import ProviderProfile

pytestmark = pytest.mark.django_db


def create_user(phone_hash: str, *, is_staff: bool = False, provider: bool = True) -> User:
    user = User.objects.create(
        phone_hash=phone_hash,
        phone_masked="138****8000",
        is_staff=is_staff,
        initial_role_selected=True,
        primary_role=User.InitialRole.PROVIDER if provider else User.InitialRole.USER,
        default_workspace=User.Workspace.PROVIDER_WORKSPACE
        if provider
        else User.Workspace.USER_HOME,
        provider_status=User.ProviderStatus.APPROVED
        if provider
        else User.ProviderStatus.NOT_SUBMITTED,
        provider_enabled=provider,
    )
    if provider:
        avatar_media_id = str(uuid.uuid4())
        MediaAsset.objects.create(
            public_id=avatar_media_id,
            owner=user,
            purpose=MediaAsset.Purpose.PROVIDER_PROFILE_AVATAR,
            storage_key=f"moment-profile/{user.id}/{avatar_media_id}",
            content_type="image/jpeg",
            extension="jpg",
            byte_size=1024,
            width=800,
            height=800,
            sha256=uuid.uuid4().hex + uuid.uuid4().hex,
            request_fingerprint=uuid.uuid4().hex + uuid.uuid4().hex,
        )
        UserProfile.objects.create(
            user=user,
            nickname=f"moment-user-{user.id}",
            gender="MALE",
            age=28,
            city_code="LZ",
        )
        ProviderProfile.objects.create(
            user=user,
            nickname=f"moment-provider-{user.id}",
            signature="耐心细致",
            introduction="擅长台球基础教学和轻松陪练，适合新手入门练习。",
            avatar_media_id=avatar_media_id,
        )
    return user


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


def create_media(user: User, marker: str) -> str:
    media_id = str(uuid.uuid4())
    content_hash = uuid.uuid4().hex + uuid.uuid4().hex
    MediaAsset.objects.create(
        public_id=media_id,
        owner=user,
        purpose=MediaAsset.Purpose.MOMENT_IMAGE,
        storage_key=f"moment/{user.id}/{media_id}",
        content_type="image/jpeg",
        extension="jpg",
        byte_size=1024,
        width=800,
        height=800,
        sha256=content_hash,
        request_fingerprint=content_hash,
    )
    return media_id


def create_service(user: User) -> ProviderService:
    return ProviderService.objects.create(
        provider_user=user,
        category=ServiceCategory.objects.get(code="SPORT"),
        title="台球助教",
        price_amount_minor=6800,
        duration_minutes=60,
        introduction="适合新手学习基础动作。",
        cover_media_id=str(uuid.uuid4()),
        status=ProviderService.Status.ONLINE,
        request_fingerprint="service-fingerprint",
    )


def moment_body(user: User) -> dict:
    return {
        "category_code": "SPORT",
        "content": "今天在泸州练习台球，欢迎一起交流。",
        "media_ids": [create_media(user, "moment-0"), create_media(user, "moment-1")],
        "tag_codes": ["SPORT"],
    }


def create_published_moment(
    user: User,
    content: str,
    *,
    published_at,
) -> str:
    client = APIClient()
    created = client.post(
        reverse("v1:provider-moments"),
        {**moment_body(user), "content": content},
        format="json",
        **auth_headers(user),
    )
    moment_id = created.json()["data"]["id"]
    client.post(
        reverse("v1:provider-moment-publish", args=[moment_id]),
        {"expected_version": 1},
        format="json",
        **auth_headers(user),
    )
    Moment.objects.filter(public_id=moment_id).update(published_at=published_at)
    return moment_id


def test_provider_can_create_publish_and_query_image_moment() -> None:
    client = APIClient()
    user = create_user("moment-user")
    service = create_service(user)
    body = {**moment_body(user), "attached_service_id": str(service.public_id)}

    created = client.post(
        reverse("v1:provider-moments"),
        body,
        format="json",
        **auth_headers(user),
    )
    moment_id = created.json()["data"]["id"]
    published = client.post(
        reverse("v1:provider-moment-publish", args=[moment_id]),
        {"expected_version": 1},
        format="json",
        **auth_headers(user),
    )
    public_list = client.get(reverse("v1:public-moments"))
    public_detail = client.get(reverse("v1:public-moment-detail", args=[moment_id]))

    assert created.status_code == 201
    assert created.json()["data"]["status"] == "DRAFT"
    assert published.status_code == 200
    assert published.json()["data"]["status"] == "PUBLISHED"
    assert published.json()["data"]["cover_media"]["display_url"]
    assert published.json()["data"]["provider"]["avatar_media"]["display_url"]
    assert published.json()["data"]["provider"]["verification"] == {
        "real_name_status": "NOT_SUBMITTED",
        "face_status": "NOT_SUBMITTED",
    }
    assert published.json()["data"]["attached_service"]["price"]["amount_minor"] == 6800
    assert public_list.status_code == 200
    assert public_list.json()["data"][0]["id"] == moment_id
    assert public_detail.status_code == 200


def test_moment_categories_and_public_tabs_are_configurable() -> None:
    client = APIClient()
    user = create_user("moment-tabs-user")
    now = timezone.now()
    moment_id = create_published_moment(
        user,
        "同城运动动态",
        published_at=now,
    )

    categories = client.get(reverse("v1:moment-categories"))
    recommended = client.get(f"{reverse('v1:public-moments')}?tab=RECOMMENDED&category_code=SPORT")
    nearby = client.get(f"{reverse('v1:public-moments')}?tab=NEARBY&city_code=LZ")
    following = client.get(f"{reverse('v1:public-moments')}?tab=FOLLOWING")

    assert categories.status_code == 200
    assert "SPORT" in [item["code"] for item in categories.json()["data"]]
    assert recommended.status_code == nearby.status_code == 200
    assert recommended.json()["data"][0]["id"] == moment_id
    assert recommended.json()["meta"]["strategy"] == "NEWEST"
    assert nearby.json()["meta"]["location_mode"] == "CITY"
    assert following.status_code == 200
    assert following.json()["meta"]["available"] is False


def test_moment_mountable_services_and_management_validation() -> None:
    client = APIClient()
    user = create_user("moment-validation-user")
    service = create_service(user)

    mountable = client.get(
        reverse("v1:moment-mountable-services"),
        **auth_headers(user),
    )
    missing_media = client.post(
        reverse("v1:provider-moments"),
        {"content": "缺少图片", "media_ids": []},
        format="json",
        **auth_headers(user),
    )
    invalid_service = client.post(
        reverse("v1:provider-moments"),
        {
            **moment_body(user),
            "attached_service_id": str(uuid.uuid4()),
        },
        format="json",
        **auth_headers(user),
    )

    assert mountable.status_code == 200
    assert [item["id"] for item in mountable.json()["data"]] == [str(service.public_id)]
    assert missing_media.status_code == 400
    assert invalid_service.status_code == 400


def test_moment_update_delete_and_public_visibility() -> None:
    client = APIClient()
    user = create_user("moment-delete-user")
    body = moment_body(user)
    created = client.post(
        reverse("v1:provider-moments"),
        body,
        format="json",
        **auth_headers(user),
    )
    moment_id = created.json()["data"]["id"]
    published = client.post(
        reverse("v1:provider-moment-publish", args=[moment_id]),
        {"expected_version": 1},
        format="json",
        **auth_headers(user),
    )
    invalid_edit = client.patch(
        reverse("v1:provider-moment-detail", args=[moment_id]),
        {"expected_version": 2, "content": "已发布内容不能直接修改"},
        format="json",
        **auth_headers(user),
    )
    deleted = client.delete(
        reverse("v1:provider-moment-detail", args=[moment_id]),
        {"expected_version": 2},
        format="json",
        **auth_headers(user),
    )
    public_detail = client.get(reverse("v1:public-moment-detail", args=[moment_id]))

    assert published.json()["data"]["status"] == "PUBLISHED"
    assert invalid_edit.status_code == 409
    assert deleted.status_code == 200
    assert public_detail.status_code == 404


@override_settings(MOMENT_REVIEW_MODE="REVIEW_REQUIRED")
def test_review_mode_can_keep_moment_pending_for_admin_review() -> None:
    client = APIClient()
    user = create_user("moment-review-user")
    admin = create_user("moment-review-admin", is_staff=True, provider=False)
    created = client.post(
        reverse("v1:provider-moments"),
        moment_body(user),
        format="json",
        **auth_headers(user),
    )
    moment_id = created.json()["data"]["id"]
    published = client.post(
        reverse("v1:provider-moment-publish", args=[moment_id]),
        {"expected_version": 1},
        format="json",
        **auth_headers(user),
    )
    approved = client.post(
        reverse("v1:admin-moment-approve", args=[moment_id]),
        {"expected_version": 2},
        format="json",
        **auth_headers(admin),
    )

    assert published.json()["data"]["status"] == "PENDING"
    assert approved.status_code == 200
    assert approved.json()["data"]["status"] == "PUBLISHED"


def test_moment_neighbors_follow_stable_newest_order() -> None:
    client = APIClient()
    user = create_user("moment-neighbor-user")
    viewer = create_user("moment-neighbor-viewer")
    now = timezone.now()
    oldest = create_published_moment(user, "最旧的动态", published_at=now - timedelta(minutes=2))
    middle = create_published_moment(user, "中间的动态", published_at=now - timedelta(minutes=1))
    newest = create_published_moment(user, "最新的动态", published_at=now)
    client.post(
        reverse("v1:moment-like", args=[middle]),
        **auth_headers(viewer),
    )

    neighbors = client.get(
        reverse("v1:public-moment-neighbors", args=[middle]),
        {"sort": "NEWEST"},
        **auth_headers(viewer),
    )
    top = client.get(
        reverse("v1:public-moment-neighbors", args=[newest]),
        {"sort": "NEWEST"},
    )
    bottom = client.get(
        reverse("v1:public-moment-neighbors", args=[oldest]),
        {"sort": "NEWEST"},
    )

    assert neighbors.status_code == top.status_code == bottom.status_code == 200
    assert neighbors.json()["data"]["previous"]["id"] == newest
    assert neighbors.json()["data"]["next"]["id"] == oldest
    assert neighbors.json()["data"]["current"]["viewer_state"]["is_liked"] is True
    assert neighbors.json()["data"]["previous"]["viewer_state"]["is_liked"] is False
    assert neighbors.json()["data"]["next"]["viewer_state"]["is_liked"] is False
    assert top.json()["data"]["previous"] is None
    assert top.json()["data"]["has_previous"] is False
    assert bottom.json()["data"]["next"] is None
    assert bottom.json()["data"]["has_next"] is False


def test_moment_neighbors_keep_filter_context_and_reject_other_sorts() -> None:
    client = APIClient()
    user = create_user("moment-neighbor-filter-user")
    now = timezone.now()
    first = create_published_moment(user, "台球动态一", published_at=now - timedelta(minutes=1))
    second = create_published_moment(user, "台球动态二", published_at=now)

    filtered = client.get(
        reverse("v1:public-moment-neighbors", args=[first]),
        {"keyword": "台球", "sort": "NEWEST"},
    )
    empty = client.get(
        reverse("v1:public-moment-neighbors", args=[first]),
        {"keyword": "不存在的关键词", "sort": "NEWEST"},
    )
    invalid_sort = client.get(
        reverse("v1:public-moment-neighbors", args=[second]),
        {"sort": "HOT"},
    )

    assert filtered.status_code == 200
    assert filtered.json()["data"]["previous"]["id"] == second
    assert filtered.json()["data"]["feed_context"]["keyword"] == "台球"
    assert empty.status_code == 404
    assert invalid_sort.status_code == 400
