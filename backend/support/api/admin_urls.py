"""客服工作台接口路由。"""

from django.urls import path

from backend.support.api.views import (
    AdminSupportFAQDetailView,
    AdminSupportFAQView,
    AdminSupportTicketActionView,
    AdminSupportTicketAssignView,
    AdminSupportTicketListView,
    AdminSupportTicketMessageView,
)

urlpatterns = [
    path("support/tickets/", AdminSupportTicketListView.as_view(), name="admin-v1-support-tickets"),
    path(
        "support/tickets/<uuid:ticket_no>/messages/",
        AdminSupportTicketMessageView.as_view(),
        name="admin-v1-support-ticket-messages",
    ),
    path(
        "support/tickets/<uuid:ticket_no>/assign/",
        AdminSupportTicketAssignView.as_view(),
        name="admin-v1-support-ticket-assign",
    ),
    path(
        "support/tickets/<uuid:ticket_no>/actions/<str:action>/",
        AdminSupportTicketActionView.as_view(),
        name="admin-v1-support-ticket-action",
    ),
    path("support/faqs/", AdminSupportFAQView.as_view(), name="admin-v1-support-faqs"),
    path(
        "support/faqs/<int:faq_id>/",
        AdminSupportFAQDetailView.as_view(),
        name="admin-v1-support-faq-detail",
    ),
]
