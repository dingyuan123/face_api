"""微信支付 App 下单、原路退款和支付回调验签适配器。"""

from __future__ import annotations

import base64
import json
import logging
import secrets
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path
from typing import Any

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric.padding import PKCS1v15
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from django.conf import settings

from backend.integrations.payments.contracts import (
    PaymentGateway,
    PaymentGatewayError,
    PaymentGatewayUnavailable,
    PaymentInitiation,
    PaymentNotification,
    RefundResult,
)
from backend.integrations.payments.crypto import load_public_key

logger = logging.getLogger("jianmianliao.payment.wechat")


class WeChatPayGateway(PaymentGateway):
    """接入微信支付 APIv3，密钥仅从环境配置加载且不写入日志。"""

    def create_app_payment(
        self,
        *,
        payment_no: str,
        description: str,
        amount_minor: int,
    ) -> PaymentInitiation:
        """创建 App 预支付订单并生成微信 SDK 调起参数。"""
        payload = {
            "appid": settings.WECHAT_PAY_APP_ID,
            "mchid": settings.WECHAT_PAY_MCH_ID,
            "description": description[:127],
            "out_trade_no": _wechat_reference(payment_no),
            "notify_url": settings.WECHAT_PAY_NOTIFY_URL,
            "amount": {"total": amount_minor, "currency": settings.PAYMENT_CURRENCY},
        }
        response = self._request("POST", "/v3/pay/transactions/app", payload)
        prepay_id = str(response.get("prepay_id", ""))
        if not prepay_id:
            raise PaymentGatewayUnavailable("微信支付未返回预支付标识")
        timestamp = str(int(time.time()))
        nonce = secrets.token_hex(16)
        package = "Sign=WXPay"
        message = "\n".join([settings.WECHAT_PAY_APP_ID, prepay_id, package, nonce, timestamp])
        return PaymentInitiation(
            channel_reference=prepay_id,
            client_payload={
                "appid": settings.WECHAT_PAY_APP_ID,
                "partnerid": settings.WECHAT_PAY_MCH_ID,
                "prepayid": prepay_id,
                "package": package,
                "noncestr": nonce,
                "timestamp": timestamp,
                "sign": self._sign(message.encode("utf-8")),
            },
        )

    def refund(
        self,
        *,
        payment_no: str,
        refund_no: str,
        amount_minor: int,
    ) -> RefundResult:
        """申请微信原支付单退款，成功与处理中状态分别返回。"""
        response = self._request(
            "POST",
            "/v3/refund/domestic/refunds",
            {
                "out_trade_no": _wechat_reference(payment_no),
                "out_refund_no": _wechat_reference(refund_no),
                "reason": "见面聊订单退款",
                "amount": {
                    "refund": amount_minor,
                    "total": amount_minor,
                    "currency": settings.PAYMENT_CURRENCY,
                },
            },
        )
        channel_status = str(response.get("status", ""))
        if channel_status == "SUCCESS":
            status = "SUCCESS"
        elif channel_status in {"PROCESSING", "ABNORMAL"}:
            status = "PENDING"
        else:
            status = "FAILED"
        return RefundResult(
            channel_refund_no=str(response.get("refund_id", "")),
            status=status,
            channel_status=channel_status,
            failure_reason="" if status != "FAILED" else "微信支付退款未成功",
        )

    def verify_notification(
        self,
        *,
        raw_body: bytes,
        headers: dict[str, str],
        form_data: dict[str, Any],
    ) -> PaymentNotification:
        """验证 APIv3 平台签名并解密支付或退款通知资源。"""
        del form_data
        normalized = {key.lower(): value for key, value in headers.items()}
        signature = normalized.get("wechatpay-signature", "")
        nonce = normalized.get("wechatpay-nonce", "")
        timestamp = normalized.get("wechatpay-timestamp", "")
        serial = normalized.get("wechatpay-serial", "")
        if not all([signature, nonce, timestamp, serial]):
            raise PaymentGatewayError("微信支付回调验签参数缺失")
        if serial != settings.WECHAT_PAY_PLATFORM_PUBLIC_KEY_ID:
            raise PaymentGatewayError("微信支付回调平台证书序列号不匹配")
        try:
            sign_timestamp = int(timestamp)
            decoded_signature = base64.b64decode(signature)
        except (ValueError, TypeError) as exc:
            raise PaymentGatewayError("微信支付回调验签参数格式无效") from exc
        if abs(time.time() - sign_timestamp) > 300:
            raise PaymentGatewayError("微信支付回调时间戳超出允许范围")
        signed_message = f"{timestamp}\n{nonce}\n{raw_body.decode('utf-8')}\n".encode()
        if not self._verify(signed_message, decoded_signature):
            raise PaymentGatewayError("微信支付回调签名验证失败")
        envelope = json.loads(raw_body.decode("utf-8"))
        resource = envelope.get("resource", {})
        if resource.get("algorithm") != "AEAD_AES_256_GCM":
            raise PaymentGatewayError("微信支付回调加密方式不支持")
        data = json.loads(self._decrypt_resource(resource).decode("utf-8"))
        if data.get("appid") and data.get("appid") != settings.WECHAT_PAY_APP_ID:
            raise PaymentGatewayError("微信支付回调 AppID 不匹配")
        if data.get("mchid") and data.get("mchid") != settings.WECHAT_PAY_MCH_ID:
            raise PaymentGatewayError("微信支付回调商户号不匹配")
        event_type = str(envelope.get("event_type", ""))
        refund_no = str(data.get("out_refund_no", ""))
        success = (
            data.get("trade_state") == "SUCCESS"
            if event_type == "TRANSACTION.SUCCESS"
            else data.get("refund_status") == "SUCCESS"
        )
        amount_data = data.get("amount", {})
        amount_value = amount_data.get("refund") if refund_no else amount_data.get("total")
        return PaymentNotification(
            event_type=event_type,
            out_trade_no=str(data.get("out_trade_no", "")),
            transaction_no=str(
                data.get("refund_id") if refund_no else data.get("transaction_id", "")
            ),
            amount_minor=int(amount_value or 0),
            success=bool(success),
            channel_status=str(data.get("refund_status") or data.get("trade_state") or ""),
            refund_no=refund_no,
        )

    def _request(
        self,
        method: str,
        path: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        """发送微信 APIv3 请求并检查 HTTP 与业务错误，不记录请求密钥。"""
        self._validate_config()
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()
        timestamp = str(int(time.time()))
        nonce = secrets.token_hex(16)
        message = f"{method}\n{path}\n{timestamp}\n{nonce}\n{body.decode()}\n".encode()
        authorization = (
            "WECHATPAY2-SHA256-RSA2048 "
            f'mchid="{settings.WECHAT_PAY_MCH_ID}",nonce_str="{nonce}",'
            f'signature="{self._sign(message)}",timestamp="{timestamp}",'
            f'serial_no="{settings.WECHAT_PAY_MERCHANT_SERIAL_NO}"'
        )
        request = urllib.request.Request(
            f"{settings.WECHAT_PAY_API_BASE_URL}{path}",
            data=body,
            method=method,
            headers={
                "Authorization": authorization,
                "Accept": "application/json",
                "Content-Type": "application/json",
                "User-Agent": "jianmianliao-backend/1.0",
            },
        )
        try:
            with urllib.request.urlopen(
                request,
                timeout=settings.WECHAT_PAY_TIMEOUT_SECONDS,
            ) as response:
                result = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:500]
            logger.warning(
                "微信支付接口返回错误",
                extra={
                    "payment_provider": "WECHAT_PAY",
                    "http_method": method,
                    "api_path": path,
                    "wechat_http_status": exc.code,
                    "wechat_response": detail,
                },
            )
            raise PaymentGatewayError(f"微信支付请求被拒绝: {detail}") from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise PaymentGatewayUnavailable("微信支付网络服务不可用") from exc
        if "code" in result:
            detail = {
                "code": result.get("code"),
                "message": result.get("message"),
                "detail": result.get("detail"),
            }
            logger.warning(
                "微信支付接口返回业务错误",
                extra={
                    "payment_provider": "WECHAT_PAY",
                    "http_method": method,
                    "api_path": path,
                    "wechat_response": detail,
                },
            )
            raise PaymentGatewayError(str(result.get("message") or "微信支付业务失败"))
        return result

    def _validate_config(self) -> None:
        """启动真实请求前校验配置完整性，但不输出任何配置值。"""
        required = [
            settings.WECHAT_PAY_MCH_ID,
            settings.WECHAT_PAY_APP_ID,
            settings.WECHAT_PAY_API_V3_KEY,
            settings.WECHAT_PAY_MERCHANT_SERIAL_NO,
            settings.WECHAT_PAY_PRIVATE_KEY,
            settings.WECHAT_PAY_PLATFORM_PUBLIC_KEY,
            settings.WECHAT_PAY_PLATFORM_PUBLIC_KEY_ID,
            settings.WECHAT_PAY_NOTIFY_URL,
        ]
        if not all(required):
            raise PaymentGatewayUnavailable("微信支付配置不完整")

    def _sign(self, message: bytes) -> str:
        """使用微信支付商户 API 私钥生成 RSA-SHA256 签名。"""
        private_key = self._private_key()
        return base64.b64encode(private_key.sign(message, PKCS1v15(), hashes.SHA256())).decode()

    def _verify(self, message: bytes, signature: bytes) -> bool:
        """使用配置的微信支付平台公钥验证回调签名。"""
        try:
            load_public_key(settings.WECHAT_PAY_PLATFORM_PUBLIC_KEY).verify(
                signature,
                message,
                PKCS1v15(),
                hashes.SHA256(),
            )
            return True
        except Exception:
            return False

    def _private_key(self) -> Any:
        """加载商户 API 私钥，错误统一转为渠道配置不可用。"""
        try:
            return serialization.load_pem_private_key(
                _key_material(settings.WECHAT_PAY_PRIVATE_KEY),
                password=None,
            )
        except (ValueError, TypeError) as exc:
            raise PaymentGatewayUnavailable("微信支付商户私钥配置无效") from exc

    def _decrypt_resource(self, resource: dict[str, Any]) -> bytes:
        """使用 APIv3 密钥解密回调资源，密文与认证标签不进入日志。"""
        try:
            nonce = resource["nonce"].encode()
            ciphertext = base64.b64decode(resource["ciphertext"])
            if len(ciphertext) < 16:
                raise ValueError
            associated_data = str(resource.get("associated_data", "")).encode()
            return AESGCM(settings.WECHAT_PAY_API_V3_KEY.encode()).decrypt(
                nonce,
                ciphertext,
                associated_data,
            )
        except (KeyError, ValueError, TypeError) as exc:
            raise PaymentGatewayError("微信支付通知解密失败") from exc


def _key_material(value: str) -> bytes:
    """兼容 PEM 文件路径与环境变量中的转义 PEM 内容。"""
    normalized = value.strip()
    candidate = Path(normalized)
    if candidate.is_file():
        return candidate.read_bytes()
    return normalized.replace("\\n", "\n").encode()


def _wechat_reference(value: str) -> str:
    """将内部 UUID 转为微信要求的 32 位商户订单号或退款单号。"""
    try:
        return uuid.UUID(value).hex
    except ValueError as exc:
        raise PaymentGatewayError("微信支付内部单号格式不正确") from exc
