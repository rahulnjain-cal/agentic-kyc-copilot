"""Shilalekh Structured JSON Logger (structlog + Kavach PII Redaction).

Named after *Shilalekh* (ancient Indian stone edicts preserving immutable public
governance records), this module configures `structlog` to output machine-
parseable JSON records enriched with OpenTelemetry `trace_id`/`span_id` and
scrubbed through `KavachPiiRedactor` before emission. Zero `print()` calls.
"""

from __future__ import annotations

import json
import logging
import sys
from typing import Any

import structlog

from kyc_copilot.callbacks.kavach_pii_redactor import redact_pii_in_structure
from kyc_copilot.observability.drishti_tracing import current_trace_context

_RECORDED_JSON_LOGS: list[str] = []
_IS_CONFIGURED = False


def _inject_drishti_trace_context(
    _logger: Any, _method_name: str, event_dict: dict[str, Any]
) -> dict[str, Any]:
    """Adds active OpenTelemetry trace_id and span_id to every log record."""
    trace_id, span_id = current_trace_context()
    event_dict.setdefault("trace_id", trace_id)
    event_dict.setdefault("span_id", span_id)
    event_dict.setdefault("case_id", "UNSCOPED")
    event_dict.setdefault("agent_name", "sutradhar_kyc_orchestrator")
    event_dict.setdefault("model_id", "deterministic")
    event_dict.setdefault("latency_ms", 0.0)
    return event_dict


def _apply_kavach_pii_scrubbing(
    _logger: Any, _method_name: str, event_dict: dict[str, Any]
) -> dict[str, Any]:
    """Actively scrubs PII from every field before JSON serialization."""
    return redact_pii_in_structure(event_dict)


def _capture_json_record(
    _logger: Any, _method_name: str, event_dict: dict[str, Any]
) -> str:
    """Renders valid JSON and stores a copy in the in-memory audit ring."""
    rendered = json.dumps(event_dict, default=str, sort_keys=True)
    _RECORDED_JSON_LOGS.append(rendered)
    return rendered


def configure_shilalekh_logging() -> None:
    """Configures structlog once for pure JSON structured logging."""
    global _IS_CONFIGURED
    if _IS_CONFIGURED:
        return

    logging.basicConfig(
        format="%(message)s",
        stream=sys.stderr,
        level=logging.INFO,
    )
    structlog.configure(
        processors=[
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.stdlib.add_log_level,
            _inject_drishti_trace_context,
            _apply_kavach_pii_scrubbing,
            _capture_json_record,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
        logger_factory=structlog.PrintLoggerFactory(file=sys.stderr),
        cache_logger_on_first_use=False,
    )
    _IS_CONFIGURED = True


def get_shilalekh_logger(name: str = "kyc_copilot") -> structlog.BoundLogger:
    """Returns a configured Shilalekh structured JSON logger."""
    configure_shilalekh_logging()
    return structlog.get_logger(name)


def get_recorded_logs() -> list[dict[str, Any]]:
    """Returns parsed JSON log objects emitted during the current run."""
    return [json.loads(line) for line in _RECORDED_JSON_LOGS]


def get_recorded_raw_json_lines() -> list[str]:
    """Returns raw JSON lines emitted during the current run."""
    return list(_RECORDED_JSON_LOGS)


def clear_recorded_logs() -> None:
    """Clears in-memory log buffer between evaluation tests."""
    _RECORDED_JSON_LOGS.clear()
