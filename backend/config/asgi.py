import os

from django.core.asgi import get_asgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "backend.config.settings.dev")

django_asgi_app = get_asgi_application()

from channels.routing import ProtocolTypeRouter, URLRouter  # noqa: E402
from channels.security.websocket import OriginValidator  # noqa: E402
from django.conf import settings  # noqa: E402

from backend.messaging.websocket_urls import websocket_urlpatterns  # noqa: E402


class NativeFriendlyOriginValidator(OriginValidator):
    """允许未携带 Origin 的原生客户端连接，并继续校验浏览器提供的 Origin。"""

    def valid_origin(self, parsed_origin):
        """原生应用可能不发送 Origin；浏览器若发送则必须命中允许列表。"""

        return parsed_origin is None or super().valid_origin(parsed_origin)


application = ProtocolTypeRouter(
    {
        "http": django_asgi_app,
        "websocket": NativeFriendlyOriginValidator(
            URLRouter(websocket_urlpatterns),
            settings.ALLOWED_HOSTS,
        ),
    }
)
