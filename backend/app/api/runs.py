from typing import Any, Literal

from fastapi import APIRouter, Request
from pydantic import BaseModel

from app.api.pagination import Page, PageParams
from app.errors import AppError
from app.results import list_assessments
from app.runs import Run, get_run

router = APIRouter(prefix="/runs", tags=["runs"])


class RunFailure(BaseModel):
    summary: str
    phase: str | None


class RunOut(BaseModel):
    run_id: str
    batch_id: str
    attempt_number: int
    status: str
    started_at: str
    completed_at: str | None
    versions: dict[str, str]
    code_commit: str | None
    failure: RunFailure | None

    @classmethod
    def of(cls, run: Run) -> "RunOut":
        failure = None
        if run.status == "failed":
            failure = RunFailure(summary=run.failure_summary, phase=run.failure_phase)
        return cls(
            run_id=run.run_id,
            batch_id=run.batch_id,
            attempt_number=run.attempt_number,
            status=run.status,
            started_at=run.started_at,
            completed_at=run.completed_at,
            versions=run.versions,
            code_commit=run.code_commit,
            failure=failure,
        )


@router.get("/{run_id}")
def read_run(request: Request, run_id: str) -> RunOut:
    with request.app.state.engine.connect() as connection:
        run = get_run(connection, run_id)
    if run is None:
        raise AppError(404, "run_not_found", "Analysis Run not found.")
    return RunOut.of(run)


class RiskFactsOut(BaseModel):
    policy_status: str
    training_on_customer_data: str
    admin_controls_available: str
    # Added by owasp-usage-risk-v2; absent on rows saved by v1.
    data_sensitivity_tier: str | None = None
    interaction_class: str | None = None
    in_inventory: bool | None = None


Tier = Literal["High", "Medium", "Low", "unresolved", "not_assessed"]
InteractionClass = Literal["presence", "content_submission", "access_grant", "unknown"]


class AssessmentOut(BaseModel):
    """One Usage Context of a succeeded Run and its contextual-risk assessment.

    Fields after ``rule_version`` were added by ``owasp-usage-risk-v2`` and are null on rows
    saved by v1.
    """

    context_number: int
    tool_id: str
    application_name: str
    domain: str
    category: str | None
    department: str
    usage_purpose: str
    data_sensitivity_tier: str
    event_ids: list[str]
    event_count: int
    first_observed_at: str
    last_observed_at: str
    metadata_id: str | None
    facts: RiskFactsOut
    tier: str
    reason_codes: list[str]
    unknown_facts: list[str]
    investigation_flag: bool
    flag_reasons: list[str]
    rule_version: str
    category_method: str | None = None
    interaction_class: str | None = None
    event_types: list[str] | None = None
    distinct_employee_count: int | None = None
    governance_level: str | None = None
    exposure_level: str | None = None
    sensitivity_assumed: bool | None = None
    base_tier: str | None = None
    escalation: str | None = None
    escalation_reason: str | None = None
    tier_raised: bool | None = None
    escalation_event_ids: list[str] | None = None
    purpose_class: str | None = None
    concern_tags: list[str] | None = None
    fact_scope: str | None = None
    framework_refs: list[dict[str, Any]] | None = None
    explanation: str | None = None
    explanation_parts: dict[str, Any] | None = None


@router.get("/{run_id}/assessments")
def read_assessments(
    request: Request,
    run_id: str,
    page: PageParams,
    tier: Tier | None = None,
    flagged: bool | None = None,
    interaction_class: InteractionClass | None = None,
    tool_id: str | None = None,
    department: str | None = None,
) -> Page[AssessmentOut]:
    with request.app.state.engine.connect() as connection:
        run = get_run(connection, run_id)
        if run is None:
            raise AppError(404, "run_not_found", "Analysis Run not found.")
        if run.status != "succeeded":
            raise AppError(
                409, "run_not_succeeded", "Only a succeeded Analysis Run has results."
            )
        rows, total = list_assessments(
            connection,
            run_id,
            page.limit,
            page.offset,
            tier,
            flagged,
            interaction_class,
            tool_id,
            department,
        )
    return Page(
        items=[AssessmentOut(**row) for row in rows],
        total=total,
        limit=page.limit,
        offset=page.offset,
    )
