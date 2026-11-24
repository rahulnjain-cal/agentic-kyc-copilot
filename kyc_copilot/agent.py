"""ADK Root Entrypoint: Sutradhar KYC Root Orchestrator (Gemini 4 Neon).

Exports `root_agent` (for `adk web` / `adk run` / Vertex AI Agent Engine) and
`kyc_app` (configured with ADK `EventsCompactionConfig` and `DharmaPolicyPlugin`).
"""

from __future__ import annotations

from google.adk.agents import LlmAgent
from google.adk.apps.app import App

from kyc_copilot.callbacks.guardrails import (
    DharmaPolicyPlugin,
    dharma_after_tool_callback,
    dharma_before_tool_callback,
)
from kyc_copilot.constitution import (
    NEON_ORCHESTRATOR_MODEL,
    SUTRADHAR_ORCHESTRATOR_INSTRUCTION,
)
from kyc_copilot.memory.compaction import build_adk_compaction_config
from kyc_copilot.sub_agents import (
    charaka_semantic_screening_agent,
    dvarapala_intake_rfi_agent,
    namarupa_entity_resolution_agent,
    pramana_edd_qra_critic_pipeline,
    trishul_domain_specialist_pool,
    vamsha_ubo_structure_agent,
)

sutradhar_kyc_orchestrator = LlmAgent(
    name="sutradhar_kyc_orchestrator",
    model=NEON_ORCHESTRATOR_MODEL,
    description=(
        "Root Commercial KYC & Entity Resolution Orchestrator coordinating "
        "intake/RFI, registry resolution, deterministic UBO math, parallel "
        "domain specialists, semantic screening, and cited QRA + HITL sign-off."
    ),
    instruction=SUTRADHAR_ORCHESTRATOR_INSTRUCTION,
    sub_agents=[
        dvarapala_intake_rfi_agent,
        namarupa_entity_resolution_agent,
        vamsha_ubo_structure_agent,
        trishul_domain_specialist_pool,
        charaka_semantic_screening_agent,
        pramana_edd_qra_critic_pipeline,
    ],
    before_tool_callback=dharma_before_tool_callback,
    after_tool_callback=dharma_after_tool_callback,
)

# Standard ADK entrypoint & spec-aligned orchestrator alias
kyc_root_orchestrator = sutradhar_kyc_orchestrator
root_agent = sutradhar_kyc_orchestrator

# ADK Application bundle with native History Compaction + Dharma Policy Plugin
kyc_app = App(
    name="arthashastra_kyc_copilot",
    root_agent=root_agent,
    plugins=[DharmaPolicyPlugin()],
    events_compaction_config=build_adk_compaction_config(),
)
