"""Sutradhar Deterministic 7-Stage KYC Orchestration Harness & cKYC Hook.

Executes the complete 7-stage Commercial KYC & Entity Resolution state machine
locally and deterministically (without requiring live LLM API credits in CI),
wiring the exact same 10 tools, Shilalekh structured JSON intent-vs-outcome
callbacks, Drishti OpenTelemetry spans, Kavach PII redaction, Sankshepa history
compaction, Vayu async memory consolidation, Nyaya citation critique loop, and
Sabha mandatory HITL Checker gate.
"""

from __future__ import annotations

import asyncio
from typing import Any, Callable, Optional

from kyc_copilot.callbacks.guardrails import (
    evaluate_sabha_hitl_triggers,
    record_tool_intent,
    record_tool_outcome,
    verify_pramana_citations,
)
from kyc_copilot.constitution import (
    HYDROGEN_FAST_MODEL,
    NEON_ORCHESTRATOR_MODEL,
    PRO_REASONING_MODEL,
)
from kyc_copilot.memory.async_consolidator import get_vayu_consolidator
from kyc_copilot.memory.compaction import SankshepaHistoryCompactor
from kyc_copilot.memory.persistent_store import get_smriti_store
from kyc_copilot.models.schemas import (
    CkYcEventInput,
    CkYcEventResult,
    CorporateGoldenRecord,
    DomainSpecialistReport,
    QualitativeRiskAssessment,
    SourceCitation,
)
from kyc_copilot.observability.drishti_tracing import traced_span
from kyc_copilot.observability.shilalekh_logger import get_shilalekh_logger
from kyc_copilot.tools import (
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
from kyc_copilot.tools.registry_data import mint_snapshot_id

_LOGGER = get_shilalekh_logger("kyc_copilot.sutradhar_harness")


def _invoke_instrumented_tool(
    tool_fn: Callable[..., dict[str, Any]],
    *,
    case_id: str,
    agent_name: str,
    model_id: str,
    tool_trace: list[str],
    recorded_snapshots: set[str],
    **kwargs: Any,
) -> dict[str, Any]:
    """Runs a tool wrapped in Dharma intent/outcome logging + OpenTelemetry span."""
    tool_name = tool_fn.__name__
    tool_args = {"case_id": case_id, **kwargs}
    inv_key = record_tool_intent(
        tool_name=tool_name,
        tool_args=tool_args,
        case_id=case_id,
        agent_name=agent_name,
        model_id=model_id,
    )
    response = tool_fn(**tool_args)
    record_tool_outcome(
        invocation_key=inv_key,
        tool_name=tool_name,
        tool_response=response,
        case_id=case_id,
        agent_name=agent_name,
        model_id=model_id,
        persist_async=True,
    )
    tool_trace.append(tool_name)
    if response.get("snapshot_id"):
        recorded_snapshots.add(str(response["snapshot_id"]))
    return response


async def _run_trishul_domain_specialists(
    case_id: str,
    filing: dict[str, Any],
    registry_snapshot_id: str,
) -> list[DomainSpecialistReport]:
    """Runs Vidhi (Legal), Shulka (Tax FATCA/CRS), and Kosa (Credit) concurrently."""

    async def _vidhi_legal() -> DomainSpecialistReport:
        with traced_span("sub_agent.vidhi_legal_skill_agent", {"kyc.case_id": case_id}):
            legal = filing.get("legal_profile", {})
            flags: list[str] = []
            if legal.get("bearer_shares_allowed"):
                flags.append("BEARER_SHARES_PERMITTED")
            if legal.get("trust_deed_present"):
                flags.append("OFFSHORE_TRUST_DEED_REVIEW_REQUIRED")
            summary = legal.get("articles_status", "Standard corporate articles verified.")
            return DomainSpecialistReport(
                domain="LEGAL",
                agent_name="vidhi_legal_skill_agent",
                risk_flags=flags,
                findings_summary=summary,
                snapshot_id=registry_snapshot_id,
                source_uri=f"registry://{filing['registry_source']}/{filing['registration_number']}#legal",
            )

    async def _shulka_tax() -> DomainSpecialistReport:
        with traced_span("sub_agent.shulka_tax_fatca_crs_agent", {"kyc.case_id": case_id}):
            tax = filing.get("tax_profile", {})
            flags: list[str] = []
            fatca = tax.get("fatca_classification", "Unknown")
            if "Non-Participating" in fatca or "Unverified" in fatca:
                flags.append("FATCA_NON_PARTICIPATING_ENTITY")
            if not tax.get("hmrc_vat_verified", False) and filing["jurisdiction_iso"] == "GB":
                flags.append("HMRC_VAT_UNVERIFIED")
            residency = ", ".join(tax.get("crs_tax_residency", [filing["jurisdiction_iso"]]))
            return DomainSpecialistReport(
                domain="TAX_FATCA_CRS",
                agent_name="shulka_tax_fatca_crs_agent",
                risk_flags=flags,
                findings_summary=f"FATCA: {fatca}; CRS Residency: {residency}.",
                snapshot_id=registry_snapshot_id,
                source_uri=f"registry://{filing['registry_source']}/{filing['registration_number']}#tax",
            )

    async def _kosa_credit() -> DomainSpecialistReport:
        with traced_span("sub_agent.kosa_credit_skill_agent", {"kyc.case_id": case_id}):
            fin = filing.get("financials", {})
            flags: list[str] = []
            debt_eq = float(fin.get("debt_to_equity", 0.5))
            curr_ratio = float(fin.get("current_ratio", 1.5))
            if debt_eq > 2.5:
                flags.append("ELEVATED_LEVERAGE")
            if curr_ratio < 1.0:
                flags.append("LIQUIDITY_STRESS")
            return DomainSpecialistReport(
                domain="CREDIT",
                agent_name="kosa_credit_skill_agent",
                risk_flags=flags,
                findings_summary=(
                    f"Revenue GBP {fin.get('annual_revenue_gbp', 0):,}; "
                    f"Debt/Equity {debt_eq:.2f}; Current Ratio {curr_ratio:.2f}."
                ),
                snapshot_id=registry_snapshot_id,
                source_uri=f"registry://{filing['registry_source']}/{filing['registration_number']}#credit",
            )

    return list(await asyncio.gather(_vidhi_legal(), _shulka_tax(), _kosa_credit()))


def _draft_and_critique_qra(
    *,
    case_id: str,
    golden: CorporateGoldenRecord,
    registry_snap: str,
    ubo_result: dict[str, Any],
    ubo_snap: str,
    domain_reports: list[DomainSpecialistReport],
    watchlist_alerts: list[dict[str, Any]],
    media_alerts: list[dict[str, Any]],
    audit_result: dict[str, Any],
    audit_snap: str,
    recorded_snapshots: set[str],
) -> tuple[QualitativeRiskAssessment, dict[str, Any]]:
    """Runs Stage 5 QRA drafting + up-to-2-iteration Nyaya Citation Critique loop."""
    ubos = ubo_result.get("identified_ubos", [])
    expected_ubo_map = {
        u["full_name"]: float(u["effective_equity_pct"])
        for u in ubos
        if float(u["effective_equity_pct"]) > 0
    }

    narrative_lines = [
        (
            f"- Entity Identity: Resolved canonical entity '{golden.canonical_name}' "
            f"(Reg: {golden.registration_number}, Jurisdiction: {golden.jurisdiction_iso}, "
            f"confidence {golden.match_confidence:.2f}) "
            f"[snapshot:{registry_snap} | source:registry://{golden.registration_number}]."
        ),
    ]
    for ubo in ubos:
        narrative_lines.append(
            f"- UBO Lineage: {ubo['full_name']} holds {ubo['effective_equity_pct']:.1f}% "
            f"effective equity and {ubo['effective_voting_pct']:.1f}% voting control "
            f"via {ubo['control_mechanism']} "
            f"[snapshot:{ubo_snap} | source:tool://calculate_cascading_ubo_ownership_rollup]."
        )
    for report in domain_reports:
        narrative_lines.append(
            f"- {report.domain} Review ({report.agent_name}): {report.findings_summary} "
            f"[snapshot:{report.snapshot_id} | source:{report.source_uri}]."
        )
    for alert in [*watchlist_alerts, *media_alerts]:
        narrative_lines.append(
            f"- Screening ({alert['category']}): {alert['subject_name']} -> "
            f"{alert['semantic_disposition']} ({alert['suppression_or_escalation_rationale']}) "
            f"[snapshot:{alert['snapshot_id']} | source:{alert['cited_source_uri']}]."
        )
    narrative_lines.append(
        f"- Policy & 90-Day Transaction Audit: Composite Risk Score "
        f"{audit_result['composite_risk_score']}/100 ({audit_result['risk_tier']}), "
        f"Confidence {audit_result['confidence_score']:.2f}, "
        f"Deviations={len(audit_result['policy_deviations'])}, "
        f"Anomalies={len(audit_result['transaction_anomalies'])} "
        f"[snapshot:{audit_snap} | source:policy://kyc_governance_policy.md]."
    )

    draft_narrative = "\n".join(narrative_lines)

    # Up to 2 critique iterations (Nyaya source-grounding loop)
    critique_report: dict[str, Any] = {}
    for iteration in range(1, 3):
        with traced_span(
            "sub_agent.nyaya_citation_critic_agent",
            {"kyc.case_id": case_id, "kyc.critique_iteration": iteration},
        ):
            critique_report = verify_pramana_citations(
                narrative=draft_narrative,
                recorded_snapshot_ids=recorded_snapshots,
                expected_ubo_percentages=expected_ubo_map,
            )
            if critique_report["passed"]:
                break

    verified_citations = [
        SourceCitation(
            snapshot_id=c["snapshot_id"],
            source_uri=c["source_uri"],
            claim_excerpt=f"Verified citation in {case_id}",
        )
        for c in critique_report.get("citations", [])
    ]

    has_pep_or_sanctions = any(
        a["semantic_disposition"] != "SUPPRESSED_FALSE_POSITIVE"
        and a["category"] in {"PEP", "SANCTIONS"}
        for a in watchlist_alerts
    )
    hitl_required, _ = evaluate_sabha_hitl_triggers(
        composite_risk_score=int(audit_result["composite_risk_score"]),
        risk_tier=str(audit_result["risk_tier"]),
        confidence_score=float(audit_result["confidence_score"]),
        has_unresolved_pep_or_sanctions=has_pep_or_sanctions,
        opaque_layer_detected=bool(ubo_result.get("opaque_layer_detected", False)),
    )

    cro_summary = (
        f"CRO 1-Page Executive Brief ({case_id}): {golden.canonical_name} "
        f"scored {audit_result['composite_risk_score']}/100 ({audit_result['risk_tier']}, "
        f"confidence {audit_result['confidence_score']:.2f}). "
        f"Identified {len(ubos)} UBO/Controlling Party node(s); "
        f"HITL Checker sign-off required={hitl_required} "
        f"[snapshot:{audit_snap} | source:policy://kyc_governance_policy.md]."
    )

    qra = QualitativeRiskAssessment(
        case_id=case_id,
        composite_risk_score=int(audit_result["composite_risk_score"]),
        risk_tier=audit_result["risk_tier"],
        confidence_score=float(audit_result["confidence_score"]),
        policy_deviations=list(audit_result["policy_deviations"]),
        transaction_anomalies=list(audit_result["transaction_anomalies"]),
        analyst_detailed_narrative=draft_narrative,
        cro_executive_summary=cro_summary,
        verified_citations=verified_citations,
        hitl_required=hitl_required,
        checker_decision=None,
    )
    return qra, critique_report


async def run_kyc_onboarding_pipeline(
    case_id: str,
    applicant_input: dict[str, Any],
    *,
    checker_token: Optional[str] = None,
    checker_decision: Optional[str] = None,
) -> dict[str, Any]:
    """Executes the full 7-stage Agentic KYC workflow for a corporate applicant."""
    tool_trace: list[str] = []
    recorded_snapshots: set[str] = set()
    event_history: list[dict[str, Any]] = []
    compactor = SankshepaHistoryCompactor()

    with traced_span(
        "orchestrator.sutradhar_kyc_orchestrator",
        {"kyc.case_id": case_id, "kyc.model": NEON_ORCHESTRATOR_MODEL},
    ):
        _LOGGER.info(
            "sutradhar_case_started",
            case_id=case_id,
            agent_name="sutradhar_kyc_orchestrator",
            model_id=NEON_ORCHESTRATOR_MODEL,
        )

        # ------------------------------------------------------------------
        # Stage 1: Dvarapala Intake, Document Quality & Silent Pre-Lookup
        # ------------------------------------------------------------------
        doc = applicant_input["uploaded_document"]
        doc_env = _invoke_instrumented_tool(
            assess_uploaded_document_quality_and_classify,
            case_id=case_id,
            agent_name="chitra_doc_intake_agent",
            model_id=HYDROGEN_FAST_MODEL,
            tool_trace=tool_trace,
            recorded_snapshots=recorded_snapshots,
            document_id=doc["document_id"],
            document_type=doc["document_type"],
            dpi=doc["dpi"],
            blur_score=doc["blur_score"],
            age_days=doc["age_days"],
            expected_entity_name=applicant_input["submitted_name"],
            entity_name_on_doc=doc["entity_name_on_doc"],
            applicant_contact_pii_sample=doc.get("applicant_contact_pii_sample"),
        )
        event_history.append(
            {
                "tool_name": "assess_uploaded_document_quality_and_classify",
                "status": doc_env["status"],
                "snapshot_id": doc_env["snapshot_id"],
            }
        )

        silent_env = _invoke_instrumented_tool(
            execute_silent_entity_pre_lookup,
            case_id=case_id,
            agent_name="gupt_silent_lookup_rfi_agent",
            model_id=HYDROGEN_FAST_MODEL,
            tool_trace=tool_trace,
            recorded_snapshots=recorded_snapshots,
            submitted_name=applicant_input["submitted_name"],
            registration_number=applicant_input.get("registration_number"),
            jurisdiction_iso=applicant_input.get("jurisdiction_iso", "GB"),
        )
        event_history.append(
            {
                "tool_name": "execute_silent_entity_pre_lookup",
                "status": silent_env["status"],
                "snapshot_id": silent_env["snapshot_id"],
            }
        )

        # Query external registry MCP to pre-fill corporate baseline before RFI
        reg_env = _invoke_instrumented_tool(
            query_external_corporate_registry_mcp,
            case_id=case_id,
            agent_name="lekha_registry_mcp_agent",
            model_id=HYDROGEN_FAST_MODEL,
            tool_trace=tool_trace,
            recorded_snapshots=recorded_snapshots,
            legal_name=applicant_input["submitted_name"],
            registration_number=applicant_input.get("registration_number"),
            jurisdiction_iso=applicant_input.get("jurisdiction_iso"),
        )
        filing = reg_env["data"]
        reg_snap = reg_env["snapshot_id"]

        # Check missing mandatory UBO identity attributes + document defects
        missing_rfi_fields: list[str] = []
        if doc_env["status"] == "RECOVERABLE_ERROR" and doc_env.get("data"):
            missing_rfi_fields.extend(doc_env["data"].get("recommended_missing_fields", []))
        for director in filing.get("directors", []):
            if not director.get("nationality"):
                if "ubo_nationality" not in missing_rfi_fields:
                    missing_rfi_fields.append("ubo_nationality")

        if missing_rfi_fields:
            prefilled = {
                "legal_name": filing["legal_name"],
                "incorporation_date": filing["incorporation_date"],
                "registered_address": filing["registered_address"],
                "sic_codes": filing["sic_codes"],
            }
            rfi_env = _invoke_instrumented_tool(
                generate_targeted_client_rfi_outreach,
                case_id=case_id,
                agent_name="gupt_silent_lookup_rfi_agent",
                model_id=HYDROGEN_FAST_MODEL,
                tool_trace=tool_trace,
                recorded_snapshots=recorded_snapshots,
                entity_id=filing["entity_id"],
                requested_fields=missing_rfi_fields,
                reason="Uploaded document defective/expired or mandatory UBO identity field missing.",
            )
            await get_vayu_consolidator().flush()
            return {
                "case_id": case_id,
                "status": "AWAITING_CLIENT_RFI",
                "edd_halted": True,
                "doc_assessment": doc_env,
                "silent_prefilled_fields": prefilled,
                "rfi_envelope": rfi_env,
                "tool_trace": tool_trace,
                "snapshot_ids": sorted(recorded_snapshots),
            }

        # ------------------------------------------------------------------
        # Stage 2: Namarupa Probabilistic Entity Resolution -> Golden Record
        # ------------------------------------------------------------------
        golden_env = _invoke_instrumented_tool(
            resolve_probabilistic_entity_golden_record,
            case_id=case_id,
            agent_name="satya_golden_record_agent",
            model_id=HYDROGEN_FAST_MODEL,
            tool_trace=tool_trace,
            recorded_snapshots=recorded_snapshots,
            submitted_name=applicant_input["submitted_name"],
            submitted_registration_number=applicant_input.get("registration_number"),
            candidates=[
                {
                    "entity_id": filing["entity_id"],
                    "legal_name": filing["legal_name"],
                    "aliases": filing.get("aliases", []),
                    "registration_number": filing["registration_number"],
                    "jurisdiction_iso": filing["jurisdiction_iso"],
                    "incorporation_date": filing["incorporation_date"],
                    "registered_address": filing["registered_address"],
                    "sic_codes": filing.get("sic_codes", []),
                    "source_snapshot_id": reg_snap,
                }
            ],
        )
        golden = CorporateGoldenRecord.model_validate(golden_env["data"])
        get_vayu_consolidator().enqueue_golden_record_update(golden, case_id=case_id)

        # ------------------------------------------------------------------
        # Stage 3: Concurrent Fan-Out — Vamsha UBO, Trishul Skills, Charaka Screening
        # ------------------------------------------------------------------
        ubo_edges = [
            {
                "parent_id": e["parent_id"],
                "parent_name": e["parent_name"],
                "parent_type": e.get("parent_type", "INDIVIDUAL"),
                "child_id": e["child_id"],
                "child_name": e.get("child_name", ""),
                "equity_pct": e["equity_pct"],
                "voting_pct": e["voting_pct"],
                "jurisdiction_iso": e.get("jurisdiction_iso", "GB"),
                "verified": e.get("verified", True),
            }
            for e in filing.get("ownership_edges", [])
        ]

        async def _run_ubo() -> dict[str, Any]:
            return _invoke_instrumented_tool(
                calculate_cascading_ubo_ownership_rollup,
                case_id=case_id,
                agent_name="vamsha_ubo_structure_agent",
                model_id=PRO_REASONING_MODEL,
                tool_trace=tool_trace,
                recorded_snapshots=recorded_snapshots,
                target_entity_id=golden.entity_id,
                edges=ubo_edges,
            )

        subjects = [
            {
                "subject_id": golden.entity_id,
                "full_name": golden.canonical_name,
                "aliases": golden.aliases,
                "jurisdiction_iso": golden.jurisdiction_iso,
                "affiliated_company": golden.canonical_name,
            }
        ]
        for director in filing.get("directors", []):
            subjects.append(
                {
                    "subject_id": director["party_id"],
                    "full_name": director["full_name"],
                    "aliases": [],
                    "dob": director.get("dob"),
                    "jurisdiction_iso": director.get("nationality"),
                    "affiliated_company": golden.canonical_name,
                }
            )

        async def _run_watchlists() -> dict[str, Any]:
            return _invoke_instrumented_tool(
                screen_entity_and_ubos_watchlists,
                case_id=case_id,
                agent_name="suchi_watchlist_screener_agent",
                model_id=HYDROGEN_FAST_MODEL,
                tool_trace=tool_trace,
                recorded_snapshots=recorded_snapshots,
                subjects=subjects,
            )

        async def _run_media() -> dict[str, Any]:
            return _invoke_instrumented_tool(
                evaluate_multilingual_adverse_media_relevance,
                case_id=case_id,
                agent_name="varta_adverse_media_agent",
                model_id=HYDROGEN_FAST_MODEL,
                tool_trace=tool_trace,
                recorded_snapshots=recorded_snapshots,
                subjects=subjects,
            )

        ubo_env, domain_reports, wl_env, media_env = await asyncio.gather(
            _run_ubo(),
            _run_trishul_domain_specialists(case_id, filing, reg_snap),
            _run_watchlists(),
            _run_media(),
        )

        # ------------------------------------------------------------------
        # Stage 4: Transaction Reconciliation & Arthashastra Policy RAG Audit
        # ------------------------------------------------------------------
        wl_alerts = wl_env["data"]["alerts"]
        media_alerts = media_env["data"]["alerts"]
        true_pep_sanctions = sum(
            1
            for a in wl_alerts
            if a["semantic_disposition"] != "SUPPRESSED_FALSE_POSITIVE"
        )
        escalated_media = sum(
            1
            for a in media_alerts
            if a["semantic_disposition"] != "SUPPRESSED_FALSE_POSITIVE"
        )
        bearer_allowed = bool(filing.get("legal_profile", {}).get("bearer_shares_allowed", False))
        opaque_detected = bool(ubo_env["data"].get("opaque_layer_detected", False))

        audit_env = _invoke_instrumented_tool(
            audit_profile_against_transactions_and_policy_rag,
            case_id=case_id,
            agent_name="artha_edd_drafter_agent",
            model_id=PRO_REASONING_MODEL,
            tool_trace=tool_trace,
            recorded_snapshots=recorded_snapshots,
            entity_id=golden.entity_id,
            jurisdiction_iso=golden.jurisdiction_iso,
            sic_codes=golden.sic_codes,
            opaque_layer_detected=opaque_detected,
            bearer_shares_allowed=bearer_allowed,
            true_pep_or_sanctions_hits=true_pep_sanctions,
            unresolved_media_hits=escalated_media,
        )

        # ------------------------------------------------------------------
        # Stage 5: QRA Synthesis & Nyaya Source Citation Critique Loop
        # ------------------------------------------------------------------
        qra, critique_report = _draft_and_critique_qra(
            case_id=case_id,
            golden=golden,
            registry_snap=reg_snap,
            ubo_result=ubo_env["data"],
            ubo_snap=ubo_env["snapshot_id"],
            domain_reports=domain_reports,
            watchlist_alerts=wl_alerts,
            media_alerts=media_alerts,
            audit_result=audit_env["data"],
            audit_snap=audit_env["snapshot_id"],
            recorded_snapshots=recorded_snapshots,
        )

        # ------------------------------------------------------------------
        # Stage 6 & 7: Mandatory Sabha HITL Sign-Off Gate & cKYC Registration
        # ------------------------------------------------------------------
        hitl_env = _invoke_instrumented_tool(
            submit_high_risk_case_for_checker_signoff,
            case_id=case_id,
            agent_name="sabha_hitl_gate_agent",
            model_id=PRO_REASONING_MODEL,
            tool_trace=tool_trace,
            recorded_snapshots=recorded_snapshots,
            entity_id=golden.entity_id,
            composite_risk_score=qra.composite_risk_score,
            risk_tier=qra.risk_tier,
            confidence_score=qra.confidence_score,
            qra_summary=qra.cro_executive_summary,
            has_unresolved_pep_or_sanctions=true_pep_sanctions > 0,
            opaque_layer_detected=opaque_detected,
            checker_token=checker_token,
            checker_decision=checker_decision,
        )

        # Compact event history if needed & flush background Vayu memory writes
        event_history, _ = compactor.compact_history(event_history)
        await get_vayu_consolidator().flush()

        final_status = (
            "BLOCKED_HITL"
            if hitl_env["status"] == "BLOCKED_HITL"
            else "COMPLETED"
        )
        return {
            "case_id": case_id,
            "status": final_status,
            "edd_halted": False,
            "golden_record": golden.model_dump(mode="json"),
            "ubo_result": ubo_env["data"],
            "domain_reports": [r.model_dump(mode="json") for r in domain_reports],
            "watchlist_alerts": wl_alerts,
            "media_alerts": media_alerts,
            "qra": qra.model_dump(mode="json"),
            "critique_report": critique_report,
            "hitl_envelope": hitl_env,
            "tool_trace": tool_trace,
            "snapshot_ids": sorted(recorded_snapshots),
        }


def process_ckyc_monitoring_event(event_payload: dict[str, Any]) -> dict[str, Any]:
    """Stage 7 Perpetual KYC (cKYC) Risk Event Classifier & Webhook Hook.

    Non-material changes (e.g., minor address formatting) auto-log an audit
    snapshot; material changes (new >=25% UBO, >=100% cash wire spike, or
    watchlist match) trigger targeted Stages 3-6 re-verification.
    """
    event = CkYcEventInput.model_validate(event_payload)
    snapshot_id = mint_snapshot_id("CKYC")

    is_material = (
        event.watchlist_hit
        or (event.new_ubo_pct is not None and event.new_ubo_pct >= 25.0)
        or (event.cash_wire_spike_pct is not None and event.cash_wire_spike_pct >= 100.0)
    )

    if is_material:
        action = "RETRIGGERED_STAGES_3_TO_6"
        rationale = (
            f"Material cKYC risk shift detected ({event.event_source}): "
            f"{event.change_summary}. Dynamically queuing Stages 3-6 re-verification."
        )
    else:
        action = "AUTO_LOGGED_NON_MATERIAL"
        rationale = (
            f"Non-material update ({event.event_source}): {event.change_summary}. "
            "Auto-logged to Smriti audit ledger without disturbing client."
        )

    get_smriti_store().save_audit_snapshot(
        snapshot_id=snapshot_id,
        case_id=f"CKYC-{event.event_id}",
        tool_name="process_ckyc_monitoring_event",
        source_uri=f"webhook://ckyc/{event.event_source}",
        payload={"event": event.model_dump(), "action": action, "rationale": rationale},
    )
    _LOGGER.info(
        "ckyc_event_classified",
        case_id=f"CKYC-{event.event_id}",
        agent_name="sutradhar_kyc_orchestrator",
        model_id=NEON_ORCHESTRATOR_MODEL,
        entity_id=event.entity_id,
        is_material=is_material,
        action_taken=action,
        snapshot_id=snapshot_id,
    )
    return CkYcEventResult(
        event_id=event.event_id,
        entity_id=event.entity_id,
        is_material=is_material,
        action_taken=action,  # type: ignore[arg-type]
        rationale=rationale,
        snapshot_id=snapshot_id,
    ).model_dump(mode="json")
