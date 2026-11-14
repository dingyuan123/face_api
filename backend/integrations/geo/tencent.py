"""腾讯地图周边地点搜索适配器。"""

from __future__ import annotations

import json
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from django.conf import settings

from backend.integrations.geo.contracts import (
    GeoProviderUnavailable,
    GeoSearchItem,
    GeoSearchResult,
)


class TencentGeoSearchProvider:
    """调用腾讯地点搜索 WebService，只输出业务需要的标准地点字段。"""

    def __init__(self, *, key: str) -> None:
        """使用腾讯地图 WebService Key 初始化适配器，不记录或返回密钥。"""

        self._key = key.strip()

    def search_nearby(
        self,
        *,
        keyword: str,
        latitude: float,
        longitude: float,
        radius_m: int,
        limit: int,
    ) -> GeoSearchResult:
        """按关键词搜索腾讯地图周边 POI，并标准化成功结果。"""

        if not self._key:
            raise GeoProviderUnavailable("腾讯地图 Key 未配置")
        params = {
            "keyword": keyword,
            "boundary": f"nearby({latitude},{longitude},{radius_m})",
            "page_size": max(1, min(limit, 20)),
            "page_index": 1,
            "key": self._key,
        }
        request = Request(
            f"{settings.TENCENT_MAP_API_BASE_URL.rstrip('/')}?{urlencode(params)}",
            headers={
                "Accept": "application/json",
                "User-Agent": "JianMianLiaoGeoSearch/1.0",
            },
        )
        try:
            with urlopen(request, timeout=settings.TENCENT_MAP_TIMEOUT_SECONDS) as response:
                payload = json.loads(response.read(1024 * 1024).decode("utf-8"))
        except (HTTPError, URLError, TimeoutError, json.JSONDecodeError, UnicodeDecodeError):
            raise GeoProviderUnavailable("腾讯地图搜索暂不可用") from None

        if payload.get("status") != 0:
            raise GeoProviderUnavailable("腾讯地图返回业务错误")

        items: list[GeoSearchItem] = []
        for raw in payload.get("data", []):
            location = raw.get("location") or {}
            ad_info = raw.get("ad_info") or {}
            latitude_value = location.get("lat")
            longitude_value = location.get("lng")
            if not isinstance(latitude_value, (int, float)) or not isinstance(
                longitude_value, (int, float)
            ):
                continue
            items.append(
                GeoSearchItem(
                    provider_poi_id=str(raw.get("id", ""))[:255],
                    name=str(raw.get("title", ""))[:200],
                    address=str(raw.get("address", ""))[:500],
                    province=str(ad_info.get("province", ""))[:100],
                    city=str(ad_info.get("city", ""))[:100],
                    district=str(ad_info.get("district", ""))[:100],
                    category_code=str(raw.get("type", ""))[:100],
                    category_name=str(raw.get("category", ""))[:200],
                    latitude=float(latitude_value),
                    longitude=float(longitude_value),
                    phone=str(raw.get("tel", ""))[:50],
                )
            )
        return GeoSearchResult(
            items=items,
            provider_total=int(payload.get("count", len(items))),
            provider="TENCENT_MAP",
        )
