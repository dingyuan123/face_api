"""外部 RSS 或 Atom 资讯适配器，统一输出安全摘要数据。"""

from __future__ import annotations

import html
import ipaddress
import re
import socket
from dataclasses import dataclass
from datetime import datetime
from email.utils import parsedate_to_datetime
from typing import Protocol
from urllib.parse import urlparse
from urllib.request import Request, urlopen
from xml.etree import ElementTree

from django.conf import settings
from django.utils import timezone

from backend.content.news_models import NewsSource


@dataclass(slots=True)
class ExternalNewsItem:
    """外部资讯适配器输出的安全摘要，不包含完整正文。"""

    external_id: str
    title: str
    summary: str
    source_url: str
    canonical_url: str
    image_url: str
    author: str
    source_name: str
    published_at: datetime | None


class NewsProvider(Protocol):
    """第三方资讯来源适配协议，便于后续替换 RSS 或接入授权 API。"""

    def fetch_latest(
        self,
        source: NewsSource,
        *,
        keyword: str = "",
        limit: int = 20,
    ) -> list[ExternalNewsItem]:
        """获取指定来源的最新安全资讯摘要。"""


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].lower()


def _child_text(element: ElementTree.Element, names: set[str]) -> str:
    for child in element.iter():
        if _local_name(child.tag) in names and child.text:
            return child.text.strip()
    return ""


def _plain_text(value: str) -> str:
    """移除 RSS 摘要中的 HTML 标签和危险脚本，仅保留可展示纯文本。"""

    without_scripts = re.sub(
        r"<(script|style)\b[^>]*>.*?</\1>",
        " ",
        value,
        flags=re.IGNORECASE | re.DOTALL,
    )
    without_tags = re.sub(r"<[^>]+>", " ", without_scripts)
    return re.sub(r"\s+", " ", html.unescape(without_tags)).strip()


def _safe_http_url(value: str) -> str:
    normalized = value.strip()
    parsed = urlparse(normalized)
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
        return ""
    try:
        addresses = socket.getaddrinfo(parsed.hostname, parsed.port or 443, type=socket.SOCK_STREAM)
    except OSError:
        return ""
    for address in addresses:
        ip = ipaddress.ip_address(address[4][0])
        if not ip.is_global:
            return ""
    return normalized


def _extract_image(item: ElementTree.Element) -> str:
    for element in item.iter():
        name = _local_name(element.tag)
        if name in {"thumbnail", "content", "enclosure"}:
            value = element.attrib.get("url") or element.attrib.get("href") or ""
            safe_value = _safe_http_url(value)
            if safe_value:
                return safe_value
    html = _child_text(item, {"description", "summary", "content"})
    match = re.search(r"""<img[^>]+src=["']([^"']+)["']""", html, re.IGNORECASE)
    return _safe_http_url(match.group(1)) if match else ""


def _parse_date(value: str) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        try:
            parsed = parsedate_to_datetime(value)
        except (TypeError, ValueError, OverflowError):
            return None
    return parsed if parsed.tzinfo else timezone.make_aware(parsed)


class RssNewsProvider:
    """使用标准库读取 RSS 或 Atom，仅提取摘要、图片、原文链接和署名。"""

    def fetch_latest(
        self,
        source: NewsSource,
        *,
        keyword: str = "",
        limit: int = 20,
    ) -> list[ExternalNewsItem]:
        """读取 RSS 或 Atom 条目并返回安全摘要。"""

        feed_url = source.feed_url.replace("{keyword}", keyword) if source.feed_url else ""
        safe_feed_url = _safe_http_url(feed_url)
        if not safe_feed_url:
            raise ValueError("来源订阅地址不是可访问的公网 HTTP 或 HTTPS 地址")
        request = Request(
            safe_feed_url,
            headers={
                "User-Agent": "JianMianLiaoNewsSync/1.0",
                "Accept": "application/rss+xml, application/atom+xml, application/xml",
            },
        )
        with urlopen(
            request,
            timeout=max(1, settings.NEWS_FETCH_TIMEOUT_SECONDS),
        ) as response:
            content = response.read(5 * 1024 * 1024)
        root = ElementTree.fromstring(content)
        entries = [
            element for element in root.iter() if _local_name(element.tag) in {"item", "entry"}
        ]
        items: list[ExternalNewsItem] = []
        effective_limit = max(1, min(limit, settings.NEWS_FETCH_MAX_ITEMS))
        for entry in entries[:effective_limit]:
            title = _child_text(entry, {"title"})
            source_url = _child_text(entry, {"link", "guid"})
            if not source_url:
                for child in entry:
                    if _local_name(child.tag) == "link":
                        source_url = child.attrib.get("href") or child.text or ""
                        if child.attrib.get("rel", "alternate") == "alternate":
                            break
            safe_source_url = _safe_http_url(source_url)
            if not title or not safe_source_url:
                continue
            external_id = _child_text(entry, {"guid", "id"}) or safe_source_url
            published_at = _parse_date(
                _child_text(entry, {"pubdate", "published", "updated", "date"})
            )
            items.append(
                ExternalNewsItem(
                    external_id=external_id[:255],
                    title=title[:200],
                    summary=_plain_text(_child_text(entry, {"description", "summary"}))[:2000],
                    source_url=safe_source_url,
                    canonical_url=safe_source_url,
                    image_url=_extract_image(entry),
                    author=_child_text(entry, {"creator", "author", "name"})[:100],
                    source_name=source.name,
                    published_at=published_at,
                )
            )
        return items
