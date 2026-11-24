"""Dvarapala Intake & RFI Sub-Agent (SequentialAgent on Gemini 4 Hydrogen).

Validates uploaded document legibility/expiry first, then runs silent CRM and
Digital Twin pre-population before generating any targeted client RFI.
"""

from __future__ import annotations

from google.adk.agents import LlmAgent, SequentialAgent

from kyc_copilot.callbacks.guardrails import (
    dharma_after_tool_callback,
    dharma_before_tool_callback,
)
from kyc_copilot.constitution import (
    DVARAPALA_INTAKE_INSTRUCTION,
    HYDROGEN_FAST_MODEL,
)
from kyc_copilot.tools.dvarapala_intake_tools import (
    assess_uploaded_document_quality_and_classify,
    execute_silent_entity_pre_lookup,
    generate_targeted_client_rfi_outreach,
)

chitra_doc_intake_agent = LlmAgent(
    name="chitra_doc_intake_agent",
    model=HYDROGEN_FAST_MODEL,
    description=(
        "Validates uploaded KYC document scan resolution (DPI >= 150), blur, "
        "proof-of-address freshness (<= 90 days), and entity match."
    ),
    instruction=DVARAPALA_INTAKE_INSTRUCTION,
    tools=[assess_uploaded_document_quality_and_classify],
    before_tool_callback=dharma_before_tool_callback,
    after_tool_callback=dharma_after_tool_callback,
)

gupt_silent_lookup_rfi_agent = LlmAgent(
    name="gupt_silent_lookup_rfi_agent",
    model=HYDROGEN_FAST_MODEL,
    description=(
        "Silently pre-populates corporate attributes from internal CRM / Smriti "
        "store and dispatches targeted RFIs only for genuinely missing fields."
    ),
    instruction=DVARAPALA_INTAKE_INSTRUCTION,
    tools=[
        execute_silent_entity_pre_lookup,
        generate_targeted_client_rfi_outreach,
    ],
    before_tool_callback=dharma_before_tool_callback,
    after_tool_callback=dharma_after_tool_callback,
)

dvarapala_intake_rfi_agent = SequentialAgent(
    name="dvarapala_intake_rfi_agent",
    description=(
        "Stage 1 Intake & RFI pipeline: validates document quality, runs silent "
        "lookup first, and prevents redundant RM-client RFI ping-pong."
    ),
    sub_agents=[chitra_doc_intake_agent, gupt_silent_lookup_rfi_agent],
)

# Spec-aligned alias
intake_and_rfi_agent = dvarapala_intake_rfi_agent
