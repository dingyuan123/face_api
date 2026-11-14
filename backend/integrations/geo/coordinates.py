"""常用地图坐标系转换工具。"""

from __future__ import annotations

import math

_EARTH_SEMI_MAJOR_AXIS = 6378245.0
_ECCENTRICITY_SQUARED = 0.00669342162296594323


def _is_outside_china(latitude: float, longitude: float) -> bool:
    """判断坐标是否明显位于中国境外，境外坐标不做火星坐标偏移。"""

    return not (72.004 <= longitude <= 137.8347 and 0.8293 <= latitude <= 55.8271)


def _transform_latitude(longitude: float, latitude: float) -> float:
    """计算 WGS84 转 GCJ02 的纬度偏移量。"""

    value = (
        -100.0
        + 2.0 * longitude
        + 3.0 * latitude
        + 0.2 * latitude * latitude
        + 0.1 * longitude * latitude
        + 0.2 * math.sqrt(abs(longitude))
    )
    value += (
        (20.0 * math.sin(6.0 * longitude * math.pi) + 20.0 * math.sin(2.0 * longitude * math.pi))
        * 2.0
        / 3.0
    )
    value += (
        (20.0 * math.sin(latitude * math.pi) + 40.0 * math.sin(latitude / 3.0 * math.pi))
        * 2.0
        / 3.0
    )
    value += (
        (160.0 * math.sin(latitude / 12.0 * math.pi) + 320.0 * math.sin(latitude * math.pi / 30.0))
        * 2.0
        / 3.0
    )
    return value


def _transform_longitude(longitude: float, latitude: float) -> float:
    """计算 WGS84 转 GCJ02 的经度偏移量。"""

    value = (
        300.0
        + longitude
        + 2.0 * latitude
        + 0.1 * longitude * longitude
        + 0.1 * longitude * latitude
        + 0.1 * math.sqrt(abs(longitude))
    )
    value += (
        (20.0 * math.sin(6.0 * longitude * math.pi) + 20.0 * math.sin(2.0 * longitude * math.pi))
        * 2.0
        / 3.0
    )
    value += (
        (20.0 * math.sin(longitude * math.pi) + 40.0 * math.sin(longitude / 3.0 * math.pi))
        * 2.0
        / 3.0
    )
    value += (
        (
            150.0 * math.sin(longitude / 12.0 * math.pi)
            + 300.0 * math.sin(longitude / 30.0 * math.pi)
        )
        * 2.0
        / 3.0
    )
    return value


def wgs84_to_gcj02(latitude: float, longitude: float) -> tuple[float, float]:
    """将 WGS84 经纬度转换为腾讯地图使用的 GCJ02 坐标。"""

    if _is_outside_china(latitude, longitude):
        return latitude, longitude
    latitude_offset = _transform_latitude(longitude - 105.0, latitude - 35.0)
    longitude_offset = _transform_longitude(longitude - 105.0, latitude - 35.0)
    latitude_radians = latitude / 180.0 * math.pi
    magic = math.sin(latitude_radians)
    magic = 1 - _ECCENTRICITY_SQUARED * magic * magic
    sqrt_magic = math.sqrt(magic)
    latitude_offset = (latitude_offset * 180.0) / (
        (_EARTH_SEMI_MAJOR_AXIS * (1 - _ECCENTRICITY_SQUARED)) / (magic * sqrt_magic) * math.pi
    )
    longitude_offset = (longitude_offset * 180.0) / (
        _EARTH_SEMI_MAJOR_AXIS / sqrt_magic * math.cos(latitude_radians) * math.pi
    )
    return latitude + latitude_offset, longitude + longitude_offset


def gcj02_to_wgs84(latitude: float, longitude: float) -> tuple[float, float]:
    """将腾讯地图使用的 GCJ02 坐标近似转换回 WGS84 坐标。"""

    if _is_outside_china(latitude, longitude):
        return latitude, longitude
    converted_latitude = latitude
    converted_longitude = longitude
    for _ in range(3):
        reference_latitude, reference_longitude = wgs84_to_gcj02(
            converted_latitude,
            converted_longitude,
        )
        converted_latitude -= reference_latitude - latitude
        converted_longitude -= reference_longitude - longitude
    return converted_latitude, converted_longitude
