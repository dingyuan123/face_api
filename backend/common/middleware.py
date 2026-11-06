from __future__ import annotations

import logging
import time
import uuid

from django.http import HttpRequest, HttpResponse, JsonResponse
from django.utils.deprecation import MiddlewareMixin

from backend.common.context import current_trace_id, trace_id_var
from backend.common.errors import ERROR_MESSAGES, ErrorCode
from backend.common.renderers import build_error_envelope


class RequestContextMiddleware(MiddlewareMixin):
    def process_request(self, request: HttpRequest) -> None:
        trace_id = uuid.uuid4().hex
        trace_id_var.set(trace_id)
        request.trace_id = trace_id

    def process_response(
        self,
        request: HttpRequest,
        response: HttpResponse,
    ) -> HttpResponse:
        trace_id = getattr(request, "trace_id", current_trace_id())
        response["X-Request-ID"] = trace_id
        response["X-Trace-ID"] = trace_id
        return response


class RequestLoggingMiddleware(MiddlewareMixin):
    logger = logging.getLogger("jianmianliao.request")

    def process_response(
        self,
        request: HttpRequest,
        response: HttpResponse,
    ) -> HttpResponse:
        started_at = getattr(request, "_started_at", None)
        duration_ms = (time.monotonic() - started_at) * 1000 if started_at else None
        self.logger.info(
            "request.completed",
            extra={
                "event": "request.completed",
                "method": request.method,
                "path": request.path,
                "status_code": response.status_code,
                "duration_ms": round(duration_ms, 2) if duration_ms is not None else None,
                "user_id": getattr(getattr(request, "user", None), "id", None),
            },
        )
        return response

    def process_request(self, request: HttpRequest) -> None:
        request._started_at = time.monotonic()


class ExceptionHandlingMiddleware(MiddlewareMixin):
    logger = logging.getLogger("jianmianliao.errors")

    def process_exception(
        self,
        request: HttpRequest,
        exception: Exception,
    ) -> JsonResponse:
        self.logger.exception(
            "request.unhandled_exception",
            extra={
                "event": "request.unhandled_exception",
                "path": request.path,
                "method": request.method,
                "exception_type": type(exception).__name__,
            },
        )
        payload = build_error_envelope(
            ErrorCode.INTERNAL_ERROR,
            ERROR_MESSAGES[ErrorCode.INTERNAL_ERROR],
        )
        return JsonResponse(payload, status=500, safe=False)
