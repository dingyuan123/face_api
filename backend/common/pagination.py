from __future__ import annotations

from collections.abc import Sequence
from typing import Any
from urllib.parse import parse_qs, urlparse

from rest_framework.pagination import CursorPagination
from rest_framework.request import Request
from rest_framework.response import Response

from backend.common.renderers import build_success_envelope


class ApiCursorPagination(CursorPagination):
    page_size = 20
    max_page_size = 100
    ordering = "-created_at"
    cursor_query_param = "cursor"
    page_size_query_param = "limit"

    def get_paginated_response(self, data: Sequence[Any]) -> Response:
        return Response(
            build_success_envelope(
                list(data),
                {
                    "next_cursor": self.get_next_link_cursor(),
                    "has_more": self.get_next_link() is not None,
                    "limit": self.get_page_size(self.request),
                },
            )
        )

    def get_next_link_cursor(self) -> str | None:
        if not self.has_next:
            return None
        next_link = self.get_next_link()
        if not next_link:
            return None
        values = parse_qs(urlparse(next_link).query).get(self.cursor_query_param)
        return values[0] if values else None

    def get_page_size(self, request: Request) -> int:
        return super().get_page_size(request) or self.page_size
