"""Observability package: Shilalekh JSON logging & Drishti OpenTelemetry tracing."""

from kyc_copilot.observability.drishti_tracing import (
    clear_recorded_spans,
    current_trace_context,
    get_drishti_tracer,
    get_recorded_spans,
    traced_span,
)
from kyc_copilot.observability.shilalekh_logger import (
    clear_recorded_logs,
    get_recorded_logs,
    get_shilalekh_logger,
)

__all__ = [
    "clear_recorded_logs",
    "clear_recorded_spans",
    "current_trace_context",
    "get_drishti_tracer",
    "get_recorded_logs",
    "get_recorded_spans",
    "get_shilalekh_logger",
    "traced_span",
]
