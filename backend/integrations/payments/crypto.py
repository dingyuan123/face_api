"""支付适配器使用的 RSA 密钥和金额转换公共能力。"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.types import (
    PrivateKeyTypes,
    PublicKeyTypes,
)

from backend.integrations.payments.contracts import PaymentGatewayUnavailable


def load_private_key(value: str) -> PrivateKeyTypes:
    """从本地密钥文件路径或 PEM 环境变量加载商户私钥，不记录密钥内容。"""
    raw = _read_key_material(value)
    try:
        key = serialization.load_pem_private_key(raw, password=None)
    except (ValueError, TypeError) as exc:
        raise PaymentGatewayUnavailable("支付商户私钥配置无效") from exc
    return key


def load_public_key(value: str) -> PublicKeyTypes:
    """从本地证书/公钥文件路径或 PEM 环境变量加载支付平台公钥。"""
    raw = _read_key_material(value)
    try:
        return serialization.load_pem_public_key(raw)
    except (ValueError, TypeError) as exc:
        raise PaymentGatewayUnavailable("支付平台公钥配置无效") from exc


def amount_to_yuan(amount_minor: int) -> str:
    """将最小货币单位转换为支付宝所需两位小数字符串，全程不使用 Float。"""
    if amount_minor <= 0:
        raise ValueError("amount_minor must be positive")
    return f"{Decimal(amount_minor) / Decimal(100):.2f}"


def yuan_to_minor(value: object) -> int:
    """将支付宝两位小数金额转换为最小货币单位，拒绝无效精度。"""
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise PaymentGatewayUnavailable("支付回调金额格式无效") from exc
    if amount <= 0 or amount != amount.quantize(Decimal("0.01")):
        raise PaymentGatewayUnavailable("支付回调金额格式无效")
    return int(amount * 100)


def _read_key_material(value: str) -> bytes:
    normalized = value.strip()
    if not normalized:
        raise PaymentGatewayUnavailable("支付密钥未配置")
    candidate = Path(normalized)
    if candidate.is_file():
        return candidate.read_bytes()
    return normalized.replace("\\n", "\n").encode()
