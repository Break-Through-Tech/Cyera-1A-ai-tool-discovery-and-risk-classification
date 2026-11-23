import re
from dataclasses import asdict
from typing import Literal

from fastapi import APIRouter, Request
from pydantic import BaseModel

from app.applications import ApplicationSummary, get_application
from app.errors import AppError
from app.runs import get_run

router = APIRouter(prefix="/runs", tags=["applications"])

_CANDIDATE_NUMBER = re.compile(r"[1-9][0-9]{0,8}")


class ApplicationSummaryOut(BaseModel):
    """One application of a succeeded Run: a resolved Tool or an unresolved Tool Candidate."""

    run_id: str
    subject_kind: Literal["tool", "candidate"]
    subject_id: str
    application_names: list[str]
    domain: str
    identity_outcome: str
    candidate_numbers: list[int]
    event_count: int
    ai_determination: str
    category_outcome: str
    category: str | None
    context_count: int
    risk_outcome: Literal["assessed", "inapplicable"]
    highest_tier: str | None
    investigation_flag: bool
    policy_statuses: list[str]

    @classmethod
    def of(cls, summary: ApplicationSummary) -> "ApplicationSummaryOut":
        return cls(**asdict(summary))


class IdentityOut(BaseModel):
    outcome: str
    tool_id: str | None
    basis: str | None
    reason: str | None
    catalog_tool_ids: list[str]


class EvidenceSourceOut(BaseModel):
    kind: str
    reference: str
    captured_at: str | None
    version: str | None


class EvidenceSentenceOut(BaseModel):
    sentence: str
    probability: float


class AiDeterminationOut(BaseModel):
    determination: str
    stage: str
    reason: str | None
    model: str | None
    probabilities: dict[str, float] | None
    evidence: list[EvidenceSentenceOut]
    needs_review: bool
    source: EvidenceSourceOut | None
    text_supplied: bool | None


class NeighborOut(BaseModel):
    tool_id: str
    name: str
    category: str
    similarity: float


class CategoryClassificationOut(BaseModel):
    outcome: str
    method: str | None
    category: str | None
    reason: str | None
    share: float | None
    neighbors: list[NeighborOut]
    source: EvidenceSourceOut | None


class CandidateOut(BaseModel):
    """One Tool Candidate of the application with its AI and category determinations."""

    candidate_number: int
    application_names: list[str]
    event_count: int
    metadata_id: str | None
    ai_determination: AiDeterminationOut
    category_classification: CategoryClassificationOut


class ActivityOut(BaseModel):
    event_count: int
    first_observed_at: str
    last_observed_at: str
    departments: list[str]


class ContextReferenceOut(BaseModel):
    run_id: str
    context_number: int
    department: str
    usage_purpose: str
    data_sensitivity_tier: str
    event_count: int
    tier: str
    investigation_flag: bool
    flag_reasons: list[str]


class UsageContextsOut(BaseModel):
    outcome: Literal["applicable", "inapplicable"]
    reason: str | None
    count: int
    event_count: int
    departments: list[str]
    first_observed_at: str | None
    last_observed_at: str | None
    references: list[ContextReferenceOut]


class PolicyStatusOut(BaseModel):
    outcome: Literal["applicable", "inapplicable"]
    reason: str | None
    statuses: list[str]


class RiskOut(BaseModel):
    outcome: Literal["assessed", "inapplicable"]
    reason: str | None
    highest_tier: str | None
    tier_counts: dict[str, int]
    investigation_flag: bool
    flag_reasons: list[str]
    rule_versions: list[str]


class ApplicationDetailOut(BaseModel):
    run_id: str
    batch_id: str
    summary: ApplicationSummaryOut
    identity: IdentityOut
    candidates: list[CandidateOut]
    activity: ActivityOut
    usage_contexts: UsageContextsOut
    policy_status: PolicyStatusOut
    risk: RiskOut


@router.get("/{run_id}/applications/{subject_kind}/{subject_id}")
def read_application(
    request: Request,
    run_id: str,
    subject_kind: Literal["tool", "candidate"],
    subject_id: str,
) -> ApplicationDetailOut:
    if subject_kind == "candidate" and not _CANDIDATE_NUMBER.fullmatch(subject_id):
        raise AppError(
            422,
            "invalid_request",
            "The request is invalid.",
            {
                "errors": [
                    {"location": ["path", "subject_id"], "problem": "invalid_candidate_number"}
                ]
            },
        )
    with request.app.state.engine.connect() as connection:
        run = get_run(connection, run_id)
        if run is None:
            raise AppError(404, "run_not_found", "Analysis Run not found.")
        if run.status != "succeeded":
            raise AppError(
                409, "run_not_succeeded", "Only a succeeded Analysis Run has results."
            )
        detail = get_application(connection, run_id, run.batch_id, subject_kind, subject_id)
    if detail is None:
        raise AppError(
            404, "application_not_found", "Application not found in this Analysis Run."
        )
    summary = ApplicationSummaryOut.of(detail["summary"])
    return ApplicationDetailOut(**{**detail, "summary": summary})
