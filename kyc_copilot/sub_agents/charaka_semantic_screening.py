"""Charaka Semantic Screening Sub-Agent (Parallel Gather in Hydrogen + Pro Aggregator).

Screens corporate entities and UBOs concurrently across watchlists (Suchi) and
multilingual adverse media (Varta) using Gemini 4 Hydrogen, then runs Viveka
(Gemini Pro) to suppress name-only false positives and prioritize true risks.
"""

from __future__ import annotations

from google.adk.agents import LlmAgent, ParallelAgent, SequentialAgent

from kyc_copilot.callbacks.guardrails import (
    dharma_after_tool_callback,
    dharma_before_tool_callback,
)
from kyc_copilot.constitution import (
    CHARAKA_WATCHLIST_INSTRUCTION,
    HYDROGEN_FAST_MODEL,
    PRO_REASONING_MODEL,
    VARTA_MEDIA_INSTRUCTION,
    VIVEKA_AGGREGATOR_INSTRUCTION,
)
from kyc_copilot.tools.charaka_screening_tools import (
    evaluate_multilingual_adverse_media_relevance,
    screen_entity_and_ubos_watchlists,
)

suchi_watchlist_screener_agent = LlmAgent(
    name="suchi_watchlist_screener_agent",
    model=HYDROGEN_FAST_MODEL,
    description=(
        "Screens corporate entities and UBOs against OFAC, UN, UK HMT, and "
        "Tier-1 PEP watchlists."
    ),
    instruction=CHARAKA_WATCHLIST_INSTRUCTION,
    tools=[screen_entity_and_ubos_watchlists],
    before_tool_callback=dharma_before_tool_callback,
    after_tool_callback=dharma_after_tool_callback,
)

varta_adverse_media_agent = LlmAgent(
    name="varta_adverse_media_agent",
    model=HYDROGEN_FAST_MODEL,
    description=(
        "Evaluates multilingual adverse media hits with DOB, jurisdiction, "
        "and corporate nexus filtering."
    ),
    instruction=VARTA_MEDIA_INSTRUCTION,
    tools=[evaluate_multilingual_adverse_media_relevance],
    before_tool_callback=dharma_before_tool_callback,
    after_tool_callback=dharma_after_tool_callback,
)

charaka_parallel_gather_pool = ParallelAgent(
    name="charaka_parallel_gather_pool",
    description="Concurrently runs PEP/Sanctions watchlists and adverse media checks.",
    sub_agents=[suchi_watchlist_screener_agent, varta_adverse_media_agent],
)

viveka_relevance_aggregator_agent = LlmAgent(
    name="viveka_relevance_aggregator_agent",
    model=PRO_REASONING_MODEL,
    description=(
        "Aggregates screening evidence, suppresses verified name-only false "
        "positives with explicit rationale, and escalates true/uncertain hits."
    ),
    instruction=VIVEKA_AGGREGATOR_INSTRUCTION,
    before_tool_callback=dharma_before_tool_callback,
    after_tool_callback=dharma_after_tool_callback,
)

charaka_semantic_screening_agent = SequentialAgent(
    name="charaka_semantic_screening_agent",
    description=(
        "Parallel watchlist + adverse media gathering (Hydrogen) followed by "
        "contextual false-positive discernment and prioritization (Pro)."
    ),
    sub_agents=[charaka_parallel_gather_pool, viveka_relevance_aggregator_agent],
)

# Spec-aligned alias
semantic_screening_agent = charaka_semantic_screening_agent
