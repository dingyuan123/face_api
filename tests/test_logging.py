from __future__ import annotations

import json
import logging

from backend.common.logging import (
    REDACTED,
    RedactingJsonFormatter,
    RequestTraceFilter,
    SensitiveDataFilter,
)


def test_structured_logging_redacts_sensitive_values_and_keeps_trace_id() -> None:
    logger = logging.getLogger("tests.redaction")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()
    logger.propagate = False
    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(RedactingJsonFormatter())
    stream_handler.addFilter(RequestTraceFilter())
    stream_handler.addFilter(SensitiveDataFilter())
    logger.addHandler(stream_handler)

    logger.info(
        "login password=plain-secret token=plain-token phone=13800138000",
        extra={"password": "plain-secret", "authorization": "Bearer plain-token", "user_id": 7},
    )

    record = logger.handlers[0].formatter.format(
        _make_record("password=plain-secret token=plain-token phone=13800138000")
    )
    payload = json.loads(record)
    assert "plain-secret" not in record
    assert "plain-token" not in record
    assert "13800138000" not in record
    assert payload["password"] == REDACTED
    assert payload["authorization"] == REDACTED
    assert payload["user_id"] == 7


def _make_record(message: str) -> logging.LogRecord:
    record = logging.LogRecord(
        name="tests.redaction",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg=message,
        args=(),
        exc_info=None,
    )
    record.password = "plain-secret"
    record.authorization = "Bearer plain-token"
    record.user_id = 7
    record.trace_id = "trace-value"
    SensitiveDataFilter().filter(record)
    return record
