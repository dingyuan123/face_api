"""支付商户密钥兼容格式和支付宝本地签名测试。"""

from __future__ import annotations

import base64
import json
import logging
from unittest.mock import patch
from urllib.parse import parse_qs

import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.asymmetric.padding import PKCS1v15
from django.test import override_settings

from backend.integrations.payments.alipay import AlipayGateway
from backend.integrations.payments.contracts import PaymentGatewayError
from backend.integrations.payments.crypto import load_private_key, load_public_key


def _generated_key_material() -> tuple[str, str]:
    """生成测试用 Base64 DER 商户私钥和支付平台公钥。"""
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_der = private_key.private_bytes(
        encoding=serialization.Encoding.DER,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    public_der = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.DER,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    return (
        base64.b64encode(private_der).decode(),
        base64.b64encode(public_der).decode(),
    )


def test_payment_keys_accept_base64_der_environment_values() -> None:
    private_value, public_value = _generated_key_material()

    private_key = load_private_key(private_value)
    public_key = load_public_key(public_value)

    assert private_key.key_size == 2048
    assert public_key.key_size == 2048


@override_settings(
    ALIPAY_APP_ID="2021000000000000",
    ALIPAY_NOTIFY_URL="https://api.example.com/api/v1/payments/alipay/notify/",
    ALIPAY_GATEWAY_URL="https://openapi.alipay.com/gateway.do",
)
def test_alipay_order_string_signs_base64_der_private_key() -> None:
    private_value, public_value = _generated_key_material()

    with override_settings(
        ALIPAY_PRIVATE_KEY=private_value,
        ALIPAY_PUBLIC_KEY=public_value,
    ):
        result = AlipayGateway().create_app_payment(
            payment_no="d9e4d92a-0b77-4503-b007-8504538c4a5d",
            description="见面聊服务预约",
            amount_minor=10_000,
        )
    params = {
        key: values[0] for key, values in parse_qs(result.client_payload["order_string"]).items()
    }

    assert params["app_id"] == "2021000000000000"
    assert params["method"] == "alipay.trade.app.pay"
    assert params["sign_type"] == "RSA2"
    signature = base64.b64decode(params["sign"], validate=True)
    sign_content = "&".join(
        f"{key}={value}" for key, value in sorted(params.items()) if key != "sign"
    )
    private_key = load_private_key(private_value)
    private_key.public_key().verify(
        signature,
        sign_content.encode("utf-8"),
        PKCS1v15(),
        hashes.SHA256(),
    )
    assert len(signature) == 256


@override_settings(
    ALIPAY_APP_ID="2021000000000000",
    ALIPAY_NOTIFY_URL="https://api.example.com/api/v1/payments/alipay/notify/",
    ALIPAY_GATEWAY_URL="https://openapi.alipay.com/gateway.do",
)
def test_alipay_gateway_logs_and_decodes_gbk_error_response(caplog) -> None:
    private_value, public_value = _generated_key_material()
    body = json.dumps(
        {
            "alipay_trade_query_response": {
                "code": "40002",
                "sub_code": "isv.invalid-signature",
                "sub_msg": "验证签名失败",
            }
        },
        ensure_ascii=False,
    ).encode("gb18030")

    class FakeHeaders(dict):
        def get_content_charset(self) -> str:
            return "gbk"

    class FakeResponse:
        headers = FakeHeaders({"Content-Type": "text/html;charset=GBK"})

        def read(self) -> bytes:
            return body

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    with caplog.at_level(logging.INFO, logger="jianmianliao.payment.alipay"):
        with (
            override_settings(
                ALIPAY_PRIVATE_KEY=private_value,
                ALIPAY_PUBLIC_KEY=public_value,
            ),
            patch(
                "backend.integrations.payments.alipay.urllib.request.urlopen",
                return_value=FakeResponse(),
            ),
            pytest.raises(PaymentGatewayError, match="验证签名失败"),
        ):
            AlipayGateway()._request(
                "alipay.trade.query",
                {"out_trade_no": "d9e4d92a-0b77-4503-b007-8504538c4a5d"},
            )

    assert "支付宝接口开始请求" in caplog.text
    assert "支付宝接口返回响应" in caplog.text
    assert "支付宝接口返回业务错误" in caplog.text
    assert any(
        getattr(record, "alipay_response", {}).get("sub_code") == "isv.invalid-signature"
        for record in caplog.records
    )
    assert all("sign" not in record.__dict__ for record in caplog.records)
