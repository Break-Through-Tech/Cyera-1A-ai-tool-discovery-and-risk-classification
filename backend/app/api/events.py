from typing import Annotated, Literal

from fastapi import APIRouter, Query, Request
from pydantic import BaseModel

from app.api.pagination import PageParams
from app.api.scope import NonEmpty, ReadScope, ScopedPage, ScopeOut
from app.events import EVENT_DEFINITIONS, EventFilters, check_event_filters, list_events
from app.overview import AI_DETERMINATIONS, IDENTITY_OUTCOMES

router = APIRouter(tags=["events"])

AiDetermination = Literal[AI_DETERMINATIONS]
IdentityOutcome = Literal[IDENTITY_OUTCOMES]


class EventOut(BaseModel):
    """One matching Activity Event as supplied, and what its Run made of it.

    run_id with subject_kind and subject_id opens its application; run_id with
    context_number its Usage Context, when it is in one.
    """

    batch_id: str
    event_id: str
    occurred_at: str
    employee_id: str
    department: str
    job_role: str | None
    application_name: str
    domain: str
    event_type: str | None
    usage_purpose: str | None
    data_sensitivity_tier: str | None
    run_id: str
    candidate_number: int
    subject_kind: Literal["tool", "candidate"]
    subject_id: str
    identity_outcome: str
    tool_id: str | None
    ai_determination: str
    category_outcome: str
    category: str | None
    context_number: int | None


class EventFiltersOut(BaseModel):
    """The event-only filters as requested; the shared ones are in ``scope.filters``."""

    ai_determinations: list[str]
    identity_outcomes: list[str]
    tool_ids: list[str]
    candidate_number: int | None
    context_number: int | None


class EventPage(ScopedPage[EventOut]):
    event_filters: EventFiltersOut


@router.get("/events")
def read_events(
    request: Request,
    scope: ReadScope,
    page: PageParams,
    ai_determinations: Annotated[list[AiDetermination], Query()] = [],
    identity_outcomes: Annotated[list[IdentityOutcome], Query()] = [],
    tool_ids: Annotated[list[NonEmpty], Query()] = [],
    candidate_number: Annotated[int | None, Query(ge=1)] = None,
    context_number: Annotated[int | None, Query(ge=1)] = None,
) -> EventPage:
    filters = EventFilters(
        ai_determinations=tuple(ai_determinations),
        identity_outcomes=tuple(identity_outcomes),
        tool_ids=tuple(tool_ids),
        candidate_number=candidate_number,
        context_number=context_number,
    )
    with request.app.state.engine.connect() as connection:
        check_event_filters(connection, scope, filters)
        rows, total = list_events(connection, scope, filters, page.limit, page.offset)
        scope_out = ScopeOut.load(connection, scope, EVENT_DEFINITIONS)
    return EventPage(
        items=[EventOut(**row) for row in rows],
        total=total,
        limit=page.limit,
        offset=page.offset,
        scope=scope_out,
        event_filters=EventFiltersOut(
            ai_determinations=ai_determinations,
            identity_outcomes=identity_outcomes,
            tool_ids=tool_ids,
            candidate_number=candidate_number,
            context_number=context_number,
        ),
    )
