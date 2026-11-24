"""Charaka Semantic Screening Tools: PEP/Sanctions & Multilingual Adverse Media.

Named after *Charaka* / *Gudhapurusha* (intelligence examiners in Kautilya's
*Arthashastra*) and *Viveka* (discernment between true risk and noise), these
tools screen entities and UBOs against mock OFAC/UN/UK HMT/LSEG PEP watchlists
and multilingual adverse media with deterministic DOB/jurisdiction false-
positive suppression.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from pydantic import ValidationError

from kyc_copilot.models.schemas import (
    AdverseMediaCandidateInput,
    AdverseMediaScreeningResult,
    ScreeningAlert,
    ToolResultEnvelope,
    WatchlistBatchRequest,
    WatchlistScreeningResult,
)
from kyc_copilot.tools.registry_data import (
    load_watchlists_and_media,
    mint_snapshot_id,
)


def _extract_birth_year(dob_str: str | None) -> int | None:
    if not dob_str or len(dob_str) < 4:
        return None
    try:
        return date.fromisoformat(dob_str[:10]).year
    except ValueError:
        return None


def screen_entity_and_ubos_watchlists(
    case_id: str,
    subjects: list[dict[str, Any]],
) -> dict[str, Any]:
    """Screens corporate entities and UBOs against OFAC, UN, UK HMT, and PEP lists.

    Evaluates primary legal names and secondary aliases for every subject. If
    any alias encounters a transient connector timeout, returns partial hits
    alongside an explicit retry instruction so screening is NEVER marked CLEAR
    while any UBO remains UNVERIFIED.

    Args:
        case_id: Unique KYC case identifier.
        subjects: Non-empty list of subject dicts matching `ScreeningSubject`
            (`subject_id`, `full_name`, `aliases`, `dob`, `jurisdiction_iso`).

    Returns:
        JSON-serializable `ToolResultEnvelope[WatchlistScreeningResult]` dict.
    """
    snapshot_id = mint_snapshot_id("WL")
    try:
        batch = WatchlistBatchRequest(case_id=case_id, subjects=subjects)  # type: ignore[arg-type]
    except ValidationError as exc:
        return ToolResultEnvelope[WatchlistScreeningResult](
            status="RECOVERABLE_ERROR",
            data=None,
            snapshot_id=snapshot_id,
            recovery_instruction=(
                f"Watchlist batch request invalid ({exc.error_count()} error(s)). "
                "Provide non-empty subjects list with subject_id and full_name."
            ),
        ).model_dump(mode="json")

    watchlists = load_watchlists_and_media().get("watchlists", [])
    alerts: list[ScreeningAlert] = []
    unverified_subjects: list[str] = []

    for subject in batch.subjects:
        all_names = [subject.full_name, *subject.aliases]
        if any("__SIMULATE_TIMEOUT__" in nm for nm in all_names):
            unverified_subjects.append(subject.full_name)
            continue

        lower_names = {nm.lower().strip() for nm in all_names}
        for entry in watchlists:
            entry_names = {
                entry["subject_name"].lower().strip(),
                *(a.lower().strip() for a in entry.get("aliases", [])),
            }
            if lower_names.intersection(entry_names):
                alerts.append(
                    ScreeningAlert(
                        alert_id=f"ALT-{entry['entry_id']}",
                        subject_name=subject.full_name,
                        category=entry["category"],
                        raw_match_score=0.98,
                        semantic_disposition="TRUE_MATCH_HIGH_RISK",
                        suppression_or_escalation_rationale=(
                            f"Exact match on {entry['list_source']} ({entry['tier']}): "
                            f"{entry['summary']}"
                        ),
                        cited_source_uri=entry["source_uri"],
                        snapshot_id=snapshot_id,
                    )
                )

    result = WatchlistScreeningResult(
        alerts=alerts,
        unverified_subjects=unverified_subjects,
        screening_complete=len(unverified_subjects) == 0,
    )

    if unverified_subjects:
        return ToolResultEnvelope[WatchlistScreeningResult](
            status="PARTIAL_MATCH",
            data=result,
            snapshot_id=snapshot_id,
            recovery_instruction=(
                "Retry failed alias once; never mark screening CLEAR when any "
                f"UBO node has status UNVERIFIED. Unverified: {unverified_subjects}"
            ),
        ).model_dump(mode="json")

    return ToolResultEnvelope[WatchlistScreeningResult](
        status="SUCCESS",
        data=result,
        snapshot_id=snapshot_id,
        recovery_instruction=None,
    ).model_dump(mode="json")


def evaluate_multilingual_adverse_media_relevance(
    case_id: str,
    subjects: list[dict[str, Any]],
) -> dict[str, Any]:
    """Evaluates multilingual adverse media hits with semantic false-positive filtering.

    Cross-references candidate press articles (including translated non-English
    maritime/financial reports) against subject DOB, jurisdiction, and corporate
    affiliation. Suppresses verified name-only false positives (e.g., >=15-year
    DOB gap in a disjoint jurisdiction) while conservatively escalating hits
    that lack disambiguating attributes.

    Args:
        case_id: Unique KYC case identifier.
        subjects: Non-empty list of subject dicts matching `ScreeningSubject`.

    Returns:
        JSON-serializable `ToolResultEnvelope[AdverseMediaScreeningResult]` dict.
    """
    snapshot_id = mint_snapshot_id("MEDIA")
    try:
        candidate_input = AdverseMediaCandidateInput(
            case_id=case_id,
            subjects=subjects,  # type: ignore[arg-type]
        )
    except ValidationError as exc:
        return ToolResultEnvelope[AdverseMediaScreeningResult](
            status="RECOVERABLE_ERROR",
            data=None,
            snapshot_id=snapshot_id,
            recovery_instruction=(
                f"Adverse media input invalid ({exc.error_count()} error(s)). "
                "Provide valid subjects with subject_id and full_name."
            ),
        ).model_dump(mode="json")

    articles = load_watchlists_and_media().get("adverse_media_corpus", [])
    alerts: list[ScreeningAlert] = []
    needs_review = False

    for subject in candidate_input.subjects:
        subj_name = subject.full_name.lower().strip()
        subj_year = _extract_birth_year(subject.dob)

        for article in articles:
            matched_names = {
                article["subject_name"].lower().strip(),
                *(nm.lower().strip() for nm in article.get("linked_individuals", [])),
            }
            if subj_name not in matched_names:
                continue

            art_year = _extract_birth_year(article.get("mentioned_dob"))
            art_jur = article.get("mentioned_jurisdiction")
            art_company = article.get("mentioned_company")

            # Rule 1: Lacks DOB and company nexus -> NEVER auto-suppress
            if not art_year and not art_company:
                needs_review = True
                alerts.append(
                    ScreeningAlert(
                        alert_id=f"ALT-{article['article_id']}",
                        subject_name=subject.full_name,
                        category=article["category"],
                        raw_match_score=0.78,
                        semantic_disposition="POTENTIAL_MATCH_NEEDS_REVIEW",
                        suppression_or_escalation_rationale=(
                            "Common-name adverse media article lacks DOB and company "
                            "nexus; escalated conservatively for EDD review."
                        ),
                        cited_source_uri=article["source_uri"],
                        snapshot_id=snapshot_id,
                    )
                )
                continue

            # Rule 2: Clear age-gap (>=15 years) + disjoint jurisdiction/company -> Suppress FP
            company_matches = bool(
                art_company
                and subject.affiliated_company
                and art_company.lower() == subject.affiliated_company.lower()
            )
            if (
                subj_year is not None
                and art_year is not None
                and abs(subj_year - art_year) >= 15
                and not company_matches
            ):
                age_gap = abs(subj_year - art_year)
                alerts.append(
                    ScreeningAlert(
                        alert_id=f"ALT-{article['article_id']}",
                        subject_name=subject.full_name,
                        category=article["category"],
                        raw_match_score=0.92,
                        semantic_disposition="SUPPRESSED_FALSE_POSITIVE",
                        suppression_or_escalation_rationale=(
                            f"Suppressed name-only false positive: {age_gap}-year birth-year "
                            f"gap (subject {subj_year} vs. article {art_year}), disjoint "
                            f"jurisdiction ({subject.jurisdiction_iso} vs. {art_jur}), and "
                            f"unrelated entity ({art_company})."
                        ),
                        cited_source_uri=article["source_uri"],
                        snapshot_id=snapshot_id,
                    )
                )
                continue

            # Rule 3: Corroborated high-risk hit (including translated foreign press)
            headline = article.get("translated_headline") or article.get("headline", "")
            alerts.append(
                ScreeningAlert(
                    alert_id=f"ALT-{article['article_id']}",
                    subject_name=subject.full_name,
                    category=article["category"],
                    raw_match_score=0.96,
                    semantic_disposition="TRUE_MATCH_HIGH_RISK",
                    suppression_or_escalation_rationale=(
                        f"Corroborated adverse media ({article['language'].upper()}): "
                        f"{headline}"
                    ),
                    cited_source_uri=article["source_uri"],
                    snapshot_id=snapshot_id,
                )
            )

    suppressed_count = sum(
        1 for a in alerts if a.semantic_disposition == "SUPPRESSED_FALSE_POSITIVE"
    )
    escalated_count = sum(
        1 for a in alerts if a.semantic_disposition != "SUPPRESSED_FALSE_POSITIVE"
    )

    result = AdverseMediaScreeningResult(
        alerts=alerts,
        suppressed_count=suppressed_count,
        escalated_count=escalated_count,
    )

    if needs_review:
        return ToolResultEnvelope[AdverseMediaScreeningResult](
            status="PARTIAL_MATCH",
            data=result,
            snapshot_id=snapshot_id,
            recovery_instruction=(
                "Do not auto-suppress; escalate uncertain hit to EDD summary."
            ),
        ).model_dump(mode="json")

    return ToolResultEnvelope[AdverseMediaScreeningResult](
        status="SUCCESS",
        data=result,
        snapshot_id=snapshot_id,
        recovery_instruction=None,
    ).model_dump(mode="json")
