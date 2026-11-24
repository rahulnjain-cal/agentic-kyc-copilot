"""5-Case Commercial KYC Golden Evaluation Suite & ADK Topology Verification.

Executes all 5 golden evaluation scenarios in `eval/golden_dataset.json`,
validates ADK multi-agent orchestration patterns and strategic model routing
(Gemini 4 Neon / Hydrogen / Pro), verifies Stage 7 Perpetual KYC webhooks,
and checks the A2A FastAPI surface.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from google.adk.agents import LlmAgent, LoopAgent, ParallelAgent, SequentialAgent

from kyc_copilot.a2a_server import app as a2a_app
from kyc_copilot.agent import (
    kyc_app,
    kyc_root_orchestrator,
    root_agent,
    sutradhar_kyc_orchestrator,
)
from kyc_copilot.constitution import (
    HYDROGEN_FAST_MODEL,
    NEON_ORCHESTRATOR_MODEL,
    PRO_REASONING_MODEL,
)
from kyc_copilot.memory.persistent_store import (
    SmritiDigitalTwinStore,
    set_smriti_store,
)
from kyc_copilot.observability.drishti_tracing import (
    clear_recorded_spans,
    get_recorded_spans,
)
from kyc_copilot.observability.shilalekh_logger import (
    clear_recorded_logs,
    get_recorded_logs,
    get_recorded_raw_json_lines,
)
from kyc_copilot.sub_agents import (
    charaka_semantic_screening_agent,
    domain_specialist_pool,
    dvarapala_intake_rfi_agent,
    edd_qra_critic_pipeline,
    entity_resolution_agent,
    intake_and_rfi_agent,
    namarupa_entity_resolution_agent,
    pramana_edd_qra_critic_pipeline,
    semantic_screening_agent,
    trishul_domain_specialist_pool,
    ubo_and_structure_agent,
    vamsha_ubo_structure_agent,
)
from kyc_copilot.sutradhar_harness import (
    process_ckyc_monitoring_event,
    run_kyc_onboarding_pipeline,
)

GOLDEN_DATASET_PATH = Path(__file__).resolve().parents[1] / "eval" / "golden_dataset.json"
GOLDEN_CASES = {
    c["case_id"]: c
    for c in json.loads(GOLDEN_DATASET_PATH.read_text(encoding="utf-8"))["cases"]
}


@pytest.fixture(autouse=True)
def _clean_telemetry_and_store(tmp_path: Path) -> None:
    clear_recorded_logs()
    clear_recorded_spans()
    set_smriti_store(SmritiDigitalTwinStore(db_path=tmp_path / "golden_eval.sqlite3"))


def test_adk_multi_agent_topology_and_strategic_model_routing() -> None:
    """Rubric Cat 3: Verifies ADK agent hierarchy, patterns, plugins & model tiers."""
    assert root_agent is sutradhar_kyc_orchestrator
    assert kyc_root_orchestrator is sutradhar_kyc_orchestrator
    assert isinstance(root_agent, LlmAgent)
    assert root_agent.model == NEON_ORCHESTRATOR_MODEL == "gemini-4-neon"
    assert len(root_agent.sub_agents) == 6

    # Check spec aliases & ADK workflow patterns
    assert isinstance(dvarapala_intake_rfi_agent, SequentialAgent)
    assert intake_and_rfi_agent is dvarapala_intake_rfi_agent
    assert all(a.model == HYDROGEN_FAST_MODEL for a in dvarapala_intake_rfi_agent.sub_agents)

    assert isinstance(namarupa_entity_resolution_agent, SequentialAgent)
    assert entity_resolution_agent is namarupa_entity_resolution_agent
    assert all(a.model == HYDROGEN_FAST_MODEL for a in namarupa_entity_resolution_agent.sub_agents)

    assert isinstance(vamsha_ubo_structure_agent, LlmAgent)
    assert ubo_and_structure_agent is vamsha_ubo_structure_agent
    assert vamsha_ubo_structure_agent.model == PRO_REASONING_MODEL

    assert isinstance(trishul_domain_specialist_pool, ParallelAgent)
    assert domain_specialist_pool is trishul_domain_specialist_pool
    assert len(trishul_domain_specialist_pool.sub_agents) == 3
    assert all(a.model == HYDROGEN_FAST_MODEL for a in trishul_domain_specialist_pool.sub_agents)

    assert isinstance(charaka_semantic_screening_agent, SequentialAgent)
    assert semantic_screening_agent is charaka_semantic_screening_agent
    gather_pool, aggregator = charaka_semantic_screening_agent.sub_agents
    assert isinstance(gather_pool, ParallelAgent)
    assert all(a.model == HYDROGEN_FAST_MODEL for a in gather_pool.sub_agents)
    assert aggregator.model == PRO_REASONING_MODEL

    assert isinstance(pramana_edd_qra_critic_pipeline, SequentialAgent)
    assert edd_qra_critic_pipeline is pramana_edd_qra_critic_pipeline
    qa_loop, hitl_gate = pramana_edd_qra_critic_pipeline.sub_agents
    assert isinstance(qa_loop, LoopAgent)
    assert qa_loop.max_iterations == 2
    assert all(a.model == PRO_REASONING_MODEL for a in qa_loop.sub_agents)
    assert hitl_gate.model == PRO_REASONING_MODEL

    # Verify App-level History Compaction + DharmaPolicyPlugin
    assert kyc_app.events_compaction_config is not None
    assert kyc_app.events_compaction_config.token_threshold == 12000
    assert any(p.name == "dharma_kyc_policy_plugin" for p in kyc_app.plugins)


@pytest.mark.asyncio
async def test_golden_case_01_fast_track_low_risk() -> None:
    """Case 1: UK SaaS vendor auto-prepares LOW QRA with zero unnecessary RFIs."""
    case = GOLDEN_CASES["GOLDEN-CASE-01"]
    result = await run_kyc_onboarding_pipeline(
        case_id=case["case_id"],
        applicant_input=case["applicant_input"],
    )
    expected = case["expected"]

    assert result["status"] == "COMPLETED"
    assert result["golden_record"]["canonical_name"] == expected["canonical_name"]
    ubo_names = [u["full_name"] for u in result["ubo_result"]["identified_ubos"]]
    assert set(expected["expected_ubo_names"]).issubset(set(ubo_names))
    assert result["qra"]["composite_risk_score"] <= expected["max_risk_score"]
    assert result["qra"]["risk_tier"] == expected["expected_risk_tier"]
    assert result["qra"]["hitl_required"] is False
    assert result["qra"]["confidence_score"] >= expected["min_confidence"]
    assert "generate_targeted_client_rfi_outreach" not in result["tool_trace"]
    for tool_name in expected["required_tools_called"]:
        assert tool_name in result["tool_trace"]
    assert result["critique_report"]["passed"] is True


@pytest.mark.asyncio
async def test_golden_case_02_multitier_cross_border_ubo_and_voting_override() -> None:
    """Case 2: 65% DE * 50% KY = 32.5% UBO + 10% eq/51% Class-B voting override."""
    case = GOLDEN_CASES["GOLDEN-CASE-02"]
    result = await run_kyc_onboarding_pipeline(
        case_id=case["case_id"],
        applicant_input=case["applicant_input"],
    )
    expected = case["expected"]

    assert result["golden_record"]["canonical_name"] == expected["canonical_name"]
    ubos_by_name = {u["full_name"]: u for u in result["ubo_result"]["identified_ubos"]}
    assert set(expected["expected_ubo_names"]).issubset(set(ubos_by_name))

    vikramaditya = ubos_by_name["Vikramaditya Rao"]
    assert vikramaditya["effective_equity_pct"] == pytest.approx(
        expected["vikramaditya_effective_equity_pct"]
    )
    assert vikramaditya["control_mechanism"] == "INDIRECT_ROLLUP"

    chitrangada = ubos_by_name["Chitrangada Sen"]
    assert chitrangada["effective_equity_pct"] == pytest.approx(10.0)
    assert chitrangada["effective_voting_pct"] == pytest.approx(51.0)
    assert chitrangada["control_mechanism"] == expected["chitrangada_control_mechanism"]

    domains = {r["domain"] for r in result["domain_reports"]}
    assert domains == set(expected["parallel_specialists_invoked"])
    assert result["critique_report"]["passed"] is expected["citation_critique_passed"]


@pytest.mark.asyncio
async def test_golden_case_03_adverse_media_false_positive_suppression() -> None:
    """Case 3: Suppresses 'David Miller' false positive via 25-year DOB & country gap."""
    case = GOLDEN_CASES["GOLDEN-CASE-03"]
    result = await run_kyc_onboarding_pipeline(
        case_id=case["case_id"],
        applicant_input=case["applicant_input"],
    )
    expected = case["expected"]

    assert result["golden_record"]["canonical_name"] == expected["canonical_name"]
    media_alerts = result["media_alerts"]
    assert len(media_alerts) == 1
    assert media_alerts[0]["subject_name"] == expected["suppressed_false_positive_subject"]
    assert media_alerts[0]["semantic_disposition"] == expected["expected_disposition"]
    assert "25-year" in media_alerts[0]["suppression_or_escalation_rationale"]
    assert result["qra"]["composite_risk_score"] <= expected["max_risk_score"]
    assert result["qra"]["risk_tier"] == expected["expected_risk_tier"]
    assert result["qra"]["hitl_required"] is False


@pytest.mark.asyncio
async def test_golden_case_04_intake_dropout_prevention_and_targeted_rfi() -> None:
    """Case 4: Silent pre-fill runs first; RFI asks ONLY for expired PoA & missing nationality."""
    case = GOLDEN_CASES["GOLDEN-CASE-04"]
    result = await run_kyc_onboarding_pipeline(
        case_id=case["case_id"],
        applicant_input=case["applicant_input"],
    )
    expected = case["expected"]

    assert result["doc_assessment"]["status"] == expected["doc_status"]
    assert result["status"] == expected["session_state"]
    assert result["edd_halted"] is expected["edd_halted"]
    for field_name in expected["silent_lookup_prefilled_fields"]:
        assert field_name in result["silent_prefilled_fields"]
    rfi_fields = result["rfi_envelope"]["data"]["requested_fields"]
    assert set(rfi_fields) == set(expected["rfi_requested_fields"])


@pytest.mark.asyncio
async def test_golden_case_05_high_risk_pep_sanctions_pii_redaction_and_hitl_stop() -> None:
    """Case 5: Scores >=85 HIGH_EDD, scrubs PII from logs, verifies citations, halts at HITL."""
    case = GOLDEN_CASES["GOLDEN-CASE-05"]
    result = await run_kyc_onboarding_pipeline(
        case_id=case["case_id"],
        applicant_input=case["applicant_input"],
    )
    expected = case["expected"]

    assert result["qra"]["composite_risk_score"] >= expected["min_risk_score"]
    assert result["qra"]["risk_tier"] == expected["expected_risk_tier"]
    assert result["ubo_result"]["opaque_layer_detected"] is expected["opaque_layer_detected"]
    assert result["qra"]["hitl_required"] is expected["hitl_required"]
    assert result["status"] == expected["hitl_status"]
    assert result["hitl_envelope"]["status"] == "BLOCKED_HITL"
    assert result["critique_report"]["passed"] is expected["citation_critique_passed"]

    # Observability assertions: valid JSON logs, paired intent/outcome, OTel spans, zero PII leak
    raw_logs = get_recorded_raw_json_lines()
    assert len(raw_logs) >= 10
    combined_log_text = "\n".join(raw_logs)
    for raw_pii_value in expected["pii_must_not_appear_in_logs"]:
        assert raw_pii_value not in combined_log_text, f"Raw PII leaked: {raw_pii_value}"

    parsed_events = [row["event"] for row in get_recorded_logs()]
    assert parsed_events.count("tool_execution_intent") >= 8
    assert parsed_events.count("tool_execution_outcome") >= 8

    spans = get_recorded_spans()
    assert any(s.name == "orchestrator.sutradhar_kyc_orchestrator" for s in spans)
    assert any(s.name == "tool.submit_high_risk_case_for_checker_signoff" for s in spans)

    # Confirm explicit KYC Checker confirmation unblocks finalization & registers cKYC watch
    approved = await run_kyc_onboarding_pipeline(
        case_id=case["case_id"],
        applicant_input=case["applicant_input"],
        checker_token="CHECKER-SIGNOFF-TOKEN",
        checker_decision="ESCALATE_SAR",
    )
    assert approved["status"] == "COMPLETED"
    assert approved["hitl_envelope"]["data"]["checker_decision"] == "ESCALATE_SAR"
    assert approved["hitl_envelope"]["data"]["ckyc_watch_registered"] is True


def test_stage_7_ckyc_webhook_and_a2a_fastapi_surface() -> None:
    """Verifies Stage 7 Perpetual KYC materiality classification & A2A FastAPI routes."""
    non_material = process_ckyc_monitoring_event(
        {
            "event_id": "EVT-001",
            "entity_id": "ENT-TAKSHASHILA-001",
            "event_source": "REGISTRY_FILING_CHANGE",
            "change_summary": "Registered street formatting updated from Rd to Road",
        }
    )
    assert non_material["is_material"] is False
    assert non_material["action_taken"] == "AUTO_LOGGED_NON_MATERIAL"

    material = process_ckyc_monitoring_event(
        {
            "event_id": "EVT-002",
            "entity_id": "ENT-NALANDA-002",
            "event_source": "REGISTRY_FILING_CHANGE",
            "change_summary": "New offshore beneficial owner acquired 30% voting stake",
            "new_ubo_pct": 30.0,
        }
    )
    assert material["is_material"] is True
    assert material["action_taken"] == "RETRIGGERED_STAGES_3_TO_6"

    client = TestClient(a2a_app)
    health = client.get("/health")
    assert health.status_code == 200
    assert health.json()["orchestrator_model"] == "gemini-4-neon"

    webhook = client.post(
        "/webhooks/ckyc-event",
        json={
            "event_id": "EVT-003",
            "entity_id": "ENT-KAUTILYA-005",
            "event_source": "TRANSACTION_ANOMALY_SPIKE",
            "change_summary": "90d wire spike of 250%",
            "cash_wire_spike_pct": 250.0,
        },
    )
    assert webhook.status_code == 200
    assert webhook.json()["action_taken"] == "RETRIGGERED_STAGES_3_TO_6"
