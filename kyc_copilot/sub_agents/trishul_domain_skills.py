"""Trishul Domain Specialist Pool (ParallelAgent on Gemini 4 Hydrogen).

Named after *Trishul* (three-pronged trident), executes three domain skill
agents concurrently:
1. Vidhi — Legal Skill Agent (articles, dual-class voting, trust deeds, bearer shares)
2. Shulka — Tax Skill Agent (FATCA/CRS residency & HMRC VAT verification)
3. Kosa — Credit & Treasury Skill Agent (financial ratios & shell risk)
"""

from __future__ import annotations

from google.adk.agents import LlmAgent, ParallelAgent

from kyc_copilot.callbacks.guardrails import (
    dharma_after_tool_callback,
    dharma_before_tool_callback,
)
from kyc_copilot.constitution import (
    HYDROGEN_FAST_MODEL,
    KOSA_CREDIT_INSTRUCTION,
    SHULKA_TAX_INSTRUCTION,
    VIDHI_LEGAL_INSTRUCTION,
)

vidhi_legal_skill_agent = LlmAgent(
    name="vidhi_legal_skill_agent",
    model=HYDROGEN_FAST_MODEL,
    description=(
        "Legal specialist analyzing articles of incorporation, Class-B voting "
        "schedules, offshore trust deeds, and bearer-share clauses."
    ),
    instruction=VIDHI_LEGAL_INSTRUCTION,
    before_tool_callback=dharma_before_tool_callback,
    after_tool_callback=dharma_after_tool_callback,
)

shulka_tax_fatca_crs_agent = LlmAgent(
    name="shulka_tax_fatca_crs_agent",
    model=HYDROGEN_FAST_MODEL,
    description=(
        "Tax specialist verifying FATCA classification, CRS multi-jurisdiction "
        "tax residency, and HMRC VAT registration."
    ),
    instruction=SHULKA_TAX_INSTRUCTION,
    before_tool_callback=dharma_before_tool_callback,
    after_tool_callback=dharma_after_tool_callback,
)

kosa_credit_skill_agent = LlmAgent(
    name="kosa_credit_skill_agent",
    model=HYDROGEN_FAST_MODEL,
    description=(
        "Credit & treasury specialist evaluating EBITDA margin, leverage, "
        "liquidity ratios, and financial consistency."
    ),
    instruction=KOSA_CREDIT_INSTRUCTION,
    before_tool_callback=dharma_before_tool_callback,
    after_tool_callback=dharma_after_tool_callback,
)

trishul_domain_specialist_pool = ParallelAgent(
    name="trishul_domain_specialist_pool",
    description=(
        "Parallel specialist pool concurrently executing Legal (Vidhi), Tax "
        "FATCA/CRS (Shulka), and Credit (Kosa) commercial KYC reviews."
    ),
    sub_agents=[
        vidhi_legal_skill_agent,
        shulka_tax_fatca_crs_agent,
        kosa_credit_skill_agent,
    ],
)

# Spec-aligned alias
domain_specialist_pool = trishul_domain_specialist_pool
