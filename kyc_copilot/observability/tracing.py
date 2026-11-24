"""Spec-aligned alias module exporting Drishti OpenTelemetry tracing utilities."""

from kyc_copilot.observability.drishti_tracing import (
    clear_recorded_spans,
    configure_drishti_tracing,
    current_trace_context,
    get_drishti_tracer,
    get_recorded_spans,
    traced_span,
)

__all__ = [
    "clear_recorded_spans",
    "configure_drishti_tracing",
    "current_trace_context",
    "get_drishti_tracer",
    "get_recorded_spans",
    "traced_span",
]
