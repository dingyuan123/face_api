from django.urls import path

from backend.social.api.views import (
    CommentDeleteView,
    FavoriteListView,
    FavoriteView,
    FollowingListView,
    MomentCommentsView,
    MomentLikeView,
    UserFollowView,
)

urlpatterns = [
    path(
        "users/<uuid:user_public_id>/follow/",
        UserFollowView.as_view(),
        name="user-follow",
    ),
    path("favorites/", FavoriteView.as_view(), name="favorites"),
    path("me/favorites/", FavoriteListView.as_view(), name="me-favorites"),
    path("me/following/", FollowingListView.as_view(), name="me-following"),
    path(
        "moments/<uuid:moment_id>/like/",
        MomentLikeView.as_view(),
        name="moment-like",
    ),
    path(
        "moments/<uuid:moment_id>/comments/",
        MomentCommentsView.as_view(),
        name="moment-comments",
    ),
    path(
        "comments/<uuid:comment_id>/",
        CommentDeleteView.as_view(),
        name="comment-delete",
    ),
]
