"""公开服务协议和隐私政策页面测试。"""

from __future__ import annotations

import pytest
from django.test import Client

from backend.legal.services import markdown_to_safe_html


@pytest.mark.parametrize(
    ("path", "title"),
    [
        ("/terms/", "见面聊用户服务协议"),
        ("/privacy/", "见面聊用户隐私政策"),
        ("/legal/terms/", "见面聊用户服务协议"),
        ("/legal/privacy/", "见面聊用户隐私政策"),
    ],
)
def test_legal_pages_are_public_and_cacheable(client: Client, path: str, title: str) -> None:
    response = client.get(path)

    assert response.status_code == 200
    assert title in response.content.decode("utf-8")
    assert response["Cache-Control"] == "public, max-age=3600"


def test_legal_markdown_renderer_escapes_raw_html() -> None:
    rendered = markdown_to_safe_html("# 标题\n\n<script>alert(1)</script>")

    assert "<h1>标题</h1>" in rendered
    assert "<script>" not in rendered
    assert "&lt;script&gt;" in rendered


def test_unknown_legal_document_returns_404(client: Client) -> None:
    response = client.get("/legal/unknown/")

    assert response.status_code == 404
