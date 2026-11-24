"""Dvarapala Intake Tools: Document Quality, Silent Pre-Lookup & Targeted RFI.

Named after *Dvarapala* (the temple gatekeeper), these three tools guard the
KYC onboarding threshold — catching defective uploads early, pre-populating
existing records silently, and preventing redundant client RFI ping-pong.
"""

from __future__ import annotations

from typing import Any, Optional

from pydantic import ValidationError

from kyc_copilot.constitution import (
    DOC_MAX_PROOF_OF_ADDRESS_AGE_DAYS,
    DOC_MIN_DPI_THRESHOLD,
)
from kyc_copilot.memory.persistent_store import get_smriti_store
from kyc_copilot.models.schemas import (
    DispatchedRfiPayload,
    DocumentQualityAssessment,
    DocumentUploadInput,
    MissingKycFieldsInput,
    PrePopulatedEntityContext,
    SilentLookupQuery,
    ToolResultEnvelope,
)
from kyc_copilot.tools.registry_data import (
    load_corporate_registries,
    mint_snapshot_id,
)


def _normalize_basic(name: str) -> str:
    cleaned = name.lower().replace("limited", "ltd").replace("solns", "solutions")
    cleaned = cleaned.replace("grp", "group")
    return " ".join(cleaned.split())


def assess_uploaded_document_quality_and_classify(
    case_id: str,
    document_id: str,
    document_type: str,
    dpi: int,
    blur_score: float,
    age_days: int,
    expected_entity_name: str,
    entity_name_on_doc: str,
    applicant_contact_pii_sample: Optional[str] = None,
) -> dict[str, Any]:
    """Assesses uploaded KYC document readability, freshness, and entity match.

    Validates scan resolution (minimum 150 DPI), blur score (<= 0.35),
    document recency (<= 90 days for proof of address), and legal entity match.
    Returns structured guided recovery instructions when defects are detected.

    Args:
        case_id: Unique KYC onboarding or review case identifier.
        document_id: Uploaded file identifier from the client intake portal.
        document_type: Document classification (e.g., PROOF_OF_ADDRESS,
            INCORPORATION_CERTIFICATE, TRUST_DEED_AND_ARTICLES).
        dpi: Detected scan resolution in dots per inch.
        blur_score: Normalized image blur index between 0.0 (sharp) and 1.0.
        age_days: Age of the document in days since issuance.
        expected_entity_name: Legal entity name declared on the application.
        entity_name_on_doc: Legal entity name extracted via OCR from the scan.
        applicant_contact_pii_sample: Optional raw contact text (scrubbed in logs).

    Returns:
        JSON-serializable `ToolResultEnvelope[DocumentQualityAssessment]` dict.
        On quality defects, returns `status="RECOVERABLE_ERROR"` with explicit
        guidance to invoke `generate_targeted_client_rfi_outreach`.
    """
    snapshot_id = mint_snapshot_id("DOC")
    try:
        validated = DocumentUploadInput(
            case_id=case_id,
            document_id=document_id,
            document_type=document_type,  # type: ignore[arg-type]
            dpi=dpi,
            blur_score=blur_score,
            age_days=age_days,
            expected_entity_name=expected_entity_name,
            entity_name_on_doc=entity_name_on_doc,
            applicant_contact_pii_sample=applicant_contact_pii_sample,
        )
    except ValidationError as exc:
        envelope: ToolResultEnvelope[DocumentQualityAssessment] = ToolResultEnvelope(
            status="RECOVERABLE_ERROR",
            data=None,
            snapshot_id=snapshot_id,
            recovery_instruction=(
                f"Invalid document metadata ({exc.error_count()} validation error(s)). "
                "Re-submit valid DPI, blur_score (0.0-1.0), and document_type."
            ),
        )
        return envelope.model_dump(mode="json")

    defects: list[str] = []
    missing_fields: list[str] = []

    is_legible = validated.dpi >= DOC_MIN_DPI_THRESHOLD and validated.blur_score <= 0.35
    if validated.dpi < DOC_MIN_DPI_THRESHOLD:
        defects.append(f"Resolution {validated.dpi} DPI is below minimum {DOC_MIN_DPI_THRESHOLD} DPI.")
    if validated.blur_score > 0.35:
        defects.append(f"Blur score {validated.blur_score:.2f} exceeds 0.35 legibility threshold.")

    is_current = True
    if (
        validated.document_type == "PROOF_OF_ADDRESS"
        and validated.age_days > DOC_MAX_PROOF_OF_ADDRESS_AGE_DAYS
    ):
        is_current = False
        defects.append(
            f"Proof of address is {validated.age_days} days old (exceeds "
            f"{DOC_MAX_PROOF_OF_ADDRESS_AGE_DAYS}-day freshness policy)."
        )

    norm_expected = _normalize_basic(validated.expected_entity_name)
    norm_extracted = _normalize_basic(validated.entity_name_on_doc)
    entity_matches = (
        norm_expected == norm_extracted
        or norm_expected.split()[0] == norm_extracted.split()[0]
    )
    if not entity_matches:
        defects.append(
            f"Document entity '{validated.entity_name_on_doc}' does not match "
            f"applicant '{validated.expected_entity_name}'."
        )

    if defects:
        if validated.document_type == "PROOF_OF_ADDRESS":
            missing_fields.append("fresh_proof_of_address_pdf")
        else:
            missing_fields.append(f"legible_{validated.document_type.lower()}_pdf")

    assessment = DocumentQualityAssessment(
        document_id=validated.document_id,
        document_type=validated.document_type,
        is_legible=is_legible,
        is_current=is_current,
        entity_matches=entity_matches,
        defects=defects,
        recommended_missing_fields=missing_fields,
    )

    if defects:
        return ToolResultEnvelope[DocumentQualityAssessment](
            status="RECOVERABLE_ERROR",
            data=assessment,
            snapshot_id=snapshot_id,
            recovery_instruction=(
                "Invoke generate_targeted_client_rfi_outreach requesting a legible, current PDF."
            ),
        ).model_dump(mode="json")

    return ToolResultEnvelope[DocumentQualityAssessment](
        status="SUCCESS",
        data=assessment,
        snapshot_id=snapshot_id,
        recovery_instruction=None,
    ).model_dump(mode="json")


def execute_silent_entity_pre_lookup(
    case_id: str,
    submitted_name: str,
    registration_number: Optional[str] = None,
    jurisdiction_iso: str = "GB",
) -> dict[str, Any]:
    """Silently pre-populates entity KYC fields from internal CRM and Smriti store.

    Always runs BEFORE contacting the client so corporate attributes already
    known to the bank or cached in the persistent Digital Twin are never
    re-requested via RFI.

    Args:
        case_id: Unique KYC case identifier.
        submitted_name: Legal name submitted by the corporate applicant.
        registration_number: Optional corporate registry number (e.g., UK-11204588).
        jurisdiction_iso: Two-letter ISO jurisdiction code (default "GB").

    Returns:
        JSON-serializable `ToolResultEnvelope[PrePopulatedEntityContext]` dict.
        If internal CRM has zero prior records, returns `status="PARTIAL_MATCH"`
        with guidance to query the external corporate registry MCP immediately.
    """
    snapshot_id = mint_snapshot_id("SILENT")
    try:
        query = SilentLookupQuery(
            case_id=case_id,
            submitted_name=submitted_name,
            registration_number=registration_number,
            jurisdiction_iso=jurisdiction_iso,
        )
    except ValidationError as exc:
        return ToolResultEnvelope[PrePopulatedEntityContext](
            status="RECOVERABLE_ERROR",
            data=None,
            snapshot_id=snapshot_id,
            recovery_instruction=(
                f"Silent lookup input invalid ({exc.error_count()} error(s)). "
                "Supply valid case_id and submitted_name."
            ),
        ).model_dump(mode="json")

    smriti_store = get_smriti_store()
    if query.registration_number:
        cached_twin = smriti_store.find_by_registration_number(query.registration_number)
        if cached_twin is not None:
            context = PrePopulatedEntityContext(
                found_in_internal_crm=True,
                entity_id=cached_twin.entity_id,
                prefilled_fields={
                    "legal_name": cached_twin.canonical_name,
                    "registration_number": cached_twin.registration_number,
                    "jurisdiction_iso": cached_twin.jurisdiction_iso,
                    "incorporation_date": cached_twin.incorporation_date,
                    "registered_address": cached_twin.registered_address,
                    "sic_codes": cached_twin.sic_codes,
                },
                missing_mandatory_fields=[],
                source_system="SMRITI_DIGITAL_TWIN_SQLITE",
            )
            return ToolResultEnvelope[PrePopulatedEntityContext](
                status="SUCCESS",
                data=context,
                snapshot_id=snapshot_id,
                recovery_instruction=None,
            ).model_dump(mode="json")

    crm_records = load_corporate_registries().get("internal_crm_records", {})
    crm_hit = crm_records.get(query.registration_number or "")
    if crm_hit:
        context = PrePopulatedEntityContext(
            found_in_internal_crm=True,
            entity_id=crm_hit["entity_id"],
            prefilled_fields={
                "legal_name": crm_hit["canonical_name"],
                "registration_number": crm_hit["registration_number"],
                "jurisdiction_iso": crm_hit["jurisdiction_iso"],
                "incorporation_date": crm_hit["incorporation_date"],
                "registered_address": crm_hit["registered_address"],
                "sic_codes": crm_hit["sic_codes"],
                "prior_cdd_tier": crm_hit["prior_cdd_tier"],
            },
            missing_mandatory_fields=[],
            source_system="INTERNAL_CRM_LEGACY",
        )
        return ToolResultEnvelope[PrePopulatedEntityContext](
            status="SUCCESS",
            data=context,
            snapshot_id=snapshot_id,
            recovery_instruction=None,
        ).model_dump(mode="json")

    # Zero internal CRM records: guide agent to external registry MCP immediately.
    empty_context = PrePopulatedEntityContext(
        found_in_internal_crm=False,
        entity_id=None,
        prefilled_fields={},
        missing_mandatory_fields=["incorporation_date", "registered_address", "sic_codes"],
        source_system="SMRITI_INTERNAL_CRM",
    )
    return ToolResultEnvelope[PrePopulatedEntityContext](
        status="PARTIAL_MATCH",
        data=empty_context,
        snapshot_id=snapshot_id,
        recovery_instruction=(
            "Proceed immediately to query_external_corporate_registry_mcp "
            "using registration_number and jurisdiction_iso."
        ),
    ).model_dump(mode="json")


def generate_targeted_client_rfi_outreach(
    case_id: str,
    entity_id: str,
    requested_fields: list[str],
    reason: str,
) -> dict[str, Any]:
    """Generates a targeted client RFI while blocking duplicate requests.

    Inspects the persistent Smriti Digital Twin before drafting outreach. If
    any requested field is already verified in a persisted Golden Record
    snapshot, rejects the duplicate RFI and instructs the agent to read the
    state graph instead. Otherwise persists session status `AWAITING_CLIENT_RFI`.

    Args:
        case_id: Unique KYC case identifier.
        entity_id: Canonical or provisional entity identifier.
        requested_fields: List of genuinely missing or expired field identifiers.
        reason: Concise explanation for the client/Relationship Manager.

    Returns:
        JSON-serializable `ToolResultEnvelope[DispatchedRfiPayload]` dict.
    """
    snapshot_id = mint_snapshot_id("RFI")
    try:
        validated = MissingKycFieldsInput(
            case_id=case_id,
            entity_id=entity_id,
            requested_fields=requested_fields,
            reason=reason,
        )
    except ValidationError as exc:
        return ToolResultEnvelope[DispatchedRfiPayload](
            status="RECOVERABLE_ERROR",
            data=None,
            snapshot_id=snapshot_id,
            recovery_instruction=(
                f"Invalid RFI payload ({exc.error_count()} error(s)). "
                "Provide non-empty requested_fields and a clear reason."
            ),
        ).model_dump(mode="json")

    smriti_store = get_smriti_store()
    existing_twin = smriti_store.get_golden_record(validated.entity_id)

    duplicate_fields: list[str] = []
    if existing_twin is not None:
        verified_map = {
            "legal_name": bool(existing_twin.canonical_name),
            "canonical_name": bool(existing_twin.canonical_name),
            "registration_number": bool(existing_twin.registration_number),
            "incorporation_date": bool(existing_twin.incorporation_date),
            "registered_address": bool(existing_twin.registered_address),
            "sic_codes": bool(existing_twin.sic_codes),
        }
        for field_name in validated.requested_fields:
            if verified_map.get(field_name, False):
                duplicate_fields.append(field_name)

        if duplicate_fields:
            existing_snap = (
                existing_twin.source_snapshot_ids[0]
                if existing_twin.source_snapshot_ids
                else snapshot_id
            )
            return ToolResultEnvelope[DispatchedRfiPayload](
                status="RECOVERABLE_ERROR",
                data=None,
                snapshot_id=existing_snap,
                recovery_instruction=(
                    "Field already verified in snapshot_id; read state graph "
                    f"instead of re-prompting client. Duplicate fields: {duplicate_fields}"
                ),
            ).model_dump(mode="json")

    rfi_id = f"RFI-{validated.case_id}-{snapshot_id[-4:]}"
    formatted_items = ", ".join(validated.requested_fields)
    payload = DispatchedRfiPayload(
        rfi_id=rfi_id,
        case_id=validated.case_id,
        entity_id=validated.entity_id,
        session_state="AWAITING_CLIENT_RFI",
        requested_fields=validated.requested_fields,
        client_message=(
            f"We have pre-populated your corporate profile from official registries. "
            f"To complete onboarding ({validated.case_id}), please provide only: "
            f"{formatted_items}. Reason: {validated.reason}"
        ),
        duplicate_fields_blocked=[],
    )
    smriti_store.save_session_state(
        case_id=validated.case_id,
        status="AWAITING_CLIENT_RFI",
        state={
            "entity_id": validated.entity_id,
            "rfi_id": rfi_id,
            "requested_fields": validated.requested_fields,
            "reason": validated.reason,
        },
    )
    return ToolResultEnvelope[DispatchedRfiPayload](
        status="SUCCESS",
        data=payload,
        snapshot_id=snapshot_id,
        recovery_instruction=None,
    ).model_dump(mode="json")
