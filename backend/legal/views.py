"""无需登录即可访问的法律文本公开页面。"""

from __future__ import annotations

from pathlib import Path

from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import render
from django.views.decorators.cache import cache_control

from backend.legal.services import extract_title, markdown_to_safe_html

DOCUMENTS = {
    "terms": {
        "filename": "user-agreement.md",
        "title": "见面聊用户服务协议",
    },
    "privacy": {
        "filename": "privacy-policy.md",
        "title": "见面聊用户隐私政策",
    },
}


@cache_control(public=True, max_age=3600)
def legal_document_view(request: HttpRequest, document_key: str) -> HttpResponse:
    """按文档标识返回公开 HTML 页面，不读取登录状态。"""
    document = DOCUMENTS.get(document_key)
    if document is None:
        raise Http404

    document_path = Path(__file__).parent / "documents" / document["filename"]
    try:
        source = document_path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise Http404 from exc

    return render(
        request,
        "legal/document.html",
        {
            "title": extract_title(source, document["title"]),
            "content": markdown_to_safe_html(source),
        },
    )
