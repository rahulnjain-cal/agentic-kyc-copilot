"""Namarupa Entity Resolution Tools: External Registry MCP & Golden Record.

Named after *Namarupa* (the Upanishadic principle of "name and form"), these
tools retrieve sovereign corporate registry filings via an MCP abstraction
layer and reconcile variant spellings into a canonical `CorporateGoldenRecord`.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from typing import Any, Optional

from pydantic import ValidationError

from kyc_copilot.constitution import (
    ENTITY_AMBIGUOUS_LOWER_THRESHOLD,
    ENTITY_AUTO_MERGE_THRESHOLD,
)
from kyc_copilot.memory.persistent_store import get_smriti_store
from kyc_copilot.models.schemas import (
    CorporateGoldenRecord,
    EntityCandidateSet,
    NormalizedRegistryFiling,
    RegistryLookupRequest,
    ToolResultEnvelope,
)
from kyc_copilot.tools.registry_data import (
    load_corporate_registries,
    mint_snapshot_id,
)

_SUFFIX_MAP = {
    "limited": "ltd",
    "incorporated": "inc",
    "corporation": "corp",
    "holdings": "holdings",
    "hldgs": "holdings",
    "solns": "solutions",
    "grp": "group",
    "sys": "systems",
}


def normalize_legal_name(raw_name: str) -> str:
    """Standardizes corporate suffixes and punctuation for deterministic matching."""
    tokens = re.findall(r"[a-z0-9]+", raw_name.lower())
    normalized = [_SUFFIX_MAP.get(tok, tok) for tok in tokens]
    return " ".join(normalized)


def _trigram_cosine_similarity(text_a: str, text_b: str) -> float:
    """Simple character-trigram + token cosine similarity in pure Python."""
    norm_a = normalize_legal_name(text_a)
    norm_b = normalize_legal_name(text_b)
    if norm_a == norm_b:
        return 1.0

    def _features(s: str) -> Counter[str]:
        padded = f"  {s}  "
        trigrams = [padded[i : i + 3] for i in range(len(padded) - 2)]
        words = s.split()
        return Counter(trigrams + words)

    vec_a = _features(norm_a)
    vec_b = _features(norm_b)
    common = set(vec_a).intersection(vec_b)
    dot = sum(vec_a[k] * vec_b[k] for k in common)
    mag_a = math.sqrt(sum(v * v for v in vec_a.values()))
    mag_b = math.sqrt(sum(v * v for v in vec_b.values()))
    if mag_a == 0.0 or mag_b == 0.0:
        return 0.0
    return dot / (mag_a * mag_b)


def query_external_corporate_registry_mcp(
    case_id: str,
    legal_name: str,
    registration_number: Optional[str] = None,
    jurisdiction_iso: Optional[str] = None,
    incorporation_year: Optional[int] = None,
) -> dict[str, Any]:
    """Queries external corporate registries (UK Companies House, DE, Cayman) via MCP.

    Resolves authoritative corporate records by exact registration number first,
    then by normalized legal name and optional incorporation year. Returns
    guided disambiguation instructions when a legal name matches multiple
    entities.

    Args:
        case_id: Unique KYC case identifier.
        legal_name: Corporate legal name to search across external registries.
        registration_number: Optional official registry filing number.
        jurisdiction_iso: Optional ISO jurisdiction filter (e.g., GB, KY, US-DE).
        incorporation_year: Optional 4-digit incorporation year to disambiguate.

    Returns:
        JSON-serializable `ToolResultEnvelope[NormalizedRegistryFiling]` dict.
        Returns `status="PARTIAL_MATCH"` with candidate list if multiple
        entities match an ambiguous legal name.
    """
    snapshot_id = mint_snapshot_id("REG")
    try:
        req = RegistryLookupRequest(
            case_id=case_id,
            legal_name=legal_name,
            registration_number=registration_number,
            jurisdiction_iso=jurisdiction_iso,
            incorporation_year=incorporation_year,
        )
    except ValidationError as exc:
        return ToolResultEnvelope[NormalizedRegistryFiling](
            status="RECOVERABLE_ERROR",
            data=None,
            snapshot_id=snapshot_id,
            recovery_instruction=(
                f"Registry lookup request invalid ({exc.error_count()} error(s)). "
                "Provide a valid case_id and legal_name."
            ),
        ).model_dump(mode="json")

    registries = load_corporate_registries().get("external_registries", [])

    # 1. Exact registration number lookup (highest precision)
    if req.registration_number:
        for entry in registries:
            if entry["registration_number"].upper() == req.registration_number.upper():
                filing = NormalizedRegistryFiling(**entry)
                return ToolResultEnvelope[NormalizedRegistryFiling](
                    status="SUCCESS",
                    data=filing,
                    snapshot_id=snapshot_id,
                    recovery_instruction=None,
                ).model_dump(mode="json")

    # 2. Fuzzy/normalized legal name search
    query_norm = normalize_legal_name(req.legal_name)
    matched: list[dict[str, Any]] = []
    for entry in registries:
        if req.jurisdiction_iso and entry["jurisdiction_iso"].upper() != req.jurisdiction_iso.upper():
            continue
        if req.incorporation_year and not entry["incorporation_date"].startswith(str(req.incorporation_year)):
            continue
        candidate_names = [entry["legal_name"], *entry.get("aliases", [])]
        best_sim = max(_trigram_cosine_similarity(query_norm, nm) for nm in candidate_names)
        if best_sim >= 0.72:
            matched.append(entry)

    if len(matched) == 1:
        filing = NormalizedRegistryFiling(**matched[0])
        return ToolResultEnvelope[NormalizedRegistryFiling](
            status="SUCCESS",
            data=filing,
            snapshot_id=snapshot_id,
            recovery_instruction=None,
        ).model_dump(mode="json")

    if len(matched) > 1:
        candidates_summary = [
            {
                "entity_id": m["entity_id"],
                "legal_name": m["legal_name"],
                "registration_number": m["registration_number"],
                "incorporation_date": m["incorporation_date"],
            }
            for m in matched
        ]
        partial_filing = NormalizedRegistryFiling(
            **{**matched[0], "ambiguous_candidates": candidates_summary}
        )
        return ToolResultEnvelope[NormalizedRegistryFiling](
            status="PARTIAL_MATCH",
            data=partial_filing,
            snapshot_id=snapshot_id,
            recovery_instruction=(
                "Ambiguous legal name; re-call tool passing registration_number "
                "or incorporation_year from intake document."
            ),
        ).model_dump(mode="json")

    return ToolResultEnvelope[NormalizedRegistryFiling](
        status="RECOVERABLE_ERROR",
        data=None,
        snapshot_id=snapshot_id,
        recovery_instruction=(
            "No corporate registry match found for the supplied name. Verify "
            "jurisdiction_iso or invoke generate_targeted_client_rfi_outreach "
            "for the certificate of incorporation."
        ),
    ).model_dump(mode="json")


def resolve_probabilistic_entity_golden_record(
    case_id: str,
    submitted_name: str,
    candidates: list[dict[str, Any]],
    submitted_registration_number: Optional[str] = None,
    submitted_address: Optional[str] = None,
) -> dict[str, Any]:
    """Reconciles variant legal names into a canonical CorporateGoldenRecord.

    Computes a combined probabilistic match score (normalized trigram cosine
    similarity plus registration-number corroboration). Auto-commits matches
    scoring >= 0.85 to the Smriti persistent Digital Twin store; returns a
    guided Legal Skill cross-check instruction for borderline scores (0.65-0.85).

    Args:
        case_id: Unique KYC case identifier.
        submitted_name: Applicant-declared corporate name (possibly abbreviated).
        candidates: Non-empty list of candidate dicts matching `EntityCandidate`.
        submitted_registration_number: Optional registration number for exact boost.
        submitted_address: Optional registered address for corroboration.

    Returns:
        JSON-serializable `ToolResultEnvelope[CorporateGoldenRecord]` dict.
    """
    snapshot_id = mint_snapshot_id("GOLDEN")
    try:
        candidate_set = EntityCandidateSet(
            case_id=case_id,
            submitted_name=submitted_name,
            submitted_registration_number=submitted_registration_number,
            submitted_address=submitted_address,
            candidates=candidates,  # type: ignore[arg-type]
        )
    except ValidationError as exc:
        return ToolResultEnvelope[CorporateGoldenRecord](
            status="RECOVERABLE_ERROR",
            data=None,
            snapshot_id=snapshot_id,
            recovery_instruction=(
                f"Candidate set validation failed ({exc.error_count()} error(s)). "
                "Pass valid EntityCandidate dicts from query_external_corporate_registry_mcp."
            ),
        ).model_dump(mode="json")

    best_score = -1.0
    best_candidate = candidate_set.candidates[0]

    for cand in candidate_set.candidates:
        names_to_compare = [cand.legal_name, *cand.aliases]
        name_sim = max(
            _trigram_cosine_similarity(candidate_set.submitted_name, nm)
            for nm in names_to_compare
        )
        reg_bonus = 0.0
        if (
            candidate_set.submitted_registration_number
            and cand.registration_number.upper()
            == candidate_set.submitted_registration_number.upper()
        ):
            reg_bonus = 0.15

        addr_bonus = 0.0
        if candidate_set.submitted_address and cand.registered_address:
            if (
                _trigram_cosine_similarity(
                    candidate_set.submitted_address, cand.registered_address
                )
                >= 0.70
            ):
                addr_bonus = 0.05

        combined_score = min(1.0, round(name_sim + reg_bonus + addr_bonus, 4))
        if combined_score > best_score:
            best_score = combined_score
            best_candidate = cand

    golden = CorporateGoldenRecord(
        entity_id=best_candidate.entity_id,
        canonical_name=best_candidate.legal_name,
        aliases=sorted(set([*best_candidate.aliases, candidate_set.submitted_name])),
        registration_number=best_candidate.registration_number,
        jurisdiction_iso=best_candidate.jurisdiction_iso,
        incorporation_date=best_candidate.incorporation_date,
        registered_address=best_candidate.registered_address,
        sic_codes=best_candidate.sic_codes,
        match_confidence=best_score,
        source_snapshot_ids=[best_candidate.source_snapshot_id, snapshot_id],
    )

    if best_score >= ENTITY_AUTO_MERGE_THRESHOLD:
        get_smriti_store().upsert_golden_record(golden)
        return ToolResultEnvelope[CorporateGoldenRecord](
            status="SUCCESS",
            data=golden,
            snapshot_id=snapshot_id,
            recovery_instruction=None,
        ).model_dump(mode="json")

    if ENTITY_AMBIGUOUS_LOWER_THRESHOLD <= best_score < ENTITY_AUTO_MERGE_THRESHOLD:
        return ToolResultEnvelope[CorporateGoldenRecord](
            status="PARTIAL_MATCH",
            data=golden,
            snapshot_id=snapshot_id,
            recovery_instruction=(
                "Cross-check registered_address via Legal Skill before merging entity nodes."
            ),
        ).model_dump(mode="json")

    return ToolResultEnvelope[CorporateGoldenRecord](
        status="RECOVERABLE_ERROR",
        data=None,
        snapshot_id=snapshot_id,
        recovery_instruction=(
            f"Probabilistic match confidence ({best_score:.2f}) is below 0.65. "
            "Re-query corporate registry using official registration_number."
        ),
    ).model_dump(mode="json")
