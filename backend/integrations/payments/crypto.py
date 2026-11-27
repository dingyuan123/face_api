"""支付适配器使用的 RSA 密钥和金额转换公共能力。"""

from __future__ import annotations

import base64
from decimal import Decimal, InvalidOperation
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.types import (
    PrivateKeyTypes,
    PublicKeyTypes,
)

from backend.integrations.payments.contracts import PaymentGatewayUnavailable


def load_private_key(value: str) -> PrivateKeyTypes:
    """从文件、PEM 或 Base64 DER 环境变量加载商户私钥。"""
    raw = _read_key_material(value)
    try:
        key = _load_private_key_bytes(raw)
    except (ValueError, TypeError) as exc:
        raise PaymentGatewayUnavailable("支付商户私钥配置无效") from exc
    return key


def load_public_key(value: str) -> PublicKeyTypes:
    """从文件、PEM 或 Base64 DER 环境变量加载支付平台公钥。"""
    raw = _read_key_material(value)
    try:
        return _load_public_key_bytes(raw)
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
    """读取文件内容或规范化环境变量中的 PEM/Base64 DER 密钥。"""
    normalized = value.strip()
    if not normalized:
        raise PaymentGatewayUnavailable("支付密钥未配置")
    candidate = Path(normalized)
    try:
        is_file = candidate.is_file()
    except OSError:
        is_file = False
    if is_file:
        return candidate.read_bytes()
    pem_value = normalized.replace("\\n", "\n")
    if pem_value.startswith("-----BEGIN "):
        return pem_value.encode()
    compact = "".join(pem_value.split())
    try:
        return base64.b64decode(compact, validate=True)
    except (ValueError, TypeError):
        return pem_value.encode()


def _load_private_key_bytes(raw: bytes) -> PrivateKeyTypes:
    """兼容 PEM 和 DER 编码的商户私钥。"""
    try:
        return serialization.load_pem_private_key(raw, password=None)
    except (ValueError, TypeError):
        return serialization.load_der_private_key(raw, password=None)


def _load_public_key_bytes(raw: bytes) -> PublicKeyTypes:
    """兼容 PEM 和 DER 编码的支付平台公钥。"""
    try:
        return serialization.load_pem_public_key(raw)
    except (ValueError, TypeError):
        return serialization.load_der_public_key(raw)
