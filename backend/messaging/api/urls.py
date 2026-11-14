"""订单实时聊天 HTTP 路由。"""

from django.urls import path

from backend.messaging.api.views import (
    ConversationHideView,
    ConversationListView,
    ConversationMessagesView,
    ConversationReadView,
    OrderConversationView,
    ProviderConversationView,
    UnreadSummaryView,
    WebSocketTicketView,
)

urlpatterns = [
    path(
        "orders/<uuid:order_no>/conversation/",
        OrderConversationView.as_view(),
        name="order-conversation",
    ),
    path(
        "messaging/conversations/providers/<uuid:provider_public_id>/",
        ProviderConversationView.as_view(),
        name="provider-conversation",
    ),
    path("conversations/", ConversationListView.as_view(), name="conversation-list"),
    path(
        "conversations/<uuid:conversation_id>/",
        ConversationHideView.as_view(),
        name="conversation-hide",
    ),
    path(
        "conversations/<uuid:conversation_id>/messages/",
        ConversationMessagesView.as_view(),
        name="conversation-messages",
    ),
    path(
        "conversations/<uuid:conversation_id>/read/",
        ConversationReadView.as_view(),
        name="conversation-read",
    ),
    path("messaging/unread-summary/", UnreadSummaryView.as_view(), name="messaging-unread-summary"),
    path("messaging/ws-ticket/", WebSocketTicketView.as_view(), name="messaging-ws-ticket"),
]
