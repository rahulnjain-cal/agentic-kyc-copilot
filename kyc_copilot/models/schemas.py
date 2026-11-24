"""Strict Pydantic v2 Input/Output Schemas & ToolResultEnvelope.

Every tool accepts and emits strictly validated Pydantic v2 models wrapped in
`ToolResultEnvelope[T]` so LLMs receive structured snapshots and explicit
`recovery_instruction` payloads rather than unhandled exceptions.
"""

from __future__ import annotations

from typing import Any, Generic, Literal, Optional, TypeVar

from pydantic import BaseModel, ConfigDict, Field

T = TypeVar("T")


# ---------------------------------------------------------------------------
# Generic Guided-Recovery Tool Envelope
# ---------------------------------------------------------------------------
class ToolResultEnvelope(BaseModel, Generic[T]):
    """Standardized response wrapper for every KYC tool invocation."""

    model_config = ConfigDict(extra="forbid")

    status: Literal[
        "SUCCESS",
        "PARTIAL_MATCH",
        "RECOVERABLE_ERROR",
        "BLOCKED_HITL",
    ]
    data: Optional[T] = None
    snapshot_id: str = Field(
        ...,
        description="Immutable audit snapshot identifier persisted for lineage.",
    )
    recovery_instruction: Optional[str] = Field(
        default=None,
        description="Explicit next-step guidance returned to the LLM on errors or ambiguity.",
    )


# ---------------------------------------------------------------------------
# Stage 1: Intake, Document Quality & Silent Pre-Lookup
# ---------------------------------------------------------------------------
class DocumentUploadInput(BaseModel):
    """Input payload for assessing an uploaded KYC document scan."""

    model_config = ConfigDict(extra="forbid")

    case_id: str = Field(..., min_length=3)
    document_id: str = Field(..., min_length=2)
    document_type: Literal[
        "PROOF_OF_ADDRESS",
        "INCORPORATION_CERTIFICATE",
        "TRUST_DEED_AND_ARTICLES",
        "PASSPORT_ID",
        "FINANCIAL_STATEMENT",
    ]
    dpi: int = Field(..., ge=10, le=2400)
    blur_score: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="0.0 is crystal sharp; values > 0.35 indicate unreadable blur.",
    )
    age_days: int = Field(..., ge=0)
    expected_entity_name: str = Field(..., min_length=2)
    entity_name_on_doc: str = Field(..., min_length=2)
    applicant_contact_pii_sample: Optional[str] = Field(
        default=None,
        description="Optional raw contact snippet tested against Kavach PII redaction.",
    )


class DocumentQualityAssessment(BaseModel):
    """Output of multimodal / OCR document quality validation."""

    model_config = ConfigDict(extra="forbid")

    document_id: str
    document_type: str
    is_legible: bool
    is_current: bool
    entity_matches: bool
    defects: list[str] = Field(default_factory=list)
    recommended_missing_fields: list[str] = Field(default_factory=list)


class SilentLookupQuery(BaseModel):
    """Query for internal CRM + Digital Twin silent pre-population."""

    model_config = ConfigDict(extra="forbid")

    case_id: str = Field(..., min_length=3)
    submitted_name: str = Field(..., min_length=2)
    registration_number: Optional[str] = None
    jurisdiction_iso: str = Field(default="GB", min_length=2, max_length=6)


class PrePopulatedEntityContext(BaseModel):
    """Entity attributes silently pre-populated before contacting the client."""

    model_config = ConfigDict(extra="forbid")

    found_in_internal_crm: bool
    entity_id: Optional[str] = None
    prefilled_fields: dict[str, Any] = Field(default_factory=dict)
    missing_mandatory_fields: list[str] = Field(default_factory=list)
    source_system: str = "SMRITI_INTERNAL_CRM"


class MissingKycFieldsInput(BaseModel):
    """Input for generating a targeted, zero-duplication client RFI."""

    model_config = ConfigDict(extra="forbid")

    case_id: str = Field(..., min_length=3)
    entity_id: str = Field(..., min_length=3)
    requested_fields: list[str] = Field(..., min_length=1)
    reason: str = Field(..., min_length=5)


class DispatchedRfiPayload(BaseModel):
    """Structured Request for Information dispatched to the RM/Client."""

    model_config = ConfigDict(extra="forbid")

    rfi_id: str
    case_id: str
    entity_id: str
    session_state: Literal["AWAITING_CLIENT_RFI"] = "AWAITING_CLIENT_RFI"
    requested_fields: list[str]
    client_message: str
    duplicate_fields_blocked: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Stage 2: Corporate Registry MCP & Probabilistic Entity Resolution
# ---------------------------------------------------------------------------
class RegistryLookupRequest(BaseModel):
    """Request to query external corporate registries via the MCP layer."""

    model_config = ConfigDict(extra="forbid")

    case_id: str = Field(..., min_length=3)
    legal_name: str = Field(..., min_length=2)
    registration_number: Optional[str] = None
    jurisdiction_iso: Optional[str] = None
    incorporation_year: Optional[int] = None


class NormalizedRegistryFiling(BaseModel):
    """Canonicalized response from an external corporate registry connector."""

    model_config = ConfigDict(extra="forbid")

    registry_source: str
    entity_id: str
    legal_name: str
    aliases: list[str] = Field(default_factory=list)
    registration_number: str
    jurisdiction_iso: str
    status: str
    incorporation_date: str
    registered_address: str
    sic_codes: list[str] = Field(default_factory=list)
    vat_number: Optional[str] = None
    directors: list[dict[str, Any]] = Field(default_factory=list)
    ownership_edges: list[dict[str, Any]] = Field(default_factory=list)
    financials: dict[str, Any] = Field(default_factory=dict)
    tax_profile: dict[str, Any] = Field(default_factory=dict)
    legal_profile: dict[str, Any] = Field(default_factory=dict)
    ambiguous_candidates: list[dict[str, str]] = Field(default_factory=list)


class EntityCandidate(BaseModel):
    """Candidate corporate record for probabilistic resolution."""

    model_config = ConfigDict(extra="forbid")

    entity_id: str
    legal_name: str
    aliases: list[str] = Field(default_factory=list)
    registration_number: str
    jurisdiction_iso: str
    incorporation_date: str
    registered_address: str
    sic_codes: list[str] = Field(default_factory=list)
    source_snapshot_id: str


class EntityCandidateSet(BaseModel):
    """Input set comparing submitted applicant details with registry candidates."""

    model_config = ConfigDict(extra="forbid")

    case_id: str = Field(..., min_length=3)
    submitted_name: str = Field(..., min_length=2)
    submitted_registration_number: Optional[str] = None
    submitted_address: Optional[str] = None
    candidates: list[EntityCandidate] = Field(..., min_length=1)


class CorporateGoldenRecord(BaseModel):
    """Canonical entity Digital Twin committed to the Smriti store."""

    model_config = ConfigDict(extra="forbid")

    entity_id: str
    canonical_name: str
    aliases: list[str] = Field(default_factory=list)
    registration_number: str
    jurisdiction_iso: str
    incorporation_date: str
    registered_address: str
    sic_codes: list[str] = Field(default_factory=list)
    match_confidence: float = Field(..., ge=0.0, le=1.0)
    source_snapshot_ids: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Stage 3: UBO Ownership Graph & Domain Specialist Reports
# ---------------------------------------------------------------------------
ControlMechanism = Literal[
    "DIRECT_EQUITY",
    "INDIRECT_ROLLUP",
    "VOTING_RIGHTS_OVERRIDE",
    "TRUSTEE_CONTROL",
    "SENIOR_MANAGING_OFFICIAL",
]


class OwnershipEdge(BaseModel):
    """Directed ownership or control edge from parent owner to child entity."""

    model_config = ConfigDict(extra="forbid")

    parent_id: str
    parent_name: str
    parent_type: Literal["INDIVIDUAL", "CORPORATE", "OFFSHORE_TRUST"] = "INDIVIDUAL"
    child_id: str
    child_name: str = ""
    equity_pct: float = Field(..., ge=0.0, le=100.0)
    voting_pct: float = Field(..., ge=0.0, le=100.0)
    control_mechanism: ControlMechanism = "DIRECT_EQUITY"
    jurisdiction_iso: str = "GB"
    verified: bool = True


class CorporateGraphEdgesInput(BaseModel):
    """Input to the deterministic Python cascading UBO ownership calculator."""

    model_config = ConfigDict(extra="forbid")

    case_id: str = Field(..., min_length=3)
    target_entity_id: str = Field(..., min_length=3)
    edges: list[OwnershipEdge] = Field(..., min_length=1)
    senior_managing_official_name: Optional[str] = None
    equity_threshold_pct: float = Field(default=25.0, ge=1.0, le=100.0)
    voting_threshold_pct: float = Field(default=25.0, ge=1.0, le=100.0)


class UBOParty(BaseModel):
    """Resolved Ultimate Beneficial Owner or Controlling Person."""

    model_config = ConfigDict(extra="forbid")

    party_id: str
    full_name: str
    effective_equity_pct: float = Field(..., ge=0.0, le=100.0)
    effective_voting_pct: float = Field(..., ge=0.0, le=100.0)
    control_mechanism: ControlMechanism
    jurisdiction_iso: str
    ownership_paths: list[str] = Field(default_factory=list)
    verified: bool = True


class UBOGraphResult(BaseModel):
    """Deterministic UBO roll-up result with graph visualization payload."""

    model_config = ConfigDict(extra="forbid")

    target_entity_id: str
    identified_ubos: list[UBOParty] = Field(default_factory=list)
    opaque_layer_detected: bool = False
    offending_node_ids: list[str] = Field(default_factory=list)
    mermaid_or_json_tree: dict[str, Any] = Field(default_factory=dict)


class DomainSpecialistReport(BaseModel):
    """Structured output from Legal (Vidhi), Tax (Shulka), or Credit (Kosa)."""

    model_config = ConfigDict(extra="forbid")

    domain: Literal["LEGAL", "TAX_FATCA_CRS", "CREDIT"]
    agent_name: str
    risk_flags: list[str] = Field(default_factory=list)
    findings_summary: str
    snapshot_id: str
    source_uri: str


# ---------------------------------------------------------------------------
# Stage 3b: Watchlist & Multilingual Adverse Media Screening
# ---------------------------------------------------------------------------
class ScreeningSubject(BaseModel):
    """Person or corporate node submitted for watchlist/media screening."""

    model_config = ConfigDict(extra="forbid")

    subject_id: str
    full_name: str
    aliases: list[str] = Field(default_factory=list)
    dob: Optional[str] = None
    jurisdiction_iso: Optional[str] = None
    affiliated_company: Optional[str] = None


class WatchlistBatchRequest(BaseModel):
    """Batch PEP/Sanctions screening request."""

    model_config = ConfigDict(extra="forbid")

    case_id: str = Field(..., min_length=3)
    subjects: list[ScreeningSubject] = Field(..., min_length=1)


class AdverseMediaCandidateInput(BaseModel):
    """Input for multilingual adverse media semantic disambiguation."""

    model_config = ConfigDict(extra="forbid")

    case_id: str = Field(..., min_length=3)
    subjects: list[ScreeningSubject] = Field(..., min_length=1)


class ScreeningAlert(BaseModel):
    """Watchlist or adverse media alert with semantic disposition."""

    model_config = ConfigDict(extra="forbid")

    alert_id: str
    subject_name: str
    category: Literal[
        "SANCTIONS",
        "PEP",
        "ADVERSE_MEDIA_FRAUD",
        "ADVERSE_MEDIA_AML",
        "ADVERSE_MEDIA_SANCTIONS_EVASION",
    ]
    raw_match_score: float = Field(..., ge=0.0, le=1.0)
    semantic_disposition: Literal[
        "TRUE_MATCH_HIGH_RISK",
        "POTENTIAL_MATCH_NEEDS_REVIEW",
        "SUPPRESSED_FALSE_POSITIVE",
    ]
    suppression_or_escalation_rationale: str
    cited_source_uri: str
    snapshot_id: str


class WatchlistScreeningResult(BaseModel):
    """Aggregated watchlist screening payload."""

    model_config = ConfigDict(extra="forbid")

    alerts: list[ScreeningAlert] = Field(default_factory=list)
    unverified_subjects: list[str] = Field(default_factory=list)
    screening_complete: bool = True


class AdverseMediaScreeningResult(BaseModel):
    """Aggregated adverse media screening payload."""

    model_config = ConfigDict(extra="forbid")

    alerts: list[ScreeningAlert] = Field(default_factory=list)
    suppressed_count: int = 0
    escalated_count: int = 0


# ---------------------------------------------------------------------------
# Stage 4 & 5: Policy RAG Audit, Citations & Qualitative Risk Assessment
# ---------------------------------------------------------------------------
class SourceCitation(BaseModel):
    """Verifiable inline citation anchoring a QRA claim to a tool snapshot."""

    model_config = ConfigDict(extra="forbid")

    snapshot_id: str
    source_uri: str
    claim_excerpt: str


class PolicyAndTxnAuditInput(BaseModel):
    """Input for 90-day transaction reconciliation and Policy RAG audit."""

    model_config = ConfigDict(extra="forbid")

    case_id: str = Field(..., min_length=3)
    entity_id: str = Field(..., min_length=3)
    jurisdiction_iso: str
    sic_codes: list[str] = Field(default_factory=list)
    projected_annual_turnover_gbp: Optional[float] = None
    opaque_layer_detected: bool = False
    bearer_shares_allowed: bool = False
    true_pep_or_sanctions_hits: int = Field(default=0, ge=0)
    unresolved_media_hits: int = Field(default=0, ge=0)


class PolicyComplianceAuditResult(BaseModel):
    """Structured output of transaction profiling and Policy RAG matching."""

    model_config = ConfigDict(extra="forbid")

    entity_id: str
    composite_risk_score: int = Field(..., ge=0, le=100)
    risk_tier: Literal["LOW", "STANDARD", "HIGH_EDD", "PROHIBITED"]
    confidence_score: float = Field(..., ge=0.0, le=1.0)
    policy_deviations: list[str] = Field(default_factory=list)
    transaction_anomalies: list[str] = Field(default_factory=list)
    matched_policy_rules: list[dict[str, Any]] = Field(default_factory=list)
    expected_volume_baseline_only: bool = False


class QualitativeRiskAssessment(BaseModel):
    """Regulator-defensible QRA dossier and CRO executive brief."""

    model_config = ConfigDict(extra="forbid")

    case_id: str
    composite_risk_score: int = Field(..., ge=0, le=100)
    risk_tier: Literal["LOW", "STANDARD", "HIGH_EDD", "PROHIBITED"]
    confidence_score: float = Field(..., ge=0.0, le=1.0)
    policy_deviations: list[str] = Field(default_factory=list)
    transaction_anomalies: list[str] = Field(default_factory=list)
    analyst_detailed_narrative: str
    cro_executive_summary: str
    verified_citations: list[SourceCitation] = Field(default_factory=list)
    hitl_required: bool
    checker_decision: Optional[Literal["APPROVE", "ESCALATE_SAR", "REJECT"]] = None


# ---------------------------------------------------------------------------
# Stage 6 & 7: Mandatory HITL Checker Sign-Off & Perpetual KYC (cKYC)
# ---------------------------------------------------------------------------
class HighRiskEscalationInput(BaseModel):
    """Input to the mandatory Sabah HITL Checker approval stop."""

    model_config = ConfigDict(extra="forbid")

    case_id: str = Field(..., min_length=3)
    entity_id: str = Field(..., min_length=3)
    composite_risk_score: int = Field(..., ge=0, le=100)
    risk_tier: Literal["LOW", "STANDARD", "HIGH_EDD", "PROHIBITED"]
    confidence_score: float = Field(..., ge=0.0, le=1.0)
    has_unresolved_pep_or_sanctions: bool = False
    opaque_layer_detected: bool = False
    qra_summary: str = Field(..., min_length=10)
    checker_token: Optional[str] = Field(
        default=None,
        description="Authorized KYC Checker confirmation token; absence forces BLOCKED_HITL.",
    )
    checker_decision: Optional[Literal["APPROVE", "ESCALATE_SAR", "REJECT"]] = None


class HitlCheckpointState(BaseModel):
    """Human-in-the-Loop governance checkpoint state."""

    model_config = ConfigDict(extra="forbid")

    case_id: str
    entity_id: str
    hitl_gate_triggered: bool
    trigger_reasons: list[str] = Field(default_factory=list)
    awaiting_checker_confirmation: bool
    checker_decision: Optional[Literal["APPROVE", "ESCALATE_SAR", "REJECT"]] = None
    ckyc_watch_registered: bool = False


class CkYcEventInput(BaseModel):
    """Incoming Perpetual KYC (cKYC) registry or transaction webhook event."""

    model_config = ConfigDict(extra="forbid")

    event_id: str
    entity_id: str
    event_source: Literal["REGISTRY_FILING_CHANGE", "TRANSACTION_ANOMALY_SPIKE", "WATCHLIST_UPDATE"]
    change_summary: str
    new_ubo_pct: Optional[float] = None
    cash_wire_spike_pct: Optional[float] = None
    watchlist_hit: bool = False


class CkYcEventResult(BaseModel):
    """Materiality classification and pipeline re-trigger decision for cKYC."""

    model_config = ConfigDict(extra="forbid")

    event_id: str
    entity_id: str
    is_material: bool
    action_taken: Literal["AUTO_LOGGED_NON_MATERIAL", "RETRIGGERED_STAGES_3_TO_6"]
    rationale: str
    snapshot_id: str
