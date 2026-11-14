"""订单实时聊天 WebSocket 路由。"""

from django.urls import re_path

from backend.messaging.consumers import MessagingConsumer

websocket_urlpatterns = [
    re_path(r"^ws/messages/$", MessagingConsumer.as_asgi()),
]
