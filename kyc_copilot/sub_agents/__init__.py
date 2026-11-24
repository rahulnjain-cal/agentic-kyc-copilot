"""Exports all modular KYC Copilot ADK sub-agents (Indian & spec aliases)."""

from kyc_copilot.sub_agents.charaka_semantic_screening import (
    charaka_semantic_screening_agent,
    semantic_screening_agent,
)
from kyc_copilot.sub_agents.dvarapala_intake_rfi import (
    dvarapala_intake_rfi_agent,
    intake_and_rfi_agent,
)
from kyc_copilot.sub_agents.namarupa_entity_resolution import (
    entity_resolution_agent,
    namarupa_entity_resolution_agent,
)
from kyc_copilot.sub_agents.pramana_edd_qra_critic import (
    edd_qra_critic_pipeline,
    pramana_edd_qra_critic_pipeline,
)
from kyc_copilot.sub_agents.trishul_domain_skills import (
    domain_specialist_pool,
    trishul_domain_specialist_pool,
)
from kyc_copilot.sub_agents.vamsha_ubo_structure import (
    ubo_and_structure_agent,
    vamsha_ubo_structure_agent,
)

__all__ = [
    "charaka_semantic_screening_agent",
    "domain_specialist_pool",
    "dvarapala_intake_rfi_agent",
    "edd_qra_critic_pipeline",
    "entity_resolution_agent",
    "intake_and_rfi_agent",
    "namarupa_entity_resolution_agent",
    "pramana_edd_qra_critic_pipeline",
    "semantic_screening_agent",
    "trishul_domain_specialist_pool",
    "ubo_and_structure_agent",
    "vamsha_ubo_structure_agent",
]
