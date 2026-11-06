from django.urls import path

from backend.reviews.api.views import (
    MyReviewsView,
    OrderReviewView,
    ProviderReviewDetailView,
    ProviderReviewManagementListView,
    ProviderReviewReplyView,
    ProviderReviewsView,
    ReviewReplyView,
    ReviewTagOptionsView,
)

urlpatterns = [
    path("orders/<uuid:order_no>/reviews/", OrderReviewView.as_view(), name="order-reviews"),
    path("me/reviews/", MyReviewsView.as_view(), name="my-reviews"),
    path(
        "provider-reviews/",
        ProviderReviewManagementListView.as_view(),
        name="provider-review-management",
    ),
    path(
        "provider-reviews/<uuid:review_id>/",
        ProviderReviewDetailView.as_view(),
        name="provider-review-detail",
    ),
    path(
        "provider-reviews/<uuid:review_id>/reply/",
        ProviderReviewReplyView.as_view(),
        name="provider-review-reply",
    ),
    path(
        "providers/<uuid:provider_public_id>/reviews/",
        ProviderReviewsView.as_view(),
        name="provider-reviews",
    ),
    path("reviews/<uuid:review_id>/replies/", ReviewReplyView.as_view(), name="review-replies"),
    path("review-options/tags/", ReviewTagOptionsView.as_view(), name="review-tags"),
]
