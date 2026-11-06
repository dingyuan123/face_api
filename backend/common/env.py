from __future__ import annotations

import os
from collections.abc import Iterable
from typing import TypeVar

from django.core.exceptions import ImproperlyConfigured
from dotenv import load_dotenv

T = TypeVar("T")


def load_environment(env_file: str | os.PathLike[str]) -> None:
    load_dotenv(env_file, override=False)


def get_text(name: str, default: str | None = None) -> str | None:
    value = os.getenv(name)
    if value is None or not value.strip():
        return default
    return value.strip()


def get_bool(name: str, default: bool = False) -> bool:
    value = get_text(name)
    if value is None:
        return default
    normalized = value.lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ImproperlyConfigured(f"环境变量 {name} 必须是布尔值, 当前值无法解析。")


def get_int(name: str, default: int) -> int:
    value = get_text(name)
    if value is None:
        return default
    try:
        return int(value)
    except ValueError as exc:
        raise ImproperlyConfigured(f"环境变量 {name} 必须是整数。") from exc


def get_list(name: str, default: Iterable[str] = ()) -> list[str]:
    value = get_text(name)
    if value is None:
        return list(default)
    return [item.strip() for item in value.split(",") if item.strip()]


def missing_envs(names: Iterable[str]) -> list[str]:
    return [name for name in names if not get_text(name)]


def require_envs(names: Iterable[str]) -> None:
    missing = missing_envs(names)
    if not missing:
        return
    joined = "、".join(missing)
    raise ImproperlyConfigured(
        f"生产配置缺少必需环境变量: {joined}. 请通过环境变量或密钥服务注入, 禁止使用默认密钥。"
    )
