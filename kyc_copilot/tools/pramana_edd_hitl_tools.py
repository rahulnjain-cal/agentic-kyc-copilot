"""Pramana EDD Policy RAG Audit & Sabha Mandatory HITL Checker Sign-Off Tools.

Combines *Pramana* (evidence-grounded Policy RAG + 90-day transaction profile
reconciliation) with *Sabha* (the elder council — our hard programmatic Human-
in-the-Loop stop requiring authorized KYC Checker confirmation whenever
composite risk >= 70 or high-risk compliance flags trigger).
"""

from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import ValidationError

from kyc_copilot.callbacks.guardrails import evaluate_sabha_hitl_triggers
from kyc_copilot.config.mudra_secrets import fetch_secret
from kyc_copilot.memory.persistent_store import get_policy_rag, get_smriti_store
from kyc_copilot.models.schemas import (
    HighRiskEscalationInput,
    HitlCheckpointState,
    PolicyAndTxnAuditInput,
    PolicyComplianceAuditResult,
    ToolResultEnvelope,
)
from kyc_copilot.tools.registry_data import (
    load_transactions_90d,
    mint_snapshot_id,
)

HIGH_RISK_JURISDICTIONS = {"KY", "VG", "PA", "SC"}


def audit_profile_against_transactions_and_policy_rag(
    case_id: str,
    entity_id: str,
    jurisdiction_iso: str,
    sic_codes: list[str],
    projected_annual_turnover_gbp: Optional[float] = None,
    opaque_layer_detected: bool = False,
    bearer_shares_allowed: bool = False,
    true_pep_or_sanctions_hits: int = 0,
    unresolved_media_hits: int = 0,
) -> dict[str, Any]:
    """Audits 90-day transaction history against KYC profile and Bank Policy RAG.

    Queries the local TF-IDF / Vertex AI Search Policy RAG index over
    `kyc_governance_policy.md`, checks 90-day cash-wire surges and offshore
    corridors, and computes a deterministic composite risk score (0-100),
    risk tier, and confidence score. Gracefully handles brand-new prospects
    without historical transaction logs.

    Args:
        case_id: Unique KYC case identifier.
        entity_id: Canonical corporate entity identifier.
        jurisdiction_iso: Primary jurisdiction ISO code (e.g., GB, KY).
        sic_codes: List of registered Standard Industrial Classification codes.
        projected_annual_turnover_gbp: Optional projected annual turnover used
            when 90-day transaction history is unavailable for a new prospect.
        opaque_layer_detected: True if >25% unverified offshore trust exists.
        bearer_shares_allowed: True if articles permit unimmobilized bearer shares.
        true_pep_or_sanctions_hits: Count of corroborated PEP/Sanctions matches.
        unresolved_media_hits: Count of escalated adverse media alerts.

    Returns:
        JSON-serializable `ToolResultEnvelope[PolicyComplianceAuditResult]` dict.
    """
    snapshot_id = mint_snapshot_id("AUDIT")
    try:
        audit_in = PolicyAndTxnAuditInput(
            case_id=case_id,
            entity_id=entity_id,
            jurisdiction_iso=jurisdiction_iso,
            sic_codes=sic_codes,
            projected_annual_turnover_gbp=projected_annual_turnover_gbp,
            opaque_layer_detected=opaque_layer_detected,
            bearer_shares_allowed=bearer_shares_allowed,
            true_pep_or_sanctions_hits=true_pep_or_sanctions_hits,
            unresolved_media_hits=unresolved_media_hits,
        )
    except ValidationError as exc:
        return ToolResultEnvelope[PolicyComplianceAuditResult](
            status="RECOVERABLE_ERROR",
            data=None,
            snapshot_id=snapshot_id,
            recovery_instruction=(
                f"Policy/transaction audit input invalid ({exc.error_count()} error(s)). "
                "Provide valid case_id, entity_id, and non-negative hit counts."
            ),
        ).model_dump(mode="json")

    # 1. Retrieve relevant bank policy rules via Policy RAG
    rag_query_terms = [
        "beneficial ownership UBO threshold",
        "90-day transaction cash wire anomaly",
        "HITL checker sign-off",
    ]
    if audit_in.opaque_layer_detected:
        rag_query_terms.append("offshore discretionary trust opaque layer violation")
    if audit_in.bearer_shares_allowed:
        rag_query_terms.append("prohibition of bearer shares")
    if audit_in.true_pep_or_sanctions_hits > 0 or audit_in.unresolved_media_hits > 0:
        rag_query_terms.append("PEP sanctions maritime transshipment escalation")

    matched_rules = get_policy_rag().query_policy(" ".join(rag_query_terms), top_k=4)

    # 2. Deterministic risk scoring & 90-day transaction reconciliation
    risk_score = 15  # Baseline commercial banking risk
    confidence_score = 0.94
    policy_deviations: list[str] = []
    transaction_anomalies: list[str] = []

    if audit_in.jurisdiction_iso.upper() in HIGH_RISK_JURISDICTIONS:
        risk_score += 15
        policy_deviations.append(
            f"POL-TRUST-02: Elevated offshore incorporation jurisdiction ({audit_in.jurisdiction_iso})."
        )

    if audit_in.opaque_layer_detected:
        risk_score += 25
        confidence_score -= 0.15
        policy_deviations.append(
            "POL-TRUST-02: Unverified offshore discretionary trust exceeds 25% ownership threshold."
        )

    if audit_in.bearer_shares_allowed:
        risk_score += 20
        policy_deviations.append(
            "POL-BEARER-03: Articles of association contain unrepealed bearer-share clause."
        )

    if audit_in.true_pep_or_sanctions_hits > 0:
        risk_score += 35
        policy_deviations.append(
            f"POL-PEP-SANC-04: {audit_in.true_pep_or_sanctions_hits} corroborated Tier-1 PEP / Sanctions match(es)."
        )

    if audit_in.unresolved_media_hits > 0:
        risk_score += 15
        policy_deviations.append(
            f"POL-PEP-SANC-04: {audit_in.unresolved_media_hits} escalated adverse media alert(s)."
        )

    txn_feed = load_transactions_90d().get(audit_in.entity_id)
    expected_baseline_only = False
    recovery_hint: Optional[str] = None

    if txn_feed is None:
        expected_baseline_only = True
        recovery_hint = "Evaluate policy rules against projected turnover instead."
    else:
        prior_cash = max(float(txn_feed.get("prior_90d_cash_wire_gbp", 0.0)), 1.0)
        curr_cash = float(txn_feed.get("current_90d_cash_wire_gbp", 0.0))
        cash_growth_pct = ((curr_cash - prior_cash) / prior_cash) * 100.0
        high_risk_txns = int(txn_feed.get("high_risk_corridor_txns", 0))

        if cash_growth_pct >= 100.0:
            risk_score += 25
            transaction_anomalies.append(
                f"POL-TXN-05: Unexplained {cash_growth_pct:.0f}% cash-wire surge "
                f"(GBP {prior_cash:,.0f} -> GBP {curr_cash:,.0f} over 90 days)."
            )
        if high_risk_txns > 5:
            risk_score += 10
            transaction_anomalies.append(
                f"POL-TXN-05: {high_risk_txns} high-risk offshore corridor transfers detected."
            )

    risk_score = min(100, max(0, risk_score))
    confidence_score = round(min(1.0, max(0.5, confidence_score)), 2)

    risk_tier: Literal["LOW", "STANDARD", "HIGH_EDD", "PROHIBITED"]
    if risk_score >= 70 or audit_in.opaque_layer_detected or audit_in.true_pep_or_sanctions_hits > 0:
        risk_tier = "HIGH_EDD"
    elif risk_score >= 40:
        risk_tier = "STANDARD"
    else:
        risk_tier = "LOW"

    result = PolicyComplianceAuditResult(
        entity_id=audit_in.entity_id,
        composite_risk_score=risk_score,
        risk_tier=risk_tier,
        confidence_score=confidence_score,
        policy_deviations=policy_deviations,
        transaction_anomalies=transaction_anomalies,
        matched_policy_rules=matched_rules,
        expected_volume_baseline_only=expected_baseline_only,
    )
    return ToolResultEnvelope[PolicyComplianceAuditResult](
        status="SUCCESS",
        data=result,
        snapshot_id=snapshot_id,
        recovery_instruction=recovery_hint,
    ).model_dump(mode="json")


def submit_high_risk_case_for_checker_signoff(
    case_id: str,
    entity_id: str,
    composite_risk_score: int,
    risk_tier: str,
    confidence_score: float,
    qra_summary: str,
    has_unresolved_pep_or_sanctions: bool = False,
    opaque_layer_detected: bool = False,
    checker_token: Optional[str] = None,
    checker_decision: Optional[str] = None,
) -> dict[str, Any]:
    """Enforces the mandatory Human-in-the-Loop (HITL) stop for high-risk KYC cases.

    Programmatically halts autonomous case finalization whenever
    `composite_risk_score >= 70`, `risk_tier` is `HIGH_EDD`/`PROHIBITED`, an
    unresolved PEP/Sanctions hit exists, an opaque offshore trust (>25%) is
    present, or `confidence_score < 0.75`. Requires an explicit KYC Checker
    confirmation token and decision (`APPROVE`, `ESCALATE_SAR`, or `REJECT`).

    Args:
        case_id: Unique KYC case identifier.
        entity_id: Canonical corporate entity identifier.
        composite_risk_score: Audited risk score between 0 and 100.
        risk_tier: Risk classification (LOW, STANDARD, HIGH_EDD, PROHIBITED).
        confidence_score: QRA explainability confidence score (0.0-1.0).
        qra_summary: Cited executive summary presented to the KYC Checker.
        has_unresolved_pep_or_sanctions: True if any PEP/Sanctions hit is open.
        opaque_layer_detected: True if >25% unverified offshore trust exists.
        checker_token: Optional authorized KYC Checker approval token.
        checker_decision: Optional Checker disposition (APPROVE, ESCALATE_SAR, REJECT).

    Returns:
        JSON-serializable `ToolResultEnvelope[HitlCheckpointState]` dict with
        `status="BLOCKED_HITL"` whenever high-risk approval is pending.
    """
    snapshot_id = mint_snapshot_id("HITL")
    try:
        escalation = HighRiskEscalationInput(
            case_id=case_id,
            entity_id=entity_id,
            composite_risk_score=composite_risk_score,
            risk_tier=risk_tier,  # type: ignore[arg-type]
            confidence_score=confidence_score,
            has_unresolved_pep_or_sanctions=has_unresolved_pep_or_sanctions,
            opaque_layer_detected=opaque_layer_detected,
            qra_summary=qra_summary,
            checker_token=checker_token,
            checker_decision=checker_decision,  # type: ignore[arg-type]
        )
    except ValidationError as exc:
        return ToolResultEnvelope[HitlCheckpointState](
            status="RECOVERABLE_ERROR",
            data=None,
            snapshot_id=snapshot_id,
            recovery_instruction=(
                f"HITL escalation payload invalid ({exc.error_count()} error(s)). "
                "Verify risk_tier, confidence_score, and checker_decision."
            ),
        ).model_dump(mode="json")

    hitl_required, reasons = evaluate_sabha_hitl_triggers(
        composite_risk_score=escalation.composite_risk_score,
        risk_tier=escalation.risk_tier,
        confidence_score=escalation.confidence_score,
        has_unresolved_pep_or_sanctions=escalation.has_unresolved_pep_or_sanctions,
        opaque_layer_detected=escalation.opaque_layer_detected,
    )

    smriti_store = get_smriti_store()

    # Mandatory programmatic HITL stop when Checker confirmation is absent
    if hitl_required and (not escalation.checker_token or not escalation.checker_decision):
        checkpoint = HitlCheckpointState(
            case_id=escalation.case_id,
            entity_id=escalation.entity_id,
            hitl_gate_triggered=True,
            trigger_reasons=reasons,
            awaiting_checker_confirmation=True,
            checker_decision=None,
            ckyc_watch_registered=False,
        )
        smriti_store.save_session_state(
            case_id=escalation.case_id,
            status="AWAITING_KYC_CHECKER_SIGNOFF",
            state={
                "entity_id": escalation.entity_id,
                "composite_risk_score": escalation.composite_risk_score,
                "risk_tier": escalation.risk_tier,
                "trigger_reasons": reasons,
                "qra_summary": escalation.qra_summary,
            },
        )
        return ToolResultEnvelope[HitlCheckpointState](
            status="BLOCKED_HITL",
            data=checkpoint,
            snapshot_id=snapshot_id,
            recovery_instruction=(
                "Pause execution and present QRA summary + UBO Digital Twin to KYC Checker persona."
            ),
        ).model_dump(mode="json")

    # Validate Checker token against Secret Manager / env if configured
    expected_token = fetch_secret(
        secret_name="kyc-copilot-checker-approval-key",
        env_fallback="KYC_CHECKER_APPROVAL_TOKEN",
    )
    if (
        hitl_required
        and expected_token
        and escalation.checker_token != expected_token
    ):
        return ToolResultEnvelope[HitlCheckpointState](
            status="BLOCKED_HITL",
            data=HitlCheckpointState(
                case_id=escalation.case_id,
                entity_id=escalation.entity_id,
                hitl_gate_triggered=True,
                trigger_reasons=[*reasons, "Invalid KYC Checker confirmation token"],
                awaiting_checker_confirmation=True,
                checker_decision=None,
                ckyc_watch_registered=False,
            ),
            snapshot_id=snapshot_id,
            recovery_instruction=(
                "Pause execution and request a valid KYC Checker confirmation token."
            ),
        ).model_dump(mode="json")

    # Approved or low-risk completion -> register Stage 7 cKYC watch trigger
    final_decision = escalation.checker_decision or "APPROVE"
    smriti_store.register_ckyc_watch(
        entity_id=escalation.entity_id,
        case_id=escalation.case_id,
        risk_tier=escalation.risk_tier,
        watch_config={
            "monitors": ["REGISTRY_FILING_CHANGE", "TRANSACTION_ANOMALY_SPIKE", "WATCHLIST_UPDATE"],
            "checker_decision": final_decision,
        },
    )
    smriti_store.save_session_state(
        case_id=escalation.case_id,
        status=f"FINALIZED_{final_decision}",
        state={
            "entity_id": escalation.entity_id,
            "risk_tier": escalation.risk_tier,
            "checker_decision": final_decision,
        },
    )
    checkpoint = HitlCheckpointState(
        case_id=escalation.case_id,
        entity_id=escalation.entity_id,
        hitl_gate_triggered=hitl_required,
        trigger_reasons=reasons,
        awaiting_checker_confirmation=False,
        checker_decision=final_decision,  # type: ignore[arg-type]
        ckyc_watch_registered=True,
    )
    return ToolResultEnvelope[HitlCheckpointState](
        status="SUCCESS",
        data=checkpoint,
        snapshot_id=snapshot_id,
        recovery_instruction=None,
    ).model_dump(mode="json")
