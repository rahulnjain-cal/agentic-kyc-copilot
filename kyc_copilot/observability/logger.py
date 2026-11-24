"""Spec-aligned alias module exporting Shilalekh structured JSON logging."""

from kyc_copilot.observability.shilalekh_logger import (
    clear_recorded_logs,
    configure_shilalekh_logging,
    get_recorded_logs,
    get_recorded_raw_json_lines,
    get_shilalekh_logger,
)

__all__ = [
    "clear_recorded_logs",
    "configure_shilalekh_logging",
    "get_recorded_logs",
    "get_recorded_raw_json_lines",
    "get_shilalekh_logger",
]
