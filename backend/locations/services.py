"""地点搜索、快捷关键词配置和公共场所过滤业务服务。"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import math
import re
import time
import unicodedata
import uuid
from datetime import timedelta
from typing import Any

from django.conf import settings
from django.core.cache import cache
from django.db import IntegrityError, transaction
from django.utils import timezone

from backend.accounts.models import User
from backend.common.crypto import decrypt_location_text, encrypt_location_text
from backend.common.errors import ERROR_MESSAGES, ErrorCode
from backend.common.exceptions import ApiError
from backend.integrations.geo.contracts import (
    GeoProviderUnavailable,
    GeoSearchItem,
    GeoSearchProvider,
)
from backend.integrations.geo.coordinates import gcj02_to_wgs84, wgs84_to_gcj02
from backend.integrations.geo.tencent import TencentGeoSearchProvider
from backend.locations.models import (
    LocationSearchKeyword,
    LocationSearchRule,
    ProviderLocationState,
)


def get_geo_provider() -> GeoSearchProvider:
    """创建腾讯地图适配器；密钥只从运行环境读取。"""

    return TencentGeoSearchProvider(key=settings.TENCENT_MAP_KEY)


def update_provider_location(
    *,
    user: User,
    latitude: float,
    longitude: float,
    coordinate_system: str,
    accuracy_m: int,
    source: str,
    privacy_version: str = "",
) -> dict[str, Any]:
    """为已开通服务者更新模糊化后的当前位置；普通用户不写入位置表。"""

    if not user.provider_enabled or user.provider_status != User.ProviderStatus.APPROVED:
        raise ApiError(
            ErrorCode.PROVIDER_NOT_ENABLED,
            ERROR_MESSAGES[ErrorCode.PROVIDER_NOT_ENABLED],
            status_code=403,
        )
    coordinate_system = str(coordinate_system).upper()
    if coordinate_system not in {"GCJ02", "WGS84"}:
        raise _invalid("coordinate_system", "坐标系只支持 GCJ02 或 WGS84")
    if not math.isfinite(latitude) or not -90 <= latitude <= 90:
        raise _invalid("latitude", "纬度必须在 -90 到 90 之间")
    if not math.isfinite(longitude) or not -180 <= longitude <= 180:
        raise _invalid("longitude", "经度必须在 -180 到 180 之间")
    if accuracy_m < 0 or accuracy_m > 10_000:
        raise _invalid("accuracy_m", "定位精度必须在 0 到 10000 米之间")
    source = str(source).strip().upper()
    if source not in {"LOGIN", "PERIODIC", "MANUAL"}:
        raise _invalid("source", "定位来源不支持")
    if len(str(privacy_version)) > 32:
        raise _invalid("privacy_version", "隐私授权版本不能超过 32 个字符")
    gcj_latitude, gcj_longitude = (
        wgs84_to_gcj02(latitude, longitude)
        if coordinate_system == "WGS84"
        else (latitude, longitude)
    )
    snapped_latitude = round(gcj_latitude, 3)
    snapped_longitude = round(gcj_longitude, 3)
    expires_at = timezone.now() + timedelta(seconds=settings.LOCATION_PROVIDER_TTL_SECONDS)
    with transaction.atomic():
        state = ProviderLocationState.objects.select_for_update().filter(user=user).first()
        if state is None:
            state = ProviderLocationState(user=user)
        state.latitude_encrypted = encrypt_location_text(f"{snapped_latitude:.3f}")
        state.longitude_encrypted = encrypt_location_text(f"{snapped_longitude:.3f}")
        state.coordinate_system = "GCJ02"
        state.accuracy_m = int(accuracy_m)
        state.source = source
        state.privacy_version = str(privacy_version)
        state.expires_at = expires_at
        state.revoked_at = None
        state.version += 1 if state.pk else 0
        state.save()
    return {
        "location_status": "ACTIVE",
        "location_freshness": "CURRENT",
        "expires_at": expires_at,
        "version": state.version,
    }


def get_provider_location_coordinates(user: User) -> tuple[float, float] | None:
    """读取服务者有效位置供内部距离计算；不向调用方暴露原始位置。"""

    state = getattr(user, "provider_location_state", None)
    if state is None or state.revoked_at is not None or state.expires_at <= timezone.now():
        return None
    return float(decrypt_location_text(state.latitude_encrypted)), float(
        decrypt_location_text(state.longitude_encrypted)
    )


def revoke_provider_location(*, user: User) -> dict[str, Any]:
    """撤销服务者当前位置共享，保留状态记录但不删除历史审计信息。"""

    with transaction.atomic():
        state = ProviderLocationState.objects.select_for_update().filter(user=user).first()
        if state is None:
            return {"location_status": "REVOKED", "version": 0}
        if state.revoked_at is None:
            state.revoked_at = timezone.now()
            state.version += 1
            state.save(update_fields=["revoked_at", "version", "updated_at"])
        return {
            "location_status": "REVOKED",
            "expires_at": state.expires_at,
            "version": state.version,
        }


def get_provider_location_status(*, user: User) -> dict[str, Any]:
    """返回服务者位置是否有效，不读取或返回经纬度。"""

    state = getattr(user, "provider_location_state", None)
    if state is None or state.revoked_at is not None:
        return {
            "location_status": "REVOKED" if state else "UNKNOWN",
            "location_freshness": "UNKNOWN",
            "expires_at": state.expires_at if state else None,
            "version": state.version if state else 0,
        }
    return {
        "location_status": "ACTIVE",
        "location_freshness": "CURRENT" if state.expires_at > timezone.now() else "UNKNOWN",
        "expires_at": state.expires_at,
        "version": state.version,
    }


def location_policy_version() -> str:
    """计算当前地点过滤规则版本，用于地点选择凭证过期判断。"""

    rules = list(
        LocationSearchRule.objects.filter(enabled=True)
        .order_by("priority", "id")
        .values_list("code", "decision", "match_scope", "match_value", "reason", "priority")
    )
    return hashlib.sha256(
        json.dumps(rules, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    ).hexdigest()[:32]


def build_location_selection_token(payload: dict[str, Any]) -> tuple[str, str]:
    """为已过滤的 POI 生成短期 HMAC 地点选择凭证。"""

    expires_at = timezone.now() + timedelta(seconds=settings.LOCATION_SELECTION_TTL_SECONDS)
    token_payload = {
        **payload,
        "policy_version": location_policy_version(),
        "exp": int(expires_at.timestamp()),
    }
    encoded = base64.urlsafe_b64encode(
        json.dumps(token_payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
            "utf-8"
        )
    ).decode("ascii")
    signature = hmac.new(
        settings.LOCATION_SELECTION_SIGNING_KEY.encode("utf-8"),
        encoded.encode("ascii"),
        hashlib.sha256,
    ).hexdigest()
    return f"{encoded}.{signature}", expires_at


def decode_location_selection_token(value: str) -> dict[str, Any]:
    """校验地点选择凭证签名、有效期和地点规则版本。"""

    try:
        encoded, signature = value.split(".", 1)
        expected = hmac.new(
            settings.LOCATION_SELECTION_SIGNING_KEY.encode("utf-8"),
            encoded.encode("ascii"),
            hashlib.sha256,
        ).hexdigest()
        if not hmac.compare_digest(signature, expected):
            raise ValueError("invalid signature")
        payload = json.loads(base64.urlsafe_b64decode(encoded.encode("ascii")).decode("utf-8"))
    except (ValueError, TypeError, binascii.Error, json.JSONDecodeError):
        raise ApiError(
            ErrorCode.LOCATION_SELECTION_INVALID,
            ERROR_MESSAGES[ErrorCode.LOCATION_SELECTION_INVALID],
            status_code=400,
        ) from None
    if int(payload.get("exp", 0)) <= int(time.time()):
        raise ApiError(
            ErrorCode.LOCATION_SELECTION_EXPIRED,
            ERROR_MESSAGES[ErrorCode.LOCATION_SELECTION_EXPIRED],
            status_code=400,
        )
    if payload.get("policy_version") != location_policy_version():
        raise ApiError(
            ErrorCode.LOCATION_SELECTION_EXPIRED,
            ERROR_MESSAGES[ErrorCode.LOCATION_SELECTION_EXPIRED],
            status_code=400,
            details={"reason": "地点规则已更新，请重新选择地点"},
        )
    return payload


def list_quick_keywords(*, include_disabled: bool = False) -> dict[str, Any]:
    """返回前端可用地点快捷搜索词，管理员可查看全部配置。"""

    queryset = LocationSearchKeyword.objects.all()
    if not include_disabled:
        queryset = queryset.filter(enabled=True)
    items = [_keyword_payload(item, include_admin_fields=include_disabled) for item in queryset]
    return {"items": items, "total": len(items)}


def create_quick_keyword(
    *,
    admin: User,
    payload: dict[str, Any],
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    """创建地点快捷关键词，并通过幂等键拒绝同键不同配置。"""

    normalized = _normalized_keyword(payload["query_keyword"])
    _ensure_request_keyword_allowed(normalized)
    code = _normalized_code(payload["code"])
    label = str(payload["label"]).strip()
    icon = str(payload.get("icon", "")).strip()
    sort_order = int(payload.get("sort_order", 0))
    if not label or len(label) > 50:
        raise _invalid("label", "展示名称长度必须在 1 到 50 之间")
    if len(icon) > 255:
        raise _invalid("icon", "图标标识不能超过 255 个字符")
    if sort_order < 0:
        raise _invalid("sort_order", "排序值不能小于 0")
    key = _validate_idempotency_key(idempotency_key) or f"auto:{uuid.uuid4()}"
    fingerprint = _fingerprint(
        {
            "code": code,
            "label": label,
            "query_keyword": normalized,
            "icon": icon,
            "sort_order": sort_order,
            "enabled": bool(payload.get("enabled", True)),
        }
    )
    try:
        with transaction.atomic():
            existing = (
                LocationSearchKeyword.objects.select_for_update()
                .filter(idempotency_key=key)
                .first()
            )
            if existing is not None:
                if existing.request_fingerprint != fingerprint:
                    raise _conflict("相同 Idempotency-Key 已用于不同快捷关键词配置")
                return {**_keyword_payload(existing, include_admin_fields=True), "reused": True}
            if LocationSearchKeyword.objects.filter(code=code).exists():
                raise _conflict("快捷关键词代码已存在")
            item = LocationSearchKeyword.objects.create(
                code=code,
                label=label,
                query_keyword=normalized,
                icon=icon,
                sort_order=sort_order,
                enabled=bool(payload.get("enabled", True)),
                idempotency_key=key,
                request_fingerprint=fingerprint,
                created_by_user_id=admin.id,
            )
    except IntegrityError as exc:
        raise _conflict("快捷关键词或幂等键已存在") from exc
    return {**_keyword_payload(item, include_admin_fields=True), "reused": False}


def update_quick_keyword(
    *,
    keyword_id: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    """按乐观锁版本更新快捷关键词，防止并发覆盖管理员配置。"""

    normalized = _normalized_keyword(payload["query_keyword"]) if "query_keyword" in payload else ""
    if normalized:
        _ensure_request_keyword_allowed(normalized)
    with transaction.atomic():
        item = (
            LocationSearchKeyword.objects.select_for_update().filter(public_id=keyword_id).first()
        )
        if item is None:
            raise _not_found()
        _ensure_version(item, payload["expected_version"])
        if normalized:
            item.query_keyword = normalized
        item.label = str(payload.get("label", item.label)).strip()
        item.icon = str(payload.get("icon", item.icon)).strip()
        item.sort_order = int(payload.get("sort_order", item.sort_order))
        item.enabled = bool(payload.get("enabled", item.enabled))
        if not item.label or len(item.label) > 50:
            raise _invalid("label", "展示名称长度必须在 1 到 50 之间")
        if len(item.icon) > 255:
            raise _invalid("icon", "图标标识不能超过 255 个字符")
        if item.sort_order < 0:
            raise _invalid("sort_order", "排序值不能小于 0")
        item.version += 1
        item.save()
    return {**_keyword_payload(item, include_admin_fields=True), "reused": False}


def deactivate_quick_keyword(*, keyword_id: str, expected_version: int) -> dict[str, Any]:
    """逻辑停用快捷关键词，保留配置历史并支持管理员重新启用。"""

    with transaction.atomic():
        item = (
            LocationSearchKeyword.objects.select_for_update().filter(public_id=keyword_id).first()
        )
        if item is None:
            raise _not_found()
        _ensure_version(item, expected_version)
        if not item.enabled:
            return {**_keyword_payload(item, include_admin_fields=True), "reused": True}
        item.enabled = False
        item.version += 1
        item.save(update_fields=["enabled", "version", "updated_at"])
    return {**_keyword_payload(item, include_admin_fields=True), "reused": False}


def search_locations(
    *,
    user: User,
    latitude: float,
    longitude: float,
    coordinate_system: str,
    keyword: str | None = None,
    quick_keyword_code: str | None = None,
    radius_m: int | None = None,
    limit: int | None = None,
    provider: GeoSearchProvider | None = None,
) -> dict[str, Any]:
    """搜索周边公共场所，执行两层过滤并返回统一计算的直线距离。"""

    if bool(keyword) == bool(quick_keyword_code):
        raise _invalid("keyword", "keyword 与 quick_keyword_code 必须且只能提供一个")
    if quick_keyword_code:
        quick_keyword = (
            LocationSearchKeyword.objects.filter(
                code=_normalized_code(quick_keyword_code), enabled=True
            )
            .order_by("sort_order", "id")
            .first()
        )
        if quick_keyword is None:
            raise ApiError(
                ErrorCode.LOCATION_QUICK_KEYWORD_NOT_FOUND,
                ERROR_MESSAGES[ErrorCode.LOCATION_QUICK_KEYWORD_NOT_FOUND],
                status_code=404,
            )
        effective_keyword = quick_keyword.query_keyword
        display_keyword = quick_keyword.label
    else:
        effective_keyword = _normalized_keyword(keyword or "")
        display_keyword = effective_keyword
        _ensure_request_keyword_allowed(effective_keyword)

    coordinate_system = coordinate_system.upper()
    if coordinate_system not in {"GCJ02", "WGS84"}:
        raise _invalid("coordinate_system", "坐标系只支持 GCJ02 或 WGS84")
    radius = int(radius_m or settings.LOCATION_SEARCH_RADIUS_DEFAULT_M)
    if radius < 100 or radius > settings.LOCATION_SEARCH_RADIUS_MAX_M:
        raise _invalid(
            "radius_m",
            f"搜索半径必须在 100 到 {settings.LOCATION_SEARCH_RADIUS_MAX_M} 米之间",
        )
    result_limit = int(limit or 10)
    if result_limit < 1 or result_limit > settings.LOCATION_SEARCH_LIMIT_MAX:
        raise _invalid(
            "limit",
            f"返回数量必须在 1 到 {settings.LOCATION_SEARCH_LIMIT_MAX} 之间",
        )
    if not math.isfinite(latitude) or not -90 <= latitude <= 90:
        raise _invalid("latitude", "纬度必须在 -90 到 90 之间")
    if not math.isfinite(longitude) or not -180 <= longitude <= 180:
        raise _invalid("longitude", "经度必须在 -180 到 180 之间")

    search_latitude, search_longitude = (
        wgs84_to_gcj02(latitude, longitude)
        if coordinate_system == "WGS84"
        else (latitude, longitude)
    )
    cache_key = _search_cache_key(
        keyword=effective_keyword,
        latitude=search_latitude,
        longitude=search_longitude,
        radius_m=radius,
        limit=result_limit,
    )
    if settings.LOCATION_SEARCH_CACHE_TTL_SECONDS > 0:
        cached = cache.get(cache_key)
        if cached is not None:
            return cached
    try:
        result = (provider or get_geo_provider()).search_nearby(
            keyword=effective_keyword,
            latitude=search_latitude,
            longitude=search_longitude,
            radius_m=radius,
            limit=result_limit,
        )
    except GeoProviderUnavailable as exc:
        raise ApiError(
            ErrorCode.LOCATION_PROVIDER_UNAVAILABLE,
            ERROR_MESSAGES[ErrorCode.LOCATION_PROVIDER_UNAVAILABLE],
            status_code=503,
        ) from exc

    allowed_items: list[dict[str, Any]] = []
    filtered_count = 0
    for item in result.items:
        rejection_reason = _poi_rejection_reason(item)
        if rejection_reason:
            filtered_count += 1
            continue
        distance_m = _distance_meters(
            search_latitude,
            search_longitude,
            item.latitude,
            item.longitude,
        )
        allowed_items.append(
            _location_payload(
                item,
                distance_m=distance_m,
                coordinate_system=coordinate_system,
            )
        )
    allowed_items.sort(key=lambda item: (item["distance_m"], item["provider_poi_id"]))
    payload = {
        "query_keyword": display_keyword,
        "quick_keyword_code": quick_keyword_code or "",
        "center": {"latitude": latitude, "longitude": longitude},
        "coordinate_system": coordinate_system,
        "radius_m": radius,
        "provider": result.provider,
        "provider_total": result.provider_total,
        "items": allowed_items[:result_limit],
        "filtered_count": filtered_count,
    }
    if settings.LOCATION_SEARCH_CACHE_TTL_SECONDS > 0:
        cache.set(cache_key, payload, settings.LOCATION_SEARCH_CACHE_TTL_SECONDS)
    return payload


def _normalized_keyword(value: str) -> str:
    """规范化搜索词，限制长度并拒绝空白关键词。"""

    normalized = re.sub(r"\s+", " ", unicodedata.normalize("NFKC", value).strip()).casefold()
    if not normalized:
        raise _invalid("keyword", "搜索关键词不能为空")
    if len(normalized) > settings.LOCATION_SEARCH_KEYWORD_MAX_LENGTH:
        raise _invalid(
            "keyword",
            f"搜索关键词不能超过 {settings.LOCATION_SEARCH_KEYWORD_MAX_LENGTH} 个字符",
        )
    return normalized


def _normalized_code(value: str) -> str:
    """规范化稳定代码，保证前后端配置引用一致。"""

    code = str(value).strip().upper()
    if not re.fullmatch(r"[A-Z][A-Z0-9_]{1,63}", code):
        raise _invalid("code", "代码必须是 2 到 64 位大写字母、数字或下划线")
    return code


def _ensure_request_keyword_allowed(keyword: str) -> None:
    """在请求第三方地图前拒绝酒店、住宅等明显不符合要求的搜索词。"""

    for rule in LocationSearchRule.objects.filter(
        enabled=True, decision=LocationSearchRule.Decision.DENY
    ).order_by("priority", "id"):
        if _normalize_rule_value(rule.match_value) in keyword:
            raise ApiError(
                ErrorCode.LOCATION_KEYWORD_NOT_ALLOWED,
                ERROR_MESSAGES[ErrorCode.LOCATION_KEYWORD_NOT_ALLOWED],
                status_code=422,
                details={"reason": rule.reason or "搜索词包含不允许的地点类型"},
            )


def _poi_rejection_reason(item: GeoSearchItem) -> str:
    """按拒绝规则和允许白名单判断第三方 POI 是否符合公共场所要求。"""

    text_by_scope = {
        LocationSearchRule.MatchScope.ANY: " ".join([item.name, item.category_name, item.address]),
        LocationSearchRule.MatchScope.NAME: item.name,
        LocationSearchRule.MatchScope.CATEGORY: item.category_name,
        LocationSearchRule.MatchScope.ADDRESS: item.address,
    }
    rules = list(LocationSearchRule.objects.filter(enabled=True).order_by("priority", "id"))
    for rule in rules:
        if rule.decision != LocationSearchRule.Decision.DENY:
            continue
        if _normalize_rule_value(rule.match_value) in _normalize_rule_value(
            text_by_scope[rule.match_scope]
        ):
            return rule.reason or "地点类型不符合公共场所要求"
    for rule in rules:
        if rule.decision != LocationSearchRule.Decision.ALLOW:
            continue
        if _normalize_rule_value(rule.match_value) in _normalize_rule_value(
            text_by_scope[rule.match_scope]
        ):
            return ""
    return "地点分类不在允许的公共场所范围内"


def _normalize_rule_value(value: str) -> str:
    """统一规则文本比较形式，忽略大小写和多余空白。"""

    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", value).strip()).casefold()


def _distance_meters(
    latitude_a: float,
    longitude_a: float,
    latitude_b: float,
    longitude_b: float,
) -> int:
    """使用 Haversine 公式计算两个 GCJ02 坐标间的球面直线距离。"""

    earth_radius_m = 6_371_008.8
    latitude_a_rad = math.radians(latitude_a)
    latitude_b_rad = math.radians(latitude_b)
    latitude_delta = latitude_b_rad - latitude_a_rad
    longitude_delta = math.radians(longitude_b - longitude_a)
    value = (
        math.sin(latitude_delta / 2) ** 2
        + math.cos(latitude_a_rad) * math.cos(latitude_b_rad) * math.sin(longitude_delta / 2) ** 2
    )
    return round(earth_radius_m * 2 * math.atan2(math.sqrt(value), math.sqrt(1 - value)))


def _distance_text(distance_m: int) -> str:
    """生成前端可直接展示的统一距离文案。"""

    return f"{distance_m}米" if distance_m < 1000 else f"{distance_m / 1000:.1f}公里"


def _location_payload(
    item: GeoSearchItem,
    *,
    distance_m: int,
    coordinate_system: str,
) -> dict[str, Any]:
    """构造不包含第三方密钥和内部请求信息的地点响应。"""

    latitude, longitude = (
        gcj02_to_wgs84(item.latitude, item.longitude)
        if coordinate_system == "WGS84"
        else (item.latitude, item.longitude)
    )
    payload = {
        "provider_poi_id": item.provider_poi_id,
        "name": item.name,
        "address": item.address,
        "province": item.province,
        "city": item.city,
        "district": item.district,
        "category_code": item.category_code,
        "category_name": item.category_name,
        "latitude": latitude,
        "longitude": longitude,
        "phone": item.phone,
        "distance_m": distance_m,
        "distance_text": _distance_text(distance_m),
    }
    selection_token, selection_expires_at = build_location_selection_token(
        {
            "provider_poi_id": item.provider_poi_id,
            "name": item.name,
            "address": item.address,
            "province": item.province,
            "city": item.city,
            "district": item.district,
            "category_code": item.category_code,
            "category_name": item.category_name,
            "latitude": latitude,
            "longitude": longitude,
            "coordinate_system": coordinate_system,
        }
    )
    payload.update(
        {
            "selection_token": selection_token,
            "selection_expires_at": selection_expires_at,
        }
    )
    return payload


def _keyword_payload(item: LocationSearchKeyword, *, include_admin_fields: bool) -> dict[str, Any]:
    """构造快捷关键词响应，管理端额外返回版本和启用状态。"""

    payload = {
        "keyword_id": str(item.public_id),
        "code": item.code,
        "label": item.label,
        "query_keyword": item.query_keyword,
        "icon": item.icon,
        "sort_order": item.sort_order,
    }
    if include_admin_fields:
        payload.update(
            {
                "enabled": item.enabled,
                "version": item.version,
                "created_at": item.created_at,
                "updated_at": item.updated_at,
            }
        )
    return payload


def _search_cache_key(
    *,
    keyword: str,
    latitude: float,
    longitude: float,
    radius_m: int,
    limit: int,
) -> str:
    """使用粗粒度坐标生成缓存键，避免保存用户精确位置。"""

    raw = json.dumps(
        {
            "keyword": keyword,
            "latitude": round(latitude, 3),
            "longitude": round(longitude, 3),
            "radius_m": radius_m,
            "limit": limit,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return f"location-search:{hashlib.sha256(raw.encode('utf-8')).hexdigest()}"


def _validate_idempotency_key(value: str | None) -> str | None:
    """校验管理员创建请求的幂等键长度。"""

    if value is None:
        return None
    key = value.strip()
    if not key or len(key) > 128:
        raise _conflict("Idempotency-Key 长度必须在 1 到 128 之间")
    return key


def _fingerprint(payload: dict[str, Any]) -> str:
    """计算请求参数摘要，不保存管理员或用户敏感数据。"""

    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _ensure_version(item: LocationSearchKeyword, expected_version: int) -> None:
    """校验快捷关键词乐观锁版本。"""

    if item.version != expected_version:
        raise ApiError(
            ErrorCode.LOCATION_QUICK_KEYWORD_VERSION_CONFLICT,
            ERROR_MESSAGES[ErrorCode.LOCATION_QUICK_KEYWORD_VERSION_CONFLICT],
            status_code=409,
            details={"current_version": item.version},
        )


def _invalid(field: str, message: str) -> ApiError:
    """构造地点搜索参数错误。"""

    return ApiError(
        ErrorCode.LOCATION_SEARCH_INVALID,
        ERROR_MESSAGES[ErrorCode.LOCATION_SEARCH_INVALID],
        status_code=400,
        details={field: message},
    )


def _conflict(message: str) -> ApiError:
    """构造快捷关键词配置冲突错误。"""

    return ApiError(
        ErrorCode.LOCATION_QUICK_KEYWORD_CONFLICT,
        ERROR_MESSAGES[ErrorCode.LOCATION_QUICK_KEYWORD_CONFLICT],
        status_code=409,
        details={"reason": message},
    )


def _not_found() -> ApiError:
    """构造快捷关键词不存在错误。"""

    return ApiError(
        ErrorCode.LOCATION_QUICK_KEYWORD_NOT_FOUND,
        ERROR_MESSAGES[ErrorCode.LOCATION_QUICK_KEYWORD_NOT_FOUND],
        status_code=404,
    )
