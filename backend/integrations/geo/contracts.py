"""地图位置搜索稳定契约和第三方无关的数据结构。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(slots=True)
class GeoSearchItem:
    """第三方地图返回并经过统一标准化的地点摘要。"""

    provider_poi_id: str
    name: str
    address: str
    province: str
    city: str
    district: str
    category_code: str
    category_name: str
    latitude: float
    longitude: float
    phone: str = ""


@dataclass(slots=True)
class GeoSearchResult:
    """第三方地图周边搜索的统一结果。"""

    items: list[GeoSearchItem]
    provider_total: int
    provider: str


class GeoSearchProvider(Protocol):
    """周边地点搜索适配协议，业务代码不得依赖具体地图厂商。"""

    def search_nearby(
        self,
        *,
        keyword: str,
        latitude: float,
        longitude: float,
        radius_m: int,
        limit: int,
    ) -> GeoSearchResult:
        """按关键词搜索指定坐标附近的地点。"""


class GeoProviderUnavailable(RuntimeError):
    """地图服务配置缺失、超时、限流或返回异常。"""
