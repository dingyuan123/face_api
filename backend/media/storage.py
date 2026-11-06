"""媒体文件本地存储适配边界，后续可替换为 OSS/COS。"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from django.core.files.base import ContentFile
from django.core.files.storage import default_storage


def build_storage_key(*, purpose: str, extension: str) -> str:
    """按日期、用途和随机标识生成不暴露原文件名的存储键。"""
    now = datetime.now(UTC)
    return f"media/{purpose.lower()}/{now:%Y/%m}/{uuid4().hex}.{extension.lstrip('.')}"


def save_bytes(storage_key: str, data: bytes) -> str:
    """保存规范化媒体字节并返回最终存储键。"""
    return default_storage.save(storage_key, ContentFile(data))


def open_bytes(storage_key: str):
    """以二进制只读方式打开已保存媒体。"""
    return default_storage.open(storage_key, mode="rb")


def delete(storage_key: str) -> None:
    """删除本地或对象存储中的媒体对象。"""
    if default_storage.exists(storage_key):
        default_storage.delete(storage_key)
