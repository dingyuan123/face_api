"""微信支付适配器安全日志和错误处理测试。"""

from __future__ import annotations

import io
import json
import logging
import re
import uuid
from urllib.error import HTTPError

import pytest
from django.test import override_settings

from backend.integrations.payments.contracts import PaymentGatewayError
from backend.integrations.payments.wechat import WeChatPayGateway


@override_settings(
    WECHAT_PAY_MCH_ID="merchant-id",
    WECHAT_PAY_MERCHANT_SERIAL_NO="merchant-serial",
)
def test_wechat_authorization_uses_required_quoted_parameter_format(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """微信 APIv3 Authorization 参数必须加双引号，否则商户验签失败。"""
    captured_request = {}

    class FakeResponse:
        def __enter__(self) -> FakeResponse:
            return self

        def __exit__(self, *args: object) -> None:
            del args

        def read(self) -> bytes:
            return b'{"prepay_id":"wechat-prepay-1"}'

    def fake_urlopen(request: object, timeout: int) -> FakeResponse:
        del timeout
        captured_request["request"] = request
        return FakeResponse()

    monkeypatch.setattr(
        "backend.integrations.payments.wechat.urllib.request.urlopen",
        fake_urlopen,
    )
    monkeypatch.setattr(WeChatPayGateway, "_validate_config", lambda self: None)
    monkeypatch.setattr(WeChatPayGateway, "_sign", lambda self, message: "test-signature")

    WeChatPayGateway()._request("POST", "/v3/pay/transactions/app", {"total": 1})

    request = captured_request["request"]
    authorization = request.headers["Authorization"]
    assert re.fullmatch(
        r"WECHATPAY2-SHA256-RSA2048 mchid=\"merchant-id\","
        r"nonce_str=\"[0-9a-f]+\","
        r"signature=\"test-signature\","
        r"timestamp=\"[0-9]+\","
        r"serial_no=\"merchant-serial\"",
        authorization,
    )


def test_wechat_payment_references_use_uuid_hex_within_channel_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """微信下单和退款均使用可逆的 32 位单号，避免触发商户订单号长度限制。"""
    captured: list[tuple[str, str, dict[str, object]]] = []

    def fake_request(
        self: WeChatPayGateway,
        method: str,
        path: str,
        payload: dict[str, object],
    ) -> dict[str, object]:
        del self
        captured.append((method, path, payload))
        if path.endswith("/refunds"):
            return {"status": "SUCCESS", "refund_id": "wechat-refund-1"}
        return {"prepay_id": "wechat-prepay-1"}

    monkeypatch.setattr(WeChatPayGateway, "_request", fake_request)
    monkeypatch.setattr(WeChatPayGateway, "_sign", lambda self, message: "test-signature")
    gateway = WeChatPayGateway()
    payment_no = str(uuid.uuid4())
    refund_no = str(uuid.uuid4())

    gateway.create_app_payment(
        payment_no=payment_no,
        description="测试订单",
        amount_minor=100,
    )
    gateway.refund(
        payment_no=payment_no,
        refund_no=refund_no,
        amount_minor=100,
    )

    payment_payload = captured[0][2]
    refund_payload = captured[1][2]
    assert payment_payload["out_trade_no"] == payment_no.replace("-", "")
    assert len(str(payment_payload["out_trade_no"])) == 32
    assert refund_payload["out_trade_no"] == payment_no.replace("-", "")
    assert refund_payload["out_refund_no"] == refund_no.replace("-", "")


def test_wechat_http_error_logs_safe_response_for_diagnosis(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """微信拒绝请求时记录状态码和响应摘要，但不记录请求签名或密钥。"""

    def raise_http_error(*args: object, **kwargs: object) -> None:
        del args, kwargs
        raise HTTPError(
            url="https://api.mch.weixin.qq.com/v3/pay/transactions/app",
            code=400,
            msg="Bad Request",
            hdrs={},
            fp=io.BytesIO(
                json.dumps(
                    {"code": "PARAM_ERROR", "message": '"mchid" 无法使用'},
                    ensure_ascii=False,
                ).encode("utf-8")
            ),
        )

    monkeypatch.setattr(
        "backend.integrations.payments.wechat.urllib.request.urlopen",
        raise_http_error,
    )
    monkeypatch.setattr(WeChatPayGateway, "_validate_config", lambda self: None)
    monkeypatch.setattr(WeChatPayGateway, "_sign", lambda self, message: "test-signature")

    with (
        caplog.at_level(logging.WARNING, logger="jianmianliao.payment.wechat"),
        pytest.raises(PaymentGatewayError, match="PARAM_ERROR"),
    ):
        WeChatPayGateway()._request(
            "POST",
            "/v3/pay/transactions/app",
            {"description": "测试订单"},
        )

    record = caplog.records[-1]
    assert record.wechat_http_status == 400
    assert "PARAM_ERROR" in record.wechat_response
    assert "mchid" in record.wechat_response
    assert "test-signature" not in record.wechat_response
