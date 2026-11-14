"""分享邀请 H5 落地页托管接口。"""

from __future__ import annotations

from pathlib import Path

from django.conf import settings
from django.http import FileResponse, HttpRequest, HttpResponse


def invite_landing_view(request: HttpRequest) -> HttpResponse:
    """返回前端提交的邀请落地页，保留 URL 中的归因查询参数。"""

    landing_file = Path(settings.H5_ROOT) / "invite" / "index.html"
    if not landing_file.is_file():
        return HttpResponse(
            "邀请落地页不存在", status=404, content_type="text/plain; charset=utf-8"
        )
    response = FileResponse(
        landing_file.open("rb"),
        content_type="text/html; charset=utf-8",
    )
    response["Cache-Control"] = "public, max-age=300"
    return response
