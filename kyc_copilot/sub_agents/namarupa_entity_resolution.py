"""Namarupa Entity Resolution Sub-Agent (SequentialAgent on Gemini 4 Hydrogen).

Queries external corporate registries via the MCP layer and reconciles legal
name variants into a canonical CorporateGoldenRecord committed to Smriti.
"""

from __future__ import annotations

from google.adk.agents import LlmAgent, SequentialAgent

from kyc_copilot.callbacks.guardrails import (
    dharma_after_tool_callback,
    dharma_before_tool_callback,
)
from kyc_copilot.constitution import (
    HYDROGEN_FAST_MODEL,
    NAMARUPA_RESOLUTION_INSTRUCTION,
)
from kyc_copilot.tools.namarupa_entity_tools import (
    query_external_corporate_registry_mcp,
    resolve_probabilistic_entity_golden_record,
)

lekha_registry_mcp_agent = LlmAgent(
    name="lekha_registry_mcp_agent",
    model=HYDROGEN_FAST_MODEL,
    description=(
        "Queries UK Companies House, Delaware, and Cayman Islands corporate "
        "registries through the standardized MCP connector."
    ),
    instruction=NAMARUPA_RESOLUTION_INSTRUCTION,
    tools=[query_external_corporate_registry_mcp],
    before_tool_callback=dharma_before_tool_callback,
    after_tool_callback=dharma_after_tool_callback,
)

satya_golden_record_agent = LlmAgent(
    name="satya_golden_record_agent",
    model=HYDROGEN_FAST_MODEL,
    description=(
        "Normalizes naming variants via probabilistic cosine matching and "
        "commits the canonical CorporateGoldenRecord to the Smriti Digital Twin."
    ),
    instruction=NAMARUPA_RESOLUTION_INSTRUCTION,
    tools=[resolve_probabilistic_entity_golden_record],
    before_tool_callback=dharma_before_tool_callback,
    after_tool_callback=dharma_after_tool_callback,
)

namarupa_entity_resolution_agent = SequentialAgent(
    name="namarupa_entity_resolution_agent",
    description=(
        "Stage 2 Entity Resolution pipeline reconciling registry filings into "
        "a verified Digital Twin Golden Record."
    ),
    sub_agents=[lekha_registry_mcp_agent, satya_golden_record_agent],
)

# Spec-aligned alias
entity_resolution_agent = namarupa_entity_resolution_agent
