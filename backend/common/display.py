"""模型枚举和业务展示文本的统一安全转换工具。"""

from __future__ import annotations

from typing import Any


def enum_label(enum_class: Any, value: Any, default: str = "") -> str:
    """返回 Django TextChoices 枚举值对应的中文展示文本。"""
    if value is None:
        return default
    try:
        return str(enum_class(value).label)
    except (TypeError, ValueError):
        return default or str(value)
