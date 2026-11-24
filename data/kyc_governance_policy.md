# Arthashastra Commercial Bank — KYC & AML Risk Governance Policy (v2026.4)

Inspired by Kautilya's *Arthashastra* principles of transparent treasury governance (*Kosa-Pramana*) and aligned with UK MLR 2017, FATF Recommendations, and EU AMLD6.

## Policy Rule POL-UBO-01: Beneficial Ownership & Voting Control Threshold
Every corporate applicant must disclose all natural persons holding **25% or more effective equity** (computed deterministically across all direct and indirect holding layers). Any natural person exercising **25% or more voting rights** (e.g., via Class-B super-voting shares) or effective control via trustee/nominee mechanisms MUST be classified as a Controlling Person / UBO regardless of equity percentage. Where no 25% owner exists, designate the Senior Managing Official.

## Policy Rule POL-TRUST-02: Offshore Trust & Opaque Structure Restriction
Any ownership layer exceeding 25% held through an unverified offshore discretionary trust (e.g., BVI, Cayman Islands, Panama) without certified settlor, trustee, and beneficiary schedules constitutes an **Opaque Layer Violation**. Such cases automatically require Enhanced Due Diligence (`HIGH_EDD`) and mandatory KYC Checker Human-in-the-Loop (HITL) approval.

## Policy Rule POL-BEARER-03: Prohibition of Bearer Shares
Entities whose articles of association permit unimmobilized **bearer shares** violate bank risk appetite. Minimum penalty: +25 risk points, immediate `HIGH_EDD` escalation, and remediation condition prior to account activation.

## Policy Rule POL-PEP-SANC-04: PEP, Sanctions & Maritime Transshipment Escalation
Any true or unresolved Tier-1 Political Exposed Person (PEP), OFAC/UN/UK HMT Sanctions match, or credible adverse media alleging sanctions evasion / maritime transshipment triggers automatic `HIGH_EDD` (+35 to +50 risk points) and a mandatory programmatic HITL freeze (`BLOCKED_HITL`). Ambiguous adverse media lacking DOB or corporate nexus must NEVER be auto-suppressed; escalate for human review. Confirmed false positives (e.g., verified >=15-year DOB gap and disjoint jurisdiction/company nexus) may be suppressed with explicit cited rationale.

## Policy Rule POL-TXN-05: 90-Day Transaction Profile Reconciliation
Compare 90-day actual volume and cash-wire intensity against expected corporate profile. An unexplained **>=100% surge in cash wires** (such as a 400% spike) or repeated high-risk offshore corridor transactions (>5 transactions) adds +25 risk points and triggers Enhanced Due Diligence plus potential SAR escalation. Brand-new prospects without historical transactions are evaluated against projected turnover baseline (`expected_volume_baseline_only=True`).

## Policy Rule POL-DOC-06: Document Quality & Targeted RFI Standard
Proof-of-address documents older than **90 days** or scans below **150 DPI** / blurry quality are rejected at intake with a targeted RFI. Silent internal CRM and authoritative registry lookups must always execute BEFORE contacting the client; duplicate RFIs for fields already verified in the entity Digital Twin are strictly prohibited.

## Policy Rule POL-HITL-07: Mandatory KYC Checker Sign-Off Gate & Citation Integrity
Autonomous case finalization is strictly forbidden whenever: (a) `composite_risk_score >= 70`, (b) `risk_tier` is `HIGH_EDD` or `PROHIBITED`, (c) an unresolved PEP or Sanctions hit exists, (d) an opaque UBO layer (>25% unverified offshore trust) is present, or (e) `confidence_score < 0.75`. Every factual assertion in the Qualitative Risk Assessment (QRA) must include an inline `[snapshot:<id> | source:<uri>]` citation verified by the Nyaya Critique Agent.
