import re
from typing import Annotated, Literal

from fastapi import APIRouter, Query, Request
from pydantic import BaseModel

from app.api.pagination import PageParams
from app.api.runs import RiskFactsOut
from app.api.scope import NonEmpty, ReadScope, ScopedPage, ScopeOut
from app.contexts import CONTEXT_DEFINITIONS, get_context, list_contexts
from app.errors import AppError
from app.runs import get_run

router = APIRouter(tags=["contexts"])

_CONTEXT_NUMBER = re.compile(r"[1-9][0-9]{0,8}")


class ContextOut(BaseModel):
    """One matching Usage Context; run_id and context_number open its stored assessment."""

    run_id: str
    batch_id: str
    context_number: int
    tool_id: str
    application_name: str
    domain: str
    category: str | None
    department: str
    usage_purpose: str
    data_sensitivity_tier: str
    event_count: int
    matching_events: int
    first_observed_at: str
    last_observed_at: str
    policy_status: str
    tier: str
    investigation_flag: bool
    flag_reasons: list[str]
    rule_version: str


class ContextFiltersOut(BaseModel):
    """The context-only filters as requested; the shared ones are in ``scope.filters``."""

    tool_ids: list[str]


class ContextPage(ScopedPage[ContextOut]):
    context_filters: ContextFiltersOut


@router.get("/contexts")
def read_contexts(
    request: Request,
    scope: ReadScope,
    page: PageParams,
    tool_ids: Annotated[list[NonEmpty], Query()] = [],
) -> ContextPage:
    with request.app.state.engine.connect() as connection:
        rows, total = list_contexts(connection, scope, page.limit, page.offset, tool_ids)
        scope_out = ScopeOut.load(connection, scope, CONTEXT_DEFINITIONS)
    return ContextPage(
        items=[ContextOut(**row) for row in rows],
        total=total,
        limit=page.limit,
        offset=page.offset,
        scope=scope_out,
        context_filters=ContextFiltersOut(tool_ids=tool_ids),
    )


class ApplicationReferenceOut(BaseModel):
    """The resolved Tool the context belongs to; opens its Run-pinned application detail."""

    run_id: str
    subject_kind: Literal["tool"]
    subject_id: str
    application_name: str
    domain: str
    category: str | None


class OriginalScopeOut(BaseModel):
    """The grouping and observed window the context was assessed on, not a request's filters."""

    department: str
    usage_purpose: str
    data_sensitivity_tier: str
    first_observed_at: str
    last_observed_at: str


class AssessmentDetailOut(BaseModel):
    """The stored Contextual Risk Assessment; facts come from ``metadata_id``'s snapshot."""

    metadata_id: str | None
    facts: RiskFactsOut
    tier: str
    reason_codes: list[str]
    unknown_facts: list[str]
    rule_version: str


class InvestigationOut(BaseModel):
    flagged: bool
    reasons: list[str]


class EventsQueryOut(BaseModel):
    run_ids: list[str]
    context_number: int


class ContextEventsOut(BaseModel):
    """The context's Activity Events: ``GET {path}`` with ``query`` pages them."""

    count: int
    path: Literal["/events"]
    query: EventsQueryOut


class ContextDetailOut(BaseModel):
    run_id: str
    batch_id: str
    context_number: int
    application: ApplicationReferenceOut
    original_scope: OriginalScopeOut
    assessment: AssessmentDetailOut
    investigation: InvestigationOut
    events: ContextEventsOut


@router.get("/runs/{run_id}/contexts/{context_id}")
def read_context(request: Request, run_id: str, context_id: str) -> ContextDetailOut:
    if not _CONTEXT_NUMBER.fullmatch(context_id):
        raise AppError(
            422,
            "invalid_request",
            "The request is invalid.",
            {"errors": [{"location": ["path", "context_id"], "problem": "invalid_context_number"}]},
        )
    with request.app.state.engine.connect() as connection:
        run = get_run(connection, run_id)
        if run is None:
            raise AppError(404, "run_not_found", "Analysis Run not found.")
        if run.status != "succeeded":
            raise AppError(
                409, "run_not_succeeded", "Only a succeeded Analysis Run has results."
            )
        context = get_context(connection, run_id, int(context_id))
    if context is None:
        raise AppError(
            404, "context_not_found", "Usage Context not found in this Analysis Run."
        )
    c = context
    return ContextDetailOut(
        run_id=run_id,
        batch_id=run.batch_id,
        context_number=c["context_number"],
        application=ApplicationReferenceOut(
            run_id=run_id,
            subject_kind="tool",
            subject_id=c["tool_id"],
            application_name=c["application_name"],
            domain=c["domain"],
            category=c["category"],
        ),
        original_scope=OriginalScopeOut(**{k: c[k] for k in OriginalScopeOut.model_fields}),
        assessment=AssessmentDetailOut(**{k: c[k] for k in AssessmentDetailOut.model_fields}),
        investigation=InvestigationOut(flagged=c["investigation_flag"], reasons=c["flag_reasons"]),
        events=ContextEventsOut(
            count=c["event_count"],
            path="/events",
            query=EventsQueryOut(run_ids=[run_id], context_number=c["context_number"]),
        ),
    )
