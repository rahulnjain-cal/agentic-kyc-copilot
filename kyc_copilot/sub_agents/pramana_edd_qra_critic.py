"""Pramana EDD QRA & Nyaya Citation Critique Pipeline (Sequential + Loop in Pro).

Implements the 3-stage quality assurance pattern from the technical blueprint:
1. Artha EDD Drafter (Policy RAG + 90-day transactions -> draft QRA & CRO brief)
2. Nyaya Citation Critic (verifies 100% [snapshot:<id> | source:<uri>] coverage
   and UBO math consistency, looping up to 2 times to remediate gaps)
3. Sabha Mandatory HITL Gate (hard stop when risk_score >= 70 or EDD flags fire)
"""

from __future__ import annotations

from google.adk.agents import LlmAgent, LoopAgent, SequentialAgent

from kyc_copilot.callbacks.guardrails import (
    dharma_after_tool_callback,
    dharma_before_tool_callback,
)
from kyc_copilot.constitution import (
    ARTHA_EDD_DRAFTER_INSTRUCTION,
    NYAYA_CRITIC_INSTRUCTION,
    PRO_REASONING_MODEL,
    SABHA_HITL_INSTRUCTION,
)
from kyc_copilot.tools.pramana_edd_hitl_tools import (
    audit_profile_against_transactions_and_policy_rag,
    submit_high_risk_case_for_checker_signoff,
)

artha_edd_drafter_agent = LlmAgent(
    name="artha_edd_drafter_agent",
    model=PRO_REASONING_MODEL,
    description=(
        "Audits 90-day transactions against bank Policy RAG and drafts the "
        "cited Analyst QRA narrative and CRO 1-page Executive Summary."
    ),
    instruction=ARTHA_EDD_DRAFTER_INSTRUCTION,
    tools=[audit_profile_against_transactions_and_policy_rag],
    before_tool_callback=dharma_before_tool_callback,
    after_tool_callback=dharma_after_tool_callback,
)

nyaya_citation_critic_agent = LlmAgent(
    name="nyaya_citation_critic_agent",
    model=PRO_REASONING_MODEL,
    description=(
        "Source Citation Critique agent inspecting every QRA claim against "
        "recorded snapshot IDs and deterministic UBO ownership math."
    ),
    instruction=NYAYA_CRITIC_INSTRUCTION,
    before_tool_callback=dharma_before_tool_callback,
    after_tool_callback=dharma_after_tool_callback,
)

nyaya_qa_critique_loop = LoopAgent(
    name="nyaya_qa_critique_loop",
    description="Up-to-2-iteration QRA drafting and source-citation critique loop.",
    sub_agents=[artha_edd_drafter_agent, nyaya_citation_critic_agent],
    max_iterations=2,
)

sabha_hitl_gate_agent = LlmAgent(
    name="sabha_hitl_gate_agent",
    model=PRO_REASONING_MODEL,
    description=(
        "Mandatory Human-in-the-Loop approval gate halting high-risk cases "
        "(risk_score >= 70) until KYC Checker sign-off is provided."
    ),
    instruction=SABHA_HITL_INSTRUCTION,
    tools=[submit_high_risk_case_for_checker_signoff],
    before_tool_callback=dharma_before_tool_callback,
    after_tool_callback=dharma_after_tool_callback,
)

pramana_edd_qra_critic_pipeline = SequentialAgent(
    name="pramana_edd_qra_critic_pipeline",
    description=(
        "Stage 4-6 EDD synthesis, Policy RAG audit, Nyaya source-citation "
        "critique loop, and Sabha mandatory HITL Checker sign-off gate."
    ),
    sub_agents=[nyaya_qa_critique_loop, sabha_hitl_gate_agent],
)

# Spec-aligned alias
edd_qra_critic_pipeline = pramana_edd_qra_critic_pipeline
