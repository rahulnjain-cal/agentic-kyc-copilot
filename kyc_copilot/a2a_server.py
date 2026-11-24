"""Minimal FastAPI Agent-to-Agent (A2A) & Stage 7 cKYC Webhook Server.

Exposes the Arthashastra KYC Copilot to upstream CRM, CLM/Case Management, and
Perpetual KYC event streams alongside the native `adk web` / `adk run` CLI.
"""

from __future__ import annotations

from typing import Any, Optional

from fastapi import FastAPI
from pydantic import BaseModel, Field

from kyc_copilot.constitution import DHARMA_MODEL_ROUTING
from kyc_copilot.sutradhar_harness import (
    process_ckyc_monitoring_event,
    run_kyc_onboarding_pipeline,
)

app = FastAPI(
    title="Arthashastra Agentic KYC & Entity Resolution Copilot (A2A API)",
    version="1.0.0",
)


class KycEvaluateRequest(BaseModel):
    """A2A request payload from upstream CRM or Case Management."""

    case_id: str = Field(..., min_length=3)
    applicant_input: dict[str, Any]
    checker_token: Optional[str] = None
    checker_decision: Optional[str] = None


@app.get("/health")
async def health_check() -> dict[str, Any]:
    """Returns readiness and sovereign model routing policy."""
    return {
        "status": "ok",
        "service": "arthashastra-kyc-copilot",
        "sovereign_region": DHARMA_MODEL_ROUTING.sovereign_region,
        "orchestrator_model": DHARMA_MODEL_ROUTING.sutradhar_orchestrator,
    }


@app.post("/a2a/kyc/evaluate")
async def evaluate_kyc_case(req: KycEvaluateRequest) -> dict[str, Any]:
    """Executes the 7-stage KYC onboarding / review pipeline via A2A."""
    return await run_kyc_onboarding_pipeline(
        case_id=req.case_id,
        applicant_input=req.applicant_input,
        checker_token=req.checker_token,
        checker_decision=req.checker_decision,
    )


@app.post("/webhooks/ckyc-event")
async def ingest_ckyc_event(event_payload: dict[str, Any]) -> dict[str, Any]:
    """Ingests Stage 7 Continuous KYC registry or transaction anomaly webhooks."""
    return process_ckyc_monitoring_event(event_payload)
