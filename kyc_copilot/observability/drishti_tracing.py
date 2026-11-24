"""Drishti Distributed Tracing — OpenTelemetry Spans (InMemory + Cloud Trace).

Named after *Drishti* (focused vision / insight), this module instruments the
Sutradhar orchestrator, parallel sub-agents, and every tool call with linked
OpenTelemetry spans. Exports to InMemorySpanExporter locally/CI for test
verification, with an optional Google Cloud Trace adapter in production.
"""

from __future__ import annotations

import os
from contextlib import contextmanager
from typing import Any, Iterator

from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import ReadableSpan, TracerProvider
from opentelemetry.sdk.trace.export import (
    BatchSpanProcessor,
    ConsoleSpanExporter,
    SimpleSpanProcessor,
)
from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
    InMemorySpanExporter,
)

_SERVICE_NAME = "arthashastra-kyc-copilot"
_IN_MEMORY_EXPORTER = InMemorySpanExporter()
_TRACER_PROVIDER: TracerProvider | None = None


def configure_drishti_tracing() -> TracerProvider:
    """Initializes the global OpenTelemetry TracerProvider once."""
    global _TRACER_PROVIDER
    if _TRACER_PROVIDER is not None:
        return _TRACER_PROVIDER

    resource = Resource.create({"service.name": _SERVICE_NAME})
    provider = TracerProvider(resource=resource)
    provider.add_span_processor(SimpleSpanProcessor(_IN_MEMORY_EXPORTER))

    if os.getenv("KYC_TRACE_CONSOLE", "false").lower() == "true":
        provider.add_span_processor(SimpleSpanProcessor(ConsoleSpanExporter()))

    if os.getenv("ENABLE_CLOUD_TRACE", "false").lower() == "true":
        try:
            from opentelemetry.exporter.cloud_trace import (  # type: ignore[import-not-found]
                CloudTraceSpanExporter,
            )

            provider.add_span_processor(
                BatchSpanProcessor(CloudTraceSpanExporter())
            )
        except Exception:
            # Keep local InMemory exporter active if GCP exporter isn't installed.
            pass

    trace.set_tracer_provider(provider)
    _TRACER_PROVIDER = provider
    return provider


def get_drishti_tracer(name: str = "kyc_copilot") -> trace.Tracer:
    """Returns an instrumented OpenTelemetry tracer."""
    provider = configure_drishti_tracing()
    return provider.get_tracer(name)


def current_trace_context() -> tuple[str, str]:
    """Returns the active OpenTelemetry (trace_id, span_id) hex pair."""
    span = trace.get_current_span()
    ctx = span.get_span_context() if span else None
    if ctx and ctx.is_valid:
        return f"{ctx.trace_id:032x}", f"{ctx.span_id:016x}"
    return "0" * 32, "0" * 16


def get_recorded_spans() -> list[ReadableSpan]:
    """Returns finished spans captured in memory for evaluation assertions."""
    return list(_IN_MEMORY_EXPORTER.get_finished_spans())


def clear_recorded_spans() -> None:
    """Clears in-memory spans between evaluation test cases."""
    _IN_MEMORY_EXPORTER.clear()


@contextmanager
def traced_span(
    span_name: str,
    attributes: dict[str, Any] | None = None,
) -> Iterator[trace.Span]:
    """Context manager creating a linked OpenTelemetry child span."""
    tracer = get_drishti_tracer()
    with tracer.start_as_current_span(span_name) as span:
        if attributes:
            for key, value in attributes.items():
                if value is not None:
                    span.set_attribute(key, str(value))
        yield span
