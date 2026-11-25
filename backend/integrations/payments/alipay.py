"""支付宝 App 下单、原路退款和异步通知 RSA2 验签适配器。"""

from __future__ import annotations

import base64
import json
import logging
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from typing import Any

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric.padding import PKCS1v15
from django.conf import settings

from backend.integrations.payments.contracts import (
    PaymentGateway,
    PaymentGatewayError,
    PaymentGatewayUnavailable,
    PaymentInitiation,
    PaymentNotification,
    RefundResult,
)
from backend.integrations.payments.crypto import (
    amount_to_yuan,
    load_private_key,
    load_public_key,
    yuan_to_minor,
)

logger = logging.getLogger("jianmianliao.payment.alipay")


def _decode_response_text(raw: bytes, charset: str | None) -> str:
    """按支付宝响应编码解码，兼容错误页返回 GBK 的情况。"""
    try:
        return raw.decode(charset or "utf-8")
    except (LookupError, UnicodeDecodeError):
        return raw.decode("gb18030", errors="replace")


def _safe_request_summary(biz_content: dict[str, Any]) -> dict[str, Any]:
    """返回可记录的支付宝请求摘要，不输出签名、密钥或完整订单串。"""
    fields = (
        "out_trade_no",
        "out_request_no",
        "refund_no",
        "total_amount",
        "refund_amount",
        "product_code",
    )
    return {field: biz_content[field] for field in fields if field in biz_content}


def _safe_response_summary(value: Any) -> dict[str, Any]:
    """返回支付宝响应的错误码和交易摘要，不输出签名或个人敏感字段。"""
    if not isinstance(value, dict):
        return {"response_type": type(value).__name__}
    fields = (
        "code",
        "msg",
        "sub_code",
        "sub_msg",
        "trace_id",
        "trade_status",
        "out_trade_no",
        "out_request_no",
        "refund_no",
        "trade_no",
        "total_amount",
        "refund_amount",
    )
    return {field: value[field] for field in fields if field in value}


class AlipayGateway(PaymentGateway):
    """接入支付宝开放平台 App 支付，签名密钥不进入响应和日志。"""

    def create_app_payment(
        self,
        *,
        payment_no: str,
        description: str,
        amount_minor: int,
    ) -> PaymentInitiation:
        """生成支付宝 App SDK 所需的已签名 order string。"""
        biz_content = {
            "out_trade_no": payment_no,
            "total_amount": amount_to_yuan(amount_minor),
            "subject": description[:240],
            "product_code": "QUICK_MSECURITY_PAY",
        }
        params = self._common_params("alipay.trade.app.pay", biz_content)
        params["notify_url"] = settings.ALIPAY_NOTIFY_URL
        params["sign"] = self._sign(params)
        order_string = urllib.parse.urlencode(params)
        logger.info(
            "支付宝 App 支付参数已生成",
            extra={
                "payment_provider": "ALIPAY",
                "api_method": "alipay.trade.app.pay",
                "payment_no": payment_no,
                "amount_minor": amount_minor,
                "sign_type": params["sign_type"],
            },
        )
        return PaymentInitiation(
            channel_reference=f"alipay-{payment_no}",
            client_payload={"order_string": order_string},
        )

    def refund(
        self,
        *,
        payment_no: str,
        refund_no: str,
        amount_minor: int,
    ) -> RefundResult:
        """调用支付宝交易退款接口，按接口结果区分成功、处理中和失败。"""
        result = self._request(
            "alipay.trade.refund",
            {
                "out_trade_no": payment_no,
                "refund_no": refund_no,
                "refund_amount": amount_to_yuan(amount_minor),
                "refund_reason": "见面聊订单退款",
            },
        )
        response = result.get("alipay_trade_refund_response", result)
        logger.info(
            "支付宝退款接口处理完成",
            extra={
                "payment_provider": "ALIPAY",
                "api_method": "alipay.trade.refund",
                "payment_no": payment_no,
                "refund_no": refund_no,
                "alipay_response": _safe_response_summary(response),
            },
        )
        if response.get("code") == "10000":
            status = "SUCCESS"
            channel_status = "REFUND_SUCCESS"
            failure_reason = ""
        elif response.get("code") in {"10003", "20000"}:
            status = "PENDING"
            channel_status = "REFUND_PROCESSING"
            failure_reason = ""
        else:
            status = "FAILED"
            channel_status = "REFUND_FAILED"
            failure_reason = str(response.get("sub_msg") or "支付宝退款失败")
        return RefundResult(
            channel_refund_no=str(response.get("trade_no", "")),
            status=status,
            channel_status=channel_status,
            failure_reason=failure_reason,
        )

    def verify_notification(
        self,
        *,
        raw_body: bytes,
        headers: dict[str, str],
        form_data: dict[str, Any],
    ) -> PaymentNotification:
        """验证支付宝异步通知 RSA2 签名并核对支付成功状态。"""
        del raw_body, headers
        payload = {
            key: str(value) for key, value in form_data.items() if key not in {"sign", "sign_type"}
        }
        signature = str(form_data.get("sign", ""))
        if not signature or not self._verify(payload, signature):
            raise PaymentGatewayError("支付宝回调签名验证失败")
        refund_no = str(form_data.get("out_refund_no", ""))
        if form_data.get("app_id") and form_data.get("app_id") != settings.ALIPAY_APP_ID:
            raise PaymentGatewayError("支付宝回调 AppID 不匹配")
        channel_status = str(form_data.get("trade_status", ""))
        success = (
            channel_status in {"REFUND_SUCCESS", "SUCCESS"}
            if refund_no
            else channel_status == "TRADE_SUCCESS"
        )
        notification = PaymentNotification(
            event_type="REFUND.NOTIFY" if refund_no else "TRADE.NOTIFY",
            out_trade_no=str(form_data.get("out_trade_no", "")),
            transaction_no=str(form_data.get("trade_no", "")),
            amount_minor=yuan_to_minor(
                form_data.get("refund_amount") if refund_no else form_data.get("total_amount")
            ),
            success=success,
            channel_status=channel_status,
            refund_no=refund_no,
        )
        logger.info(
            "支付宝异步通知验证完成",
            extra={
                "payment_provider": "ALIPAY",
                "event_type": notification.event_type,
                "out_trade_no": notification.out_trade_no,
                "transaction_no": notification.transaction_no,
                "refund_no": notification.refund_no,
                "channel_status": notification.channel_status,
                "notification_success": notification.success,
            },
        )
        return notification

    def _request(self, method: str, biz_content: dict[str, Any]) -> dict[str, Any]:
        """调用支付宝网关并验证业务响应签名，不打印商户密钥。"""
        self._validate_config()
        params = self._common_params(method, biz_content)
        params["sign"] = self._sign(params)
        logger.info(
            "支付宝接口开始请求",
            extra={
                "payment_provider": "ALIPAY",
                "api_method": method,
                "alipay_request": _safe_request_summary(biz_content),
            },
        )
        request = urllib.request.Request(
            settings.ALIPAY_GATEWAY_URL,
            data=urllib.parse.urlencode(params).encode(),
            method="POST",
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "User-Agent": "jianmianliao-backend/1.0",
            },
        )
        try:
            with urllib.request.urlopen(
                request,
                timeout=settings.ALIPAY_TIMEOUT_SECONDS,
            ) as response:
                raw_response = response.read()
                response_text = _decode_response_text(
                    raw_response,
                    response.headers.get_content_charset(),
                )
                result = json.loads(response_text)
        except urllib.error.HTTPError as exc:
            detail = _decode_response_text(
                exc.read(),
                exc.headers.get_content_charset(),
            )[:500]
            logger.warning(
                "支付宝接口返回 HTTP 错误",
                extra={
                    "payment_provider": "ALIPAY",
                    "api_method": method,
                    "alipay_http_status": exc.code,
                    "alipay_response": detail,
                },
            )
            raise PaymentGatewayError("支付宝请求被拒绝") from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            logger.warning(
                "支付宝接口网络不可用",
                extra={
                    "payment_provider": "ALIPAY",
                    "api_method": method,
                    "error_type": type(exc).__name__,
                },
            )
            raise PaymentGatewayUnavailable("支付宝网络服务不可用") from exc
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            logger.warning(
                "支付宝接口响应格式不正确",
                extra={
                    "payment_provider": "ALIPAY",
                    "api_method": method,
                    "error_type": type(exc).__name__,
                },
            )
            raise PaymentGatewayError("支付宝响应格式不正确") from exc
        response_data = result.get(f"{method.replace('.', '_')}_response")
        logger.info(
            "支付宝接口返回响应",
            extra={
                "payment_provider": "ALIPAY",
                "api_method": method,
                "alipay_response": _safe_response_summary(
                    response_data if isinstance(response_data, dict) else result
                ),
            },
        )
        if isinstance(response_data, dict) and response_data.get("code") != "10000":
            logger.warning(
                "支付宝接口返回业务错误",
                extra={
                    "payment_provider": "ALIPAY",
                    "api_method": method,
                    "alipay_response": _safe_response_summary(response_data),
                },
            )
            raise PaymentGatewayError(
                str(response_data.get("sub_msg") or response_data.get("msg") or "支付宝业务失败")
            )
        response_params = {
            key: value
            for key, value in result.items()
            if key not in {"sign", "sign_type"} and isinstance(value, str)
        }
        if response_data is not None and result.get("sign"):
            serialized = json.dumps(
                response_data,
                ensure_ascii=False,
                separators=(",", ":"),
            )
            if not self._verify_text(serialized, str(result["sign"])):
                logger.warning(
                    "支付宝接口响应验签失败",
                    extra={
                        "payment_provider": "ALIPAY",
                        "api_method": method,
                        "alipay_response": _safe_response_summary(response_data),
                    },
                )
                raise PaymentGatewayError("支付宝响应签名验证失败")
        del response_params
        return result

    def _common_params(
        self,
        method: str,
        biz_content: dict[str, Any],
    ) -> dict[str, str]:
        """生成支付宝公共请求参数，时间统一由服务端产生。"""
        return {
            "app_id": settings.ALIPAY_APP_ID,
            "method": method,
            "format": "JSON",
            "charset": "utf-8",
            "sign_type": "RSA2",
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "version": "1.0",
            "biz_content": json.dumps(
                biz_content,
                ensure_ascii=False,
                separators=(",", ":"),
            ),
            "notify_url": settings.ALIPAY_NOTIFY_URL,
        }

    def _sign(self, params: dict[str, str]) -> str:
        """对排序后的业务参数执行 RSA2 签名。"""
        content = "&".join(
            f"{key}={value}"
            for key, value in sorted(params.items())
            if key != "sign" and value not in {"", None}
        )
        return self._sign_text(content)

    def _verify(self, params: dict[str, str], signature: str) -> bool:
        """验证支付宝表单通知的排序参数签名。"""
        content = "&".join(
            f"{key}={value}" for key, value in sorted(params.items()) if value not in {"", None}
        )
        return self._verify_text(content, signature)

    def _sign_text(self, content: str) -> str:
        private_key = self._private_key()
        signature = private_key.sign(
            content.encode("utf-8"),
            PKCS1v15(),
            hashes.SHA256(),
        )
        return base64.b64encode(signature).decode()

    def _verify_text(self, content: str, signature: str) -> bool:
        try:
            load_public_key(settings.ALIPAY_PUBLIC_KEY).verify(
                base64.b64decode(signature),
                content.encode("utf-8"),
                PKCS1v15(),
                hashes.SHA256(),
            )
            return True
        except Exception:
            return False

    def _private_key(self) -> Any:
        try:
            return load_private_key(settings.ALIPAY_PRIVATE_KEY)
        except PaymentGatewayUnavailable as exc:
            raise PaymentGatewayUnavailable("支付宝商户私钥配置无效") from exc

    def _validate_config(self) -> None:
        required = [
            settings.ALIPAY_APP_ID,
            settings.ALIPAY_PRIVATE_KEY,
            settings.ALIPAY_PUBLIC_KEY,
            settings.ALIPAY_NOTIFY_URL,
        ]
        if not all(required):
            raise PaymentGatewayUnavailable("支付宝配置不完整")
