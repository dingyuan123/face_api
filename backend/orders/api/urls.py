from django.urls import path

from backend.orders.api.views import (
    AdminOrderRefundRequestApproveView,
    AdminOrderRefundRequestListView,
    AdminOrderRefundRequestRejectView,
    AdminOrderRefundRequestRetryView,
    OrderActionView,
    OrderCancelView,
    OrderDetailView,
    OrderListCreateView,
    OrderPayView,
    OrderQuoteView,
    OrderRefundRequestCancelView,
    OrderRefundRequestView,
    OrderRejectView,
    OrderSummaryView,
)

urlpatterns = [
    path("orders/quotes/", OrderQuoteView.as_view(), name="order-quote"),
    path("orders/summary/", OrderSummaryView.as_view(), name="order-summary"),
    path(
        "orders/<uuid:order_no>/refund-requests/",
        OrderRefundRequestView.as_view(),
        name="order-refund-requests",
    ),
    path(
        "refund-requests/<uuid:request_no>/cancel/",
        OrderRefundRequestCancelView.as_view(),
        name="order-refund-request-cancel",
    ),
    path(
        "admin/refund-requests/",
        AdminOrderRefundRequestListView.as_view(),
        name="admin-order-refund-requests",
    ),
    path(
        "admin/refund-requests/<uuid:request_no>/approve/",
        AdminOrderRefundRequestApproveView.as_view(),
        name="admin-order-refund-request-approve",
    ),
    path(
        "admin/refund-requests/<uuid:request_no>/reject/",
        AdminOrderRefundRequestRejectView.as_view(),
        name="admin-order-refund-request-reject",
    ),
    path(
        "admin/refund-requests/<uuid:request_no>/retry/",
        AdminOrderRefundRequestRetryView.as_view(),
        name="admin-order-refund-request-retry",
    ),
    path("orders/", OrderListCreateView.as_view(), name="orders"),
    path("orders/<uuid:order_no>/", OrderDetailView.as_view(), name="order-detail"),
    path("orders/<uuid:order_no>/pay/", OrderPayView.as_view(), name="order-pay"),
    path("orders/<uuid:order_no>/cancel/", OrderCancelView.as_view(), name="order-cancel"),
    path("orders/<uuid:order_no>/reject/", OrderRejectView.as_view(), name="order-reject"),
    path(
        "orders/<uuid:order_no>/actions/<str:action>/",
        OrderActionView.as_view(),
        name="order-action",
    ),
]
