from __future__ import annotations

import uuid
from datetime import timedelta

import pytest
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from backend.accounts.models import AuthToken, User
from backend.accounts.services import _token_raw, hash_token
from backend.content.models import Moment
from backend.media.models import MediaAsset
from backend.profiles.models import UserProfile

pytestmark = pytest.mark.django_db


def create_user(phone_hash: str, *, provider: bool = False) -> User:
    user = User.objects.create(
        phone_hash=phone_hash,
        phone_masked="138****8000",
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
    UserProfile.objects.create(
        user=user,
        nickname=f"user-{phone_hash}",
        gender="MALE",
        age=28,
        city_code="LZ",
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


def create_published_moment(user: User) -> Moment:
    return Moment.objects.create(
        provider_user=user,
        content="公开动态",
        status=Moment.Status.PUBLISHED,
        visibility=Moment.Visibility.PUBLIC,
        published_at=timezone.now(),
        request_fingerprint="fingerprint",
    )


def create_user_avatar(user: User) -> str:
    media_id = str(uuid.uuid4())
    content_hash = uuid.uuid4().hex + uuid.uuid4().hex
    MediaAsset.objects.create(
        public_id=media_id,
        owner=user,
        purpose=MediaAsset.Purpose.USER_PROFILE_AVATAR,
        storage_key=f"user-avatar/{user.id}/{media_id}",
        content_type="image/jpeg",
        extension="jpg",
        byte_size=1024,
        width=800,
        height=800,
        sha256=content_hash,
        request_fingerprint=content_hash,
    )
    UserProfile.objects.filter(user=user).update(avatar_media_id=media_id)
    return media_id


def test_follow_and_favorite_are_unique_and_reversible() -> None:
    client = APIClient()
    user = create_user("social-user")
    provider = create_user("social-provider", provider=True)

    followed = client.post(
        reverse("v1:user-follow", args=[provider.public_id]),
        **auth_headers(user),
    )
    repeated_follow = client.post(
        reverse("v1:user-follow", args=[provider.public_id]),
        **auth_headers(user),
    )
    unfavorited = client.delete(
        reverse("v1:favorites"),
        {"target_type": "PROVIDER", "target_id": str(provider.public_id)},
        format="json",
        **auth_headers(user),
    )
    favorited = client.post(
        reverse("v1:favorites"),
        {"target_type": "PROVIDER", "target_id": str(provider.public_id)},
        format="json",
        **auth_headers(user),
    )
    repeated_favorite = client.post(
        reverse("v1:favorites"),
        {"target_type": "PROVIDER", "target_id": str(provider.public_id)},
        format="json",
        **auth_headers(user),
    )
    following = client.get(reverse("v1:me-following"), **auth_headers(user))

    assert followed.status_code == repeated_follow.status_code == 200
    assert favorited.status_code == repeated_favorite.status_code == 200
    assert unfavorited.status_code == 200
    assert following.json()["data"][0]["followed_user_public_id"] == str(provider.public_id)


def test_moment_payload_returns_viewer_interaction_state() -> None:
    client = APIClient()
    user = create_user("viewer-state-user")
    provider = create_user("viewer-state-provider", provider=True)
    moment = create_published_moment(provider)
    detail_url = reverse("v1:public-moment-detail", args=[moment.public_id])

    anonymous_detail = client.get(detail_url)
    initial_detail = client.get(detail_url, **auth_headers(user))
    initial_list = client.get(reverse("v1:public-moments"), **auth_headers(user))

    client.post(
        reverse("v1:moment-like", args=[moment.public_id]),
        **auth_headers(user),
    )
    client.post(
        reverse("v1:favorites"),
        {"target_type": "MOMENT", "target_id": str(moment.public_id)},
        format="json",
        **auth_headers(user),
    )
    client.post(
        reverse("v1:user-follow", args=[provider.public_id]),
        **auth_headers(user),
    )
    interacted_detail = client.get(detail_url, **auth_headers(user))
    interacted_list = client.get(reverse("v1:public-moments"), **auth_headers(user))

    assert anonymous_detail.json()["data"]["viewer_state"] == {
        "is_liked": False,
        "is_favorited": False,
        "is_following": False,
    }
    assert initial_detail.json()["data"]["viewer_state"] == {
        "is_liked": False,
        "is_favorited": False,
        "is_following": False,
    }
    assert initial_list.json()["data"][0]["viewer_state"] == {
        "is_liked": False,
        "is_favorited": False,
        "is_following": False,
    }
    assert interacted_detail.json()["data"]["viewer_state"] == {
        "is_liked": True,
        "is_favorited": True,
        "is_following": True,
    }
    assert interacted_list.json()["data"][0]["viewer_state"] == {
        "is_liked": True,
        "is_favorited": True,
        "is_following": True,
    }


def test_comment_payload_returns_only_public_user_summary() -> None:
    client = APIClient()
    user = create_user("comment-summary-user")
    provider = create_user("comment-summary-provider", provider=True)
    moment = create_published_moment(provider)
    create_user_avatar(user)

    created = client.post(
        reverse("v1:moment-comments", args=[moment.public_id]),
        {"content": "资料展示测试"},
        format="json",
        **auth_headers(user),
    )
    comments = client.get(
        reverse("v1:moment-comments", args=[moment.public_id]),
        **auth_headers(user),
    )

    created_user = created.json()["data"]["user"]
    listed_user = comments.json()["data"][0]["user"]
    assert created_user == listed_user
    assert created_user["public_id"] == str(user.public_id)
    assert created_user["nickname"] == "user-comment-summary-user"
    assert created_user["avatar_media"]["display_url"]
    assert set(created_user) == {"public_id", "nickname", "avatar_media"}
    assert "phone_masked" not in str(created.json())
    assert "phone_hash" not in str(created.json())


def test_moment_likes_and_comments_update_counts_and_respect_ownership() -> None:
    client = APIClient()
    user = create_user("social-moment-user")
    provider = create_user("social-moment-provider", provider=True)
    moment = create_published_moment(provider)

    liked = client.post(
        reverse("v1:moment-like", args=[moment.public_id]),
        **auth_headers(user),
    )
    repeated_like = client.post(
        reverse("v1:moment-like", args=[moment.public_id]),
        **auth_headers(user),
    )
    comment = client.post(
        reverse("v1:moment-comments", args=[moment.public_id]),
        {"content": "很有帮助"},
        format="json",
        **auth_headers(user),
    )
    comments = client.get(
        reverse("v1:moment-comments", args=[moment.public_id]),
        **auth_headers(user),
    )
    deleted = client.delete(
        reverse("v1:comment-delete", args=[comment.json()["data"]["id"]]),
        **auth_headers(user),
    )
    deleted_again = client.delete(
        reverse("v1:comment-delete", args=[comment.json()["data"]["id"]]),
        **auth_headers(user),
    )
    unliked = client.delete(
        reverse("v1:moment-like", args=[moment.public_id]),
        **auth_headers(user),
    )

    moment.refresh_from_db()
    assert liked.status_code == repeated_like.status_code == 200
    assert liked.json()["data"]["like_count"] == 1
    assert comment.status_code == 201
    assert comments.json()["data"][0]["content"] == "很有帮助"
    assert deleted.status_code == 200
    assert deleted_again.status_code == 400
    assert unliked.status_code == 200
    assert moment.like_count == 0
    assert moment.comment_count == 0
