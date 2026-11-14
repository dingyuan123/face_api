"""用户服务协议和隐私政策公开地址。"""

from django.urls import path

from backend.legal.views import legal_document_view

urlpatterns = [
    path("terms/", legal_document_view, {"document_key": "terms"}, name="legal-terms"),
    path("privacy/", legal_document_view, {"document_key": "privacy"}, name="legal-privacy"),
    path(
        "legal/terms/",
        legal_document_view,
        {"document_key": "terms"},
        name="legal-terms-canonical",
    ),
    path(
        "legal/privacy/",
        legal_document_view,
        {"document_key": "privacy"},
        name="legal-privacy-canonical",
    ),
]
