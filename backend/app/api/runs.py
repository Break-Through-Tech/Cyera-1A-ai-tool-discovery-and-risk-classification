from typing import Literal

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


class AssessmentOut(BaseModel):
    """One Usage Context of a succeeded Run and its contextual-risk assessment."""

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


@router.get("/{run_id}/assessments")
def read_assessments(
    request: Request,
    run_id: str,
    page: PageParams,
    tier: Literal["High", "Medium", "Lower", "unresolved"] | None = None,
    flagged: bool | None = None,
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
            connection, run_id, page.limit, page.offset, tier, flagged
        )
    return Page(
        items=[AssessmentOut(**row) for row in rows],
        total=total,
        limit=page.limit,
        offset=page.offset,
    )
