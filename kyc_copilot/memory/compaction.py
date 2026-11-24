"""Sankshepa Context Compaction (ADK EventsCompactionConfig + Token Window).

Named after *Sankshepa* (Sanskrit: concise distillation of vast treatises),
this module prevents context-window bloat in two complementary layers:
1. Native Google ADK `EventsCompactionConfig` attached to `kyc_app`.
2. A simple, deterministic token-budget sliding window compactor that
   distills verbose raw registry filings and adverse media payloads into a
   compact structured JSON summary once turn history exceeds 12,000 tokens,
   strictly preserving every `snapshot_id` for audit traceability.
"""

from __future__ import annotations

import json
import os
from typing import Any

from google.adk.apps.app import EventsCompactionConfig

from kyc_copilot.constitution import HISTORY_COMPACTION_TOKEN_LIMIT


def estimate_token_count(payload: Any) -> int:
    """Simple, deterministic ~4-chars-per-token estimator."""
    serialized = payload if isinstance(payload, str) else json.dumps(payload, default=str)
    return max(1, len(serialized) // 4)


def build_adk_compaction_config(
    token_threshold: int = HISTORY_COMPACTION_TOKEN_LIMIT,
    event_retention_size: int | None = None,
) -> EventsCompactionConfig:
    """Builds the native ADK EventsCompactionConfig attached to the root App."""
    retention = (
        event_retention_size
        if event_retention_size is not None
        else int(os.getenv("KYC_COMPACTION_RETENTION_EVENTS", "6"))
    )
    return EventsCompactionConfig(
        token_threshold=token_threshold,
        event_retention_size=retention,
    )


class SankshepaHistoryCompactor:
    """Deterministic sliding-window compactor preserving 100% of snapshot IDs."""

    def __init__(
        self,
        token_threshold: int = HISTORY_COMPACTION_TOKEN_LIMIT,
        keep_recent_events: int = 4,
    ) -> None:
        self.token_threshold = token_threshold
        self.keep_recent_events = keep_recent_events

    def compact_history(
        self, events: list[dict[str, Any]]
    ) -> tuple[list[dict[str, Any]], bool]:
        """Compacts older verbose events when total tokens exceed threshold.

        Args:
            events: Chronological list of conversation/tool event dicts.

        Returns:
            A tuple of `(compacted_events, was_compacted)` where every
            `snapshot_id` from compacted turns is preserved in a single
            structured `sankshepa_compacted_summary` event.
        """
        total_tokens = estimate_token_count(events)
        if total_tokens <= self.token_threshold or len(events) <= self.keep_recent_events:
            return events, False

        older_events = events[: -self.keep_recent_events]
        recent_events = events[-self.keep_recent_events :]

        preserved_snapshots: list[str] = []
        compacted_tools: list[str] = []
        key_statuses: list[str] = []

        for evt in older_events:
            snap_id = evt.get("snapshot_id")
            if snap_id and snap_id not in preserved_snapshots:
                preserved_snapshots.append(str(snap_id))
            tool_name = evt.get("tool_name") or evt.get("role") or "event"
            compacted_tools.append(str(tool_name))
            status = evt.get("status")
            if status:
                key_statuses.append(f"{tool_name}:{status}")

        summary_event: dict[str, Any] = {
            "role": "system",
            "event_type": "sankshepa_compacted_summary",
            "compacted_event_count": len(older_events),
            "original_estimated_tokens": total_tokens,
            "preserved_snapshot_ids": preserved_snapshots,
            "tools_summarized": compacted_tools,
            "status_digest": key_statuses,
            "summary": (
                f"Compacted {len(older_events)} verbose historical turns while "
                f"preserving {len(preserved_snapshots)} immutable snapshot IDs."
            ),
        }
        return [summary_event, *recent_events], True
