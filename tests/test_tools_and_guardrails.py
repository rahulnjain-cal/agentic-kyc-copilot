"""Unit tests covering Tools, Schemas, Guided Errors, Memory, Compaction,
Async Consolidation, PII Redaction, Structured Logging, Tracing, and Secrets.
"""

from __future__ import annotations

import inspect
import json
from pathlib import Path

import pytest

from kyc_copilot.callbacks.guardrails import (
    evaluate_sabha_hitl_triggers,
    record_tool_intent,
    record_tool_outcome,
    verify_pramana_citations,
)
from kyc_copilot.callbacks.kavach_pii_redactor import (
    KavachPiiRedactor,
    redact_pii,
    redact_pii_in_structure,
)
from kyc_copilot.config.mudra_secrets import MudraSecretVault
from kyc_copilot.memory.async_consolidator import VayuAsyncMemoryConsolidator
from kyc_copilot.memory.compaction import (
    SankshepaHistoryCompactor,
    build_adk_compaction_config,
)
from kyc_copilot.memory.persistent_store import (
    ArthashastraPolicyRag,
    SmritiDigitalTwinStore,
    set_smriti_store,
)
from kyc_copilot.models.schemas import CorporateGoldenRecord
from kyc_copilot.observability.drishti_tracing import (
    clear_recorded_spans,
    get_recorded_spans,
    traced_span,
)
from kyc_copilot.observability.shilalekh_logger import (
    clear_recorded_logs,
    get_recorded_logs,
    get_recorded_raw_json_lines,
)
from kyc_copilot.tools import (
    ALL_TEN_KYC_TOOLS,
    assess_uploaded_document_quality_and_classify,
    audit_profile_against_transactions_and_policy_rag,
    calculate_cascading_ubo_ownership_rollup,
    evaluate_multilingual_adverse_media_relevance,
    execute_silent_entity_pre_lookup,
    generate_targeted_client_rfi_outreach,
    query_external_corporate_registry_mcp,
    resolve_probabilistic_entity_golden_record,
    screen_entity_and_ubos_watchlists,
    submit_high_risk_case_for_checker_signoff,
)


@pytest.fixture()
def isolated_smriti_store(tmp_path: Path) -> SmritiDigitalTwinStore:
    store = SmritiDigitalTwinStore(db_path=tmp_path / "test_smriti.sqlite3")
    set_smriti_store(store)
    return store


def test_all_ten_tools_have_verb_specific_names_and_google_docstrings() -> None:
    """Rubric Cat 1: All 10 tools have verb-specific names & Google-style docstrings."""
    assert len(ALL_TEN_KYC_TOOLS) == 10
    expected_verbs = {
        "assess",
        "execute",
        "query",
        "resolve",
        "calculate",
        "screen",
        "evaluate",
        "audit",
        "generate",
        "submit",
    }
    for fn in ALL_TEN_KYC_TOOLS:
        first_word = fn.__name__.split("_")[0]
        assert first_word in expected_verbs, f"{fn.__name__} must start with a clear verb"
        doc = inspect.getdoc(fn) or ""
        assert "Args:" in doc and "Returns:" in doc, f"{fn.__name__} missing Google docstring"


def test_guided_error_recovery_across_malformed_and_ambiguous_inputs(
    isolated_smriti_store: SmritiDigitalTwinStore,
) -> None:
    """Rubric Cat 1: Guided ToolResultEnvelope recovery payloads without crashes."""
    # 1. Blurry/expired document triggers RFI instruction
    bad_doc = assess_uploaded_document_quality_and_classify(
        case_id="UNIT-01",
        document_id="DOC-BAD",
        document_type="PROOF_OF_ADDRESS",
        dpi=90,
        blur_score=0.6,
        age_days=120,
        expected_entity_name="Takshashila Cloud Systems Ltd",
        entity_name_on_doc="Takshashila Cloud Systems Ltd",
    )
    assert bad_doc["status"] == "RECOVERABLE_ERROR"
    assert "generate_targeted_client_rfi_outreach" in bad_doc["recovery_instruction"]

    # 2. Malformed Pydantic input never throws unhandled exception
    invalid_doc = assess_uploaded_document_quality_and_classify(
        case_id="X",  # too short (<3)
        document_id="D",
        document_type="UNKNOWN_TYPE",
        dpi=5,
        blur_score=2.0,
        age_days=-5,
        expected_entity_name="A",
        entity_name_on_doc="B",
    )
    assert invalid_doc["status"] == "RECOVERABLE_ERROR"
    assert invalid_doc["recovery_instruction"] is not None

    # 3. Unknown CRM entity returns PARTIAL_MATCH pointing to external registry MCP
    silent_miss = execute_silent_entity_pre_lookup(
        case_id="UNIT-02",
        submitted_name="Unseen Startup Ltd",
        registration_number="UK-00000000",
        jurisdiction_iso="GB",
    )
    assert silent_miss["status"] == "PARTIAL_MATCH"
    assert "query_external_corporate_registry_mcp" in silent_miss["recovery_instruction"]

    # 4. Ambiguous legal name ("Chola Global Holdings") returns candidate list + hint
    ambiguous = query_external_corporate_registry_mcp(
        case_id="UNIT-03",
        legal_name="Chola Global Holdings",
        jurisdiction_iso="GB",
    )
    assert ambiguous["status"] == "PARTIAL_MATCH"
    assert len(ambiguous["data"]["ambiguous_candidates"]) == 2
    assert "registration_number" in ambiguous["recovery_instruction"]

    # 5. Borderline entity match (0.65 - 0.85) guides Legal Skill cross-check
    borderline = resolve_probabilistic_entity_golden_record(
        case_id="UNIT-04",
        submitted_name="Takshashila Cloud Services Ltd",
        candidates=[
            {
                "entity_id": "ENT-TAKSHASHILA-001",
                "legal_name": "Takshashila Cloud Systems Ltd",
                "aliases": [],
                "registration_number": "UK-11204588",
                "jurisdiction_iso": "GB",
                "incorporation_date": "2021-03-14",
                "registered_address": "22 Bishopsgate, London",
                "sic_codes": ["62012"],
                "source_snapshot_id": "SNAP-REG-TEST",
            }
        ],
    )
    assert borderline["status"] == "PARTIAL_MATCH"
    assert "Legal Skill" in borderline["recovery_instruction"]

    # 6. Watchlist timeout returns partial status & never marks CLEAR
    wl_timeout = screen_entity_and_ubos_watchlists(
        case_id="UNIT-05",
        subjects=[
            {
                "subject_id": "SUB-1",
                "full_name": "Arjun Mehta",
                "aliases": ["__SIMULATE_TIMEOUT__"],
            }
        ],
    )
    assert wl_timeout["status"] == "PARTIAL_MATCH"
    assert wl_timeout["data"]["screening_complete"] is False
    assert "UNVERIFIED" in wl_timeout["recovery_instruction"]

    # 7. Common-name adverse media without DOB/company nexus never auto-suppresses
    uncertain_media = evaluate_multilingual_adverse_media_relevance(
        case_id="UNIT-06",
        subjects=[
            {
                "subject_id": "SUB-2",
                "full_name": "Sanjay Verma",
                "dob": "1985-05-05",
                "jurisdiction_iso": "GB",
            }
        ],
    )
    assert uncertain_media["status"] == "PARTIAL_MATCH"
    assert uncertain_media["data"]["alerts"][0]["semantic_disposition"] == "POTENTIAL_MATCH_NEEDS_REVIEW"
    assert "Do not auto-suppress" in uncertain_media["recovery_instruction"]

    # 8. New prospect without 90d transactions uses projected turnover baseline
    new_prospect = audit_profile_against_transactions_and_policy_rag(
        case_id="UNIT-07",
        entity_id="ENT-ASHOKA-004",
        jurisdiction_iso="GB",
        sic_codes=["64999"],
        projected_annual_turnover_gbp=1_500_000.0,
    )
    assert new_prospect["status"] == "SUCCESS"
    assert new_prospect["data"]["expected_volume_baseline_only"] is True
    assert "projected turnover" in new_prospect["recovery_instruction"]

    # 9. Duplicate RFI rejected when field already verified in Digital Twin
    isolated_smriti_store.upsert_golden_record(
        CorporateGoldenRecord(
            entity_id="ENT-DUP-CHECK",
            canonical_name="Vedic Analytics Ltd",
            registration_number="UK-88881111",
            jurisdiction_iso="GB",
            incorporation_date="2020-01-01",
            registered_address="1 Lombard St, London",
            sic_codes=["62020"],
            match_confidence=0.98,
            source_snapshot_ids=["SNAP-REG-VERIFIED"],
        )
    )
    dup_rfi = generate_targeted_client_rfi_outreach(
        case_id="UNIT-08",
        entity_id="ENT-DUP-CHECK",
        requested_fields=["incorporation_date"],
        reason="Confirm incorporation date",
    )
    assert dup_rfi["status"] == "RECOVERABLE_ERROR"
    assert "already verified" in dup_rfi["recovery_instruction"]


def test_deterministic_ubo_calculator_cycles_overflow_and_smo_fallback() -> None:
    """Verifies Vamsha deterministic UBO math handles loops, >100%, and SMO fallback."""
    # Circular loop: A -> B -> A
    circular = calculate_cascading_ubo_ownership_rollup(
        case_id="UBO-CYC",
        target_entity_id="ENT-A",
        edges=[
            {
                "parent_id": "ENT-B",
                "parent_name": "B Holdings",
                "parent_type": "CORPORATE",
                "child_id": "ENT-A",
                "equity_pct": 60.0,
                "voting_pct": 60.0,
            },
            {
                "parent_id": "ENT-A",
                "parent_name": "A Operating",
                "parent_type": "CORPORATE",
                "child_id": "ENT-B",
                "equity_pct": 60.0,
                "voting_pct": 60.0,
            },
        ],
    )
    assert circular["status"] == "RECOVERABLE_ERROR"
    assert circular["data"]["opaque_layer_detected"] is True
    assert set(circular["data"]["offending_node_ids"]) == {"ENT-A", "ENT-B"}
    assert "opaque_layer_detected=True" in circular["recovery_instruction"]

    # Sum > 100%
    overflow = calculate_cascading_ubo_ownership_rollup(
        case_id="UBO-OVER",
        target_entity_id="ENT-X",
        edges=[
            {
                "parent_id": "IND-1",
                "parent_name": "Owner One",
                "parent_type": "INDIVIDUAL",
                "child_id": "ENT-X",
                "equity_pct": 70.0,
                "voting_pct": 70.0,
            },
            {
                "parent_id": "IND-2",
                "parent_name": "Owner Two",
                "parent_type": "INDIVIDUAL",
                "child_id": "ENT-X",
                "equity_pct": 50.0,
                "voting_pct": 50.0,
            },
        ],
    )
    assert overflow["status"] == "RECOVERABLE_ERROR"
    assert "ENT-X" in overflow["data"]["offending_node_ids"]

    # Dispersed <25% ownership -> Senior Managing Official fallback
    dispersed = calculate_cascading_ubo_ownership_rollup(
        case_id="UBO-SMO",
        target_entity_id="ENT-DISP",
        senior_managing_official_name="Siddharth Nair",
        edges=[
            {
                "parent_id": f"IND-{i}",
                "parent_name": f"Shareholder {i}",
                "parent_type": "INDIVIDUAL",
                "child_id": "ENT-DISP",
                "equity_pct": 20.0,
                "voting_pct": 20.0,
            }
            for i in range(5)
        ],
    )
    assert dispersed["status"] == "SUCCESS"
    assert len(dispersed["data"]["identified_ubos"]) == 1
    assert dispersed["data"]["identified_ubos"][0]["control_mechanism"] == "SENIOR_MANAGING_OFFICIAL"
    assert dispersed["data"]["identified_ubos"][0]["full_name"] == "Siddharth Nair"


def test_history_compaction_over_12k_tokens_preserves_all_snapshot_ids() -> None:
    """Rubric Cat 2: Compacts >12k token histories while preserving every snapshot_id."""
    adk_cfg = build_adk_compaction_config()
    assert adk_cfg.token_threshold == 12000

    compactor = SankshepaHistoryCompactor(token_threshold=12000, keep_recent_events=2)
    verbose_events = [
        {
            "role": "tool",
            "tool_name": f"tool_step_{i}",
            "status": "SUCCESS",
            "snapshot_id": f"SNAP-HIST-{i:03d}",
            "raw_filing": "A" * 10000,  # ~2500 tokens each -> >20k tokens total
        }
        for i in range(8)
    ]
    compacted, was_compacted = compactor.compact_history(verbose_events)
    assert was_compacted is True
    assert len(compacted) == 3  # 1 summary event + 2 recent events
    preserved = compacted[0]["preserved_snapshot_ids"]
    for i in range(6):
        assert f"SNAP-HIST-{i:03d}" in preserved


@pytest.mark.asyncio
async def test_async_memory_consolidation_and_cross_turn_persistence(
    tmp_path: Path,
) -> None:
    """Rubric Cat 2: Non-blocking asyncio memory writes persist across turns in SQLite."""
    db_file = tmp_path / "cross_turn.sqlite3"
    store_turn_1 = SmritiDigitalTwinStore(db_path=db_file)
    consolidator = VayuAsyncMemoryConsolidator(store=store_turn_1)

    record = CorporateGoldenRecord(
        entity_id="ENT-PERSIST-01",
        canonical_name="Gupta Quantum Systems Ltd",
        registration_number="UK-77770001",
        jurisdiction_iso="GB",
        incorporation_date="2022-01-10",
        registered_address="10 Downing Way, London",
        sic_codes=["62012"],
        match_confidence=0.96,
        source_snapshot_ids=["SNAP-PERSIST-1"],
    )
    task1 = consolidator.enqueue_golden_record_update(record, case_id="CASE-TURN-1")
    task2 = consolidator.enqueue_snapshot_consolidation(
        snapshot_id="SNAP-PERSIST-1",
        case_id="CASE-TURN-1",
        tool_name="resolve_probabilistic_entity_golden_record",
        source_uri="tool://resolve",
        payload={"contact": "Owner DOB 1980-03-15 Passport XY1234567"},
    )
    assert task1 is not None and task2 is not None
    flushed = await consolidator.flush()
    assert flushed >= 2

    # Turn 2: fresh store instance reads persisted Digital Twin & redacted snapshot
    store_turn_2 = SmritiDigitalTwinStore(db_path=db_file)
    loaded = store_turn_2.get_golden_record("ENT-PERSIST-01")
    assert loaded is not None
    assert loaded.canonical_name == "Gupta Quantum Systems Ltd"

    snapshots = store_turn_2.list_case_snapshots("CASE-TURN-1")
    assert len(snapshots) == 1
    serialized = json.dumps(snapshots[0]["payload"])
    assert "XY1234567" not in serialized
    assert "1980-03-15" not in serialized
    assert "[REDACTED_PASSPORT]" in serialized


def test_policy_rag_retrieves_relevant_governance_rules() -> None:
    """Verifies local vector Policy RAG matches bearer-share and trust rules."""
    rag = ArthashastraPolicyRag()
    hits = rag.query_policy("prohibition of bearer shares and offshore discretionary trust", top_k=3)
    rule_ids = {h["rule_id"] for h in hits}
    assert "POL-BEARER-03" in rule_ids or "POL-TRUST-02" in rule_ids


def test_kavach_pii_redaction_structured_json_logs_and_otel_spans() -> None:
    """Rubric Cat 4: Valid JSON logs, paired intent/outcome, OTel spans, zero PII leak."""
    clear_recorded_logs()
    clear_recorded_spans()

    raw_pii = (
        "Passport AB1234567 NINo QQ123456C SSN 123-45-6789 DOB 1975-06-20 "
        "email exec@example.co.uk IBAN GB29NWBK60161331926819"
    )
    scrubbed = redact_pii(raw_pii)
    for secret in ("AB1234567", "QQ123456C", "123-45-6789", "1975-06-20", "exec@example.co.uk", "GB29NWBK60161331926819"):
        assert secret not in scrubbed
    assert "[REDACTED_PASSPORT]" in scrubbed
    assert "[REDACTED_TAX_ID]" in scrubbed
    assert "[REDACTED_DOB]" in scrubbed
    assert "[REDACTED_EMAIL]" in scrubbed
    assert "[REDACTED_IBAN]" in scrubbed

    nested_scrubbed = redact_pii_in_structure({"residential_address": "12 Baker St", "dob": "1982-01-01"})
    assert nested_scrubbed["residential_address"] == "[REDACTED_ADDRESS]"
    assert nested_scrubbed["dob"] == "[REDACTED_DOB]"

    with traced_span("test.root_kyc_turn", {"kyc.case_id": "OBS-01"}):
        inv_key = record_tool_intent(
            tool_name="assess_uploaded_document_quality_and_classify",
            tool_args={"case_id": "OBS-01", "note": raw_pii},
            case_id="OBS-01",
            agent_name="chitra_doc_intake_agent",
            model_id="gemini-4-hydrogen",
        )
        record_tool_outcome(
            invocation_key=inv_key,
            tool_name="assess_uploaded_document_quality_and_classify",
            tool_response={"status": "SUCCESS", "snapshot_id": "SNAP-OBS-1"},
            case_id="OBS-01",
            agent_name="chitra_doc_intake_agent",
            model_id="gemini-4-hydrogen",
            persist_async=False,
        )

    raw_lines = get_recorded_raw_json_lines()
    assert len(raw_lines) >= 2
    for line in raw_lines:
        parsed = json.loads(line)  # Must be strict valid JSON
        assert "trace_id" in parsed and "span_id" in parsed
        assert "AB1234567" not in line
        assert "GB29NWBK60161331926819" not in line

    events = [entry["event"] for entry in get_recorded_logs()]
    assert "tool_execution_intent" in events
    assert "tool_execution_outcome" in events

    span_names = [s.name for s in get_recorded_spans()]
    assert "tool.assess_uploaded_document_quality_and_classify" in span_names
    assert "test.root_kyc_turn" in span_names


def test_citation_critique_self_eval_and_secret_manager_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verifies Nyaya citation self-eval catches missing citations and Mudra uses env fallback."""
    good_text = "- Vikramaditya Rao owns 32.5% [snapshot:SNAP-UBO-1 | source:tool://ubo]."
    good_check = verify_pramana_citations(
        narrative=good_text,
        recorded_snapshot_ids={"SNAP-UBO-1"},
        expected_ubo_percentages={"Vikramaditya Rao": 32.5},
    )
    assert good_check["passed"] is True

    bad_text = "- Vikramaditya Rao owns 40.0% without any snapshot reference."
    bad_check = verify_pramana_citations(
        narrative=bad_text,
        recorded_snapshot_ids={"SNAP-UBO-1"},
        expected_ubo_percentages={"Vikramaditya Rao": 32.5},
    )
    assert bad_check["passed"] is False
    assert len(bad_check["issues"]) >= 1

    hitl_flag, reasons = evaluate_sabha_hitl_triggers(
        composite_risk_score=70,
        risk_tier="HIGH_EDD",
        confidence_score=0.90,
    )
    assert hitl_flag is True
    assert any("70" in r for r in reasons)

    monkeypatch.setenv("TEST_MUDRA_TOKEN", "ephemeral-ci-token")
    vault = MudraSecretVault(enable_secret_manager=False)
    assert vault.get_secret("kyc-test-secret", env_fallback="TEST_MUDRA_TOKEN") == "ephemeral-ci-token"

    # Confirm KavachPiiRedactor works cleanly with DLP disabled
    redactor = KavachPiiRedactor(enable_cloud_dlp=False)
    assert "[REDACTED_EMAIL]" in redactor.redact_text("contact compliance@bank.co.uk")
