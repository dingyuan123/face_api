"""测试和本地联调使用的静态地点搜索适配器。"""

from __future__ import annotations

from backend.integrations.geo.contracts import GeoSearchItem, GeoSearchResult


class FakeGeoSearchProvider:
    """返回固定 POI 列表，不访问网络，供自动化测试和契约验证使用。"""

    def __init__(self, items: list[GeoSearchItem] | None = None) -> None:
        """初始化静态 POI 列表。"""

        self._items = items or []

    def search_nearby(
        self,
        *,
        keyword: str,
        latitude: float,
        longitude: float,
        radius_m: int,
        limit: int,
    ) -> GeoSearchResult:
        """返回预设地点摘要，忽略外部网络参数。"""

        return GeoSearchResult(
            items=self._items[:limit],
            provider_total=len(self._items),
            provider="FAKE",
        )
