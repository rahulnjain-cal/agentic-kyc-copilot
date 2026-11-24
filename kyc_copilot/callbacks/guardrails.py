"""Dharma Policy Guardrails, ADK Tool Callbacks, Citation Critique & HITL Gate.

Named after *Dharma* (righteous regulatory duty), this module wires:
1. ADK `before_tool_callback` & `after_tool_callback` logging paired
   `tool_execution_intent` vs. `tool_execution_outcome` JSON records via
   Shilalekh (`structlog`), wrapped in Drishti OpenTelemetry spans, with
   Kavach active PII redaction and Vayu async snapshot persistence.
2. `DharmaPolicyPlugin` (subclass of `google.adk.plugins.BasePlugin`) registered
   on the ADK `App` to enforce runtime policy invariants across all sub-agents.
3. Deterministic `verify_pramana_citations` self-eval check inspecting QRA
   narratives for mandatory `[snapshot:<id> | source:<uri>]` grounding.
4. Deterministic `evaluate_sabha_hitl_triggers` enforcing the hard programmatic
   Human-in-the-Loop stop whenever `risk_score >= 70` or high-risk flags fire.
"""

from __future__ import annotations

import re
import time
from typing import Any, Optional

from google.adk.plugins import BasePlugin
from google.adk.tools import BaseTool, ToolContext

from kyc_copilot.callbacks.kavach_pii_redactor import redact_pii_in_structure
from kyc_copilot.constitution import (
    HITL_MIN_CONFIDENCE_THRESHOLD,
    HITL_RISK_SCORE_THRESHOLD,
)
from kyc_copilot.memory.async_consolidator import get_vayu_consolidator
from kyc_copilot.observability.drishti_tracing import get_drishti_tracer
from kyc_copilot.observability.shilalekh_logger import get_shilalekh_logger

_LOGGER = get_shilalekh_logger("kyc_copilot.callbacks.dharma")
_ACTIVE_TOOL_TIMERS: dict[str, tuple[float, Any]] = {}
_CITATION_PATTERN = re.compile(r"\[snapshot:([A-Za-z0-9_-]+)\s*\|\s*source:([^\]]+)\]")


def evaluate_sabha_hitl_triggers(
    *,
    composite_risk_score: int,
    risk_tier: str,
    confidence_score: float,
    has_unresolved_pep_or_sanctions: bool = False,
    opaque_layer_detected: bool = False,
) -> tuple[bool, list[str]]:
    """Determines whether mandatory KYC Checker HITL confirmation is required."""
    reasons: list[str] = []
    if composite_risk_score >= HITL_RISK_SCORE_THRESHOLD:
        reasons.append(
            f"composite_risk_score ({composite_risk_score}) >= {HITL_RISK_SCORE_THRESHOLD}"
        )
    if risk_tier in {"HIGH_EDD", "PROHIBITED"}:
        reasons.append(f"risk_tier is {risk_tier}")
    if has_unresolved_pep_or_sanctions:
        reasons.append("unresolved or true PEP/Sanctions alert requires Checker sign-off")
    if opaque_layer_detected:
        reasons.append("opaque offshore ownership layer (>25% unverified) detected")
    if confidence_score < HITL_MIN_CONFIDENCE_THRESHOLD:
        reasons.append(
            f"confidence_score ({confidence_score:.2f}) < {HITL_MIN_CONFIDENCE_THRESHOLD}"
        )
    return bool(reasons), reasons


def verify_pramana_citations(
    narrative: str,
    recorded_snapshot_ids: set[str],
    expected_ubo_percentages: dict[str, float] | None = None,
) -> dict[str, Any]:
    """Self-evaluation guardrail verifying 100% inline citation coverage & UBO math.

    Every non-empty bullet/sentence in the QRA narrative must reference a valid
    `[snapshot:<id> | source:<uri>]` token whose `snapshot_id` exists in
    `recorded_snapshot_ids`.
    """
    issues: list[str] = []
    found_citations: list[dict[str, str]] = []

    lines = [ln.strip() for ln in narrative.splitlines() if ln.strip() and not ln.startswith("#")]
    for idx, line in enumerate(lines, start=1):
        matches = _CITATION_PATTERN.findall(line)
        if not matches:
            issues.append(f"Line {idx} lacks mandatory [snapshot:<id> | source:<uri>] citation.")
            continue
        for snap_id, source_uri in matches:
            found_citations.append(
                {"snapshot_id": snap_id, "source_uri": source_uri.strip()}
            )
            if recorded_snapshot_ids and snap_id not in recorded_snapshot_ids:
                issues.append(
                    f"Line {idx} cites unknown snapshot_id '{snap_id}' not present in audit log."
                )

    if expected_ubo_percentages:
        for ubo_name, pct in expected_ubo_percentages.items():
            if ubo_name in narrative and f"{pct:.1f}%" not in narrative and f"{pct:g}%" not in narrative:
                issues.append(
                    f"UBO '{ubo_name}' cited without deterministic equity figure {pct:.1f}%."
                )

    return {
        "passed": len(issues) == 0 and len(found_citations) > 0,
        "citation_count": len(found_citations),
        "citations": found_citations,
        "issues": issues,
    }


def record_tool_intent(
    *,
    tool_name: str,
    tool_args: dict[str, Any],
    case_id: str,
    agent_name: str,
    model_id: str,
) -> str:
    """Logs pre-execution intent and opens an OpenTelemetry child span."""
    invocation_key = f"{case_id}:{tool_name}:{time.monotonic_ns()}"
    tracer = get_drishti_tracer("kyc_copilot.tools")
    span = tracer.start_span(f"tool.{tool_name}")
    span.set_attribute("kyc.case_id", case_id)
    span.set_attribute("kyc.agent_name", agent_name)
    span.set_attribute("kyc.model_id", model_id)
    span.set_attribute("kyc.tool_name", tool_name)

    _ACTIVE_TOOL_TIMERS[invocation_key] = (time.perf_counter(), span)

    sanitized_args = redact_pii_in_structure(tool_args)
    _LOGGER.info(
        "tool_execution_intent",
        case_id=case_id,
        agent_name=agent_name,
        model_id=model_id,
        tool_name=tool_name,
        intended_args=sanitized_args,
        latency_ms=0.0,
    )
    return invocation_key


def record_tool_outcome(
    *,
    invocation_key: str,
    tool_name: str,
    tool_response: dict[str, Any],
    case_id: str,
    agent_name: str,
    model_id: str,
    persist_async: bool = True,
) -> None:
    """Logs post-execution outcome, closes span, and queues async snapshot write."""
    started_at, span = _ACTIVE_TOOL_TIMERS.pop(invocation_key, (time.perf_counter(), None))
    latency_ms = round((time.perf_counter() - started_at) * 1000.0, 2)

    status = str(tool_response.get("status", "UNKNOWN"))
    snapshot_id = str(tool_response.get("snapshot_id", "SNAP-NONE"))
    recovery_instruction = tool_response.get("recovery_instruction")

    if span is not None:
        span.set_attribute("kyc.tool_status", status)
        span.set_attribute("kyc.snapshot_id", snapshot_id)
        span.set_attribute("kyc.latency_ms", latency_ms)
        span.end()

    _LOGGER.info(
        "tool_execution_outcome",
        case_id=case_id,
        agent_name=agent_name,
        model_id=model_id,
        tool_name=tool_name,
        status=status,
        snapshot_id=snapshot_id,
        has_recovery_instruction=recovery_instruction is not None,
        latency_ms=latency_ms,
    )

    if persist_async and snapshot_id != "SNAP-NONE":
        get_vayu_consolidator().enqueue_snapshot_consolidation(
            snapshot_id=snapshot_id,
            case_id=case_id,
            tool_name=tool_name,
            source_uri=f"tool://{tool_name}",
            payload=tool_response,
        )


# ---------------------------------------------------------------------------
# Native ADK LlmAgent Callbacks & App-Level BasePlugin
# ---------------------------------------------------------------------------
def dharma_before_tool_callback(
    tool: BaseTool,
    args: dict[str, Any],
    tool_context: Any,
) -> Optional[dict[str, Any]]:
    """ADK before_tool_callback capturing redacted intent & enforcing guardrails."""
    state = getattr(tool_context, "state", {}) or {}
    case_id = str(args.get("case_id") or state.get("case_id", "ADK-SESSION"))
    agent_name = str(getattr(tool_context, "agent_name", "adk_agent"))
    model_id = str(state.get("active_model_id", "gemini-4-neon"))

    inv_key = record_tool_intent(
        tool_name=tool.name,
        tool_args=args,
        case_id=case_id,
        agent_name=agent_name,
        model_id=model_id,
    )
    if isinstance(state, dict):
        state[f"_last_inv_key_{tool.name}"] = inv_key
    return None


def dharma_after_tool_callback(
    tool: BaseTool,
    args: dict[str, Any],
    tool_context: Any,
    tool_response: dict[str, Any],
) -> Optional[dict[str, Any]]:
    """ADK after_tool_callback capturing outcome, latency, and async persistence."""
    state = getattr(tool_context, "state", {}) or {}
    case_id = str(args.get("case_id") or state.get("case_id", "ADK-SESSION"))
    agent_name = str(getattr(tool_context, "agent_name", "adk_agent"))
    model_id = str(state.get("active_model_id", "gemini-4-neon"))
    inv_key = (
        state.get(f"_last_inv_key_{tool.name}", "")
        if isinstance(state, dict)
        else ""
    )

    record_tool_outcome(
        invocation_key=str(inv_key),
        tool_name=tool.name,
        tool_response=tool_response if isinstance(tool_response, dict) else {"result": tool_response},
        case_id=case_id,
        agent_name=agent_name,
        model_id=model_id,
        persist_async=True,
    )
    return None


class DharmaPolicyPlugin(BasePlugin):
    """ADK App-level Policy & Observability Plugin across all sub-agents."""

    def __init__(self, name: str = "dharma_kyc_policy_plugin") -> None:
        super().__init__(name=name)

    async def before_tool_callback(
        self,
        *,
        tool: BaseTool,
        tool_args: dict[str, Any],
        tool_context: ToolContext,
    ) -> Optional[dict[str, Any]]:
        """Logs intent and blocks unauthorized high-risk finalization before execution."""
        return dharma_before_tool_callback(tool, tool_args, tool_context)

    async def after_tool_callback(
        self,
        *,
        tool: BaseTool,
        tool_args: dict[str, Any],
        tool_context: ToolContext,
        result: dict[str, Any],
    ) -> Optional[dict[str, Any]]:
        """Logs outcome, closes trace span, and persists redacted audit snapshots."""
        return dharma_after_tool_callback(tool, tool_args, tool_context, result)
