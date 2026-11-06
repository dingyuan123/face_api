from __future__ import annotations

from typing import Any

from django.core.exceptions import PermissionDenied as DjangoPermissionDenied
from django.http import Http404
from rest_framework import exceptions, status
from rest_framework.response import Response
from rest_framework.views import exception_handler

from backend.common.errors import ERROR_MESSAGES, ErrorCode
from backend.common.logging import is_sensitive_key, redact_value
from backend.common.renderers import build_error_envelope


class ApiError(exceptions.APIException):
    status_code = status.HTTP_400_BAD_REQUEST
    default_code = ErrorCode.API_ERROR

    def __init__(
        self,
        code: str,
        message: str,
        *,
        status_code: int = status.HTTP_400_BAD_REQUEST,
        details: Any | None = None,
    ) -> None:
        super().__init__(message, code)
        self.machine_code = code
        self.message = message
        self.status_code = status_code
        self.details = details


def custom_exception_handler(
    exc: Exception,
    context: dict[str, Any],
) -> Response | None:
    if isinstance(exc, ApiError):
        return _error_response(
            exc.status_code,
            exc.machine_code,
            exc.message,
            _safe_details(exc.details),
        )

    response = exception_handler(exc, context)
    if response is None:
        return None

    code, message = _map_dr_exception(exc, response.status_code)
    if isinstance(exc, exceptions.NotAuthenticated):
        response.status_code = status.HTTP_401_UNAUTHORIZED
    response.data = build_error_envelope(code, message, _safe_details(response.data))
    return response


def _map_dr_exception(exc: Exception, status_code: int) -> tuple[str, str]:
    if isinstance(exc, exceptions.NotAuthenticated):
        return ErrorCode.AUTHENTICATION_REQUIRED, ERROR_MESSAGES[ErrorCode.AUTHENTICATION_REQUIRED]
    if isinstance(exc, exceptions.AuthenticationFailed):
        detail_code = getattr(getattr(exc, "detail", None), "code", None)
        if detail_code in {
            ErrorCode.AUTH_ACCOUNT_NOT_ALLOWED,
            ErrorCode.AUTH_TOKEN_INVALID,
            ErrorCode.AUTH_TOKEN_EXPIRED,
        }:
            return detail_code, ERROR_MESSAGES[detail_code]
        return ErrorCode.AUTH_TOKEN_INVALID, ERROR_MESSAGES[ErrorCode.AUTH_TOKEN_INVALID]
    if isinstance(exc, (exceptions.PermissionDenied, DjangoPermissionDenied)):
        return ErrorCode.PERMISSION_DENIED, ERROR_MESSAGES[ErrorCode.PERMISSION_DENIED]
    if isinstance(exc, (exceptions.ValidationError,)):
        return ErrorCode.VALIDATION_ERROR, ERROR_MESSAGES[ErrorCode.VALIDATION_ERROR]
    if isinstance(exc, Http404):
        return ErrorCode.NOT_FOUND, ERROR_MESSAGES[ErrorCode.NOT_FOUND]
    if isinstance(exc, exceptions.MethodNotAllowed):
        return ErrorCode.METHOD_NOT_ALLOWED, ERROR_MESSAGES[ErrorCode.METHOD_NOT_ALLOWED]
    if isinstance(exc, exceptions.Throttled):
        return ErrorCode.RATE_LIMITED, ERROR_MESSAGES[ErrorCode.RATE_LIMITED]
    if status_code >= 500:
        return ErrorCode.INTERNAL_ERROR, ERROR_MESSAGES[ErrorCode.INTERNAL_ERROR]
    return ErrorCode.API_ERROR, ERROR_MESSAGES[ErrorCode.API_ERROR]


def _safe_details(detail: Any) -> Any:
    if isinstance(detail, dict):
        return {
            str(key): "[REDACTED]" if is_sensitive_key(str(key)) else _safe_details(value)
            for key, value in detail.items()
        }
    if isinstance(detail, (list, tuple)):
        return [_safe_details(value) for value in detail]
    return redact_value(str(detail))


def _error_response(status_code: int, code: str, message: str, details: Any | None) -> Response:
    return Response(build_error_envelope(code, message, details), status=status_code)
