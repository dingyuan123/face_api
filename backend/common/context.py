from __future__ import annotations

from contextvars import ContextVar

trace_id_var: ContextVar[str] = ContextVar("trace_id", default="")


def current_trace_id() -> str:
    return trace_id_var.get() or "unavailable"
