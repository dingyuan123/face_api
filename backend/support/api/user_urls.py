"""用户客服工单接口路由。"""

from django.urls import path

from backend.support.api.views import (
    SupportFAQView,
    SupportMessageView,
    SupportTicketDetailView,
    SupportTicketView,
)

urlpatterns = [
    path("support/tickets/", SupportTicketView.as_view(), name="support-tickets"),
    path(
        "support/tickets/<uuid:ticket_no>/",
        SupportTicketDetailView.as_view(),
        name="support-ticket-detail",
    ),
    path(
        "support/tickets/<uuid:ticket_no>/messages/",
        SupportMessageView.as_view(),
        name="support-ticket-messages",
    ),
    path("support/faqs/", SupportFAQView.as_view(), name="support-faqs"),
]
