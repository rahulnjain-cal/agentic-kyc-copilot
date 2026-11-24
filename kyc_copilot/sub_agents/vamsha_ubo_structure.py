"""Vamsha UBO & Corporate Structure Sub-Agent (LlmAgent on Gemini Pro).

Traces cross-border ownership hierarchies and delegates ALL cascading equity
and voting-rights mathematics to the deterministic Python ownership calculator.
"""

from __future__ import annotations

from google.adk.agents import LlmAgent

from kyc_copilot.callbacks.guardrails import (
    dharma_after_tool_callback,
    dharma_before_tool_callback,
)
from kyc_copilot.constitution import PRO_REASONING_MODEL, VAMSHA_UBO_INSTRUCTION
from kyc_copilot.tools.vamsha_ubo_tools import (
    calculate_cascading_ubo_ownership_rollup,
)

vamsha_ubo_structure_agent = LlmAgent(
    name="vamsha_ubo_structure_agent",
    model=PRO_REASONING_MODEL,
    description=(
        "Traces multi-jurisdiction corporate ownership trees and runs "
        "deterministic Python cascading UBO math (>=25% equity & voting control)."
    ),
    instruction=VAMSHA_UBO_INSTRUCTION,
    tools=[calculate_cascading_ubo_ownership_rollup],
    before_tool_callback=dharma_before_tool_callback,
    after_tool_callback=dharma_after_tool_callback,
)

# Spec-aligned alias
ubo_and_structure_agent = vamsha_ubo_structure_agent
