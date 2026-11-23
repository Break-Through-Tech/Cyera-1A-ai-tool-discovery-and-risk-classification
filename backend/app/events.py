"""Activity Event drill-down: the scope's matching events and what their Run made of them.

Beyond the shared scope filters, events narrow by AI Determination, Identity Resolution
outcome and Tool, and, with exactly one pinned Run, by Tool Candidate or Usage Context, so
every overview count, application and Usage Context opens the events behind it.
"""

from collections.abc import Mapping
from dataclasses import dataclass

from sqlalchemy import ColumnElement, Connection, func, select

from app.db.tables import tool_candidates, usage_context_assessments
from app.errors import AppError
from app.pipeline.usage_contexts import RESOLVED_OUTCOMES
from app.scope import Scope, scoped_events

EVENT_DEFINITIONS = {
    "events": (
        "One row per matching Activity Event and selected Run (see matching_activity), "
        "narrowed by the event filters: its Tool Candidate's AI Determination, Identity "
        "Resolution outcome, Tool, or number, or its Usage Context. Ordered by event time, "
        "Batch ID and event ID."
    ),
}


@dataclass(frozen=True)
class EventFilters:
    """Event-only filters; ``candidate_number`` and ``context_number`` need one pinned Run."""

    ai_determinations: tuple[str, ...] = ()
    identity_outcomes: tuple[str, ...] = ()
    tool_ids: tuple[str, ...] = ()
    candidate_number: int | None = None
    context_number: int | None = None


# Run-pinned event filters: (parameter, table holding the reference, error code, noun).
_REFERENCES = (
    ("candidate_number", tool_candidates, "candidate_not_found", "Tool Candidate"),
    ("context_number", usage_context_assessments, "context_not_found", "Usage Context"),
)


def check_event_filters(connection: Connection, scope: Scope, filters: EventFilters) -> None:
    """Raise a 422 when a Run-pinned reference lacks exactly one ``run_ids``, or a 404 when
    the referenced Tool Candidate or Usage Context is not in that Run."""
    requested = [ref for ref in _REFERENCES if getattr(filters, ref[0]) is not None]
    if requested and len(scope.filters.run_ids) != 1:
        raise AppError(
            422,
            "invalid_request",
            "The request is invalid.",
            {
                "errors": [
                    {"location": ["query", name], "problem": "requires_one_run_id"}
                    for name, *_ in requested
                ]
            },
        )
    for name, table, code, noun in requested:
        found = connection.execute(
            select(func.count()).select_from(table).where(
                table.c.run_id == scope.filters.run_ids[0],
                table.c[name] == getattr(filters, name),
            )
        ).scalar_one()
        if not found:
            raise AppError(
                404,
                code,
                f"{noun} not found in this Analysis Run.",
                {"errors": [{"location": ["query", name], "problem": "not_found"}]},
            )


def list_events(
    connection: Connection, scope: Scope, filters: EventFilters, limit: int, offset: int
) -> tuple[list[dict], int]:
    """One page of the scope's matching Activity Events and their total; see ``EVENT_DEFINITIONS``.

    Each row has the ``scoped_events`` columns and the application subject
    (``subject_kind``, ``subject_id``) its Tool Candidate belongs to.
    """
    events = scoped_events(scope)
    where: list[ColumnElement[bool]] = []
    if filters.ai_determinations:
        where.append(events.c.ai_determination.in_(filters.ai_determinations))
    if filters.identity_outcomes:
        where.append(events.c.identity_outcome.in_(filters.identity_outcomes))
    if filters.tool_ids:
        where.append(events.c.tool_id.in_(filters.tool_ids))
    if filters.candidate_number is not None:
        where.append(events.c.candidate_number == filters.candidate_number)
    if filters.context_number is not None:
        where.append(events.c.context_number == filters.context_number)
    total = connection.execute(select(func.count()).select_from(events).where(*where)).scalar_one()
    rows = connection.execute(
        select(events)
        .where(*where)
        .order_by(events.c.occurred_at, events.c.batch_id, events.c.event_id)
        .limit(limit)
        .offset(offset)
    ).mappings().all()
    return [{**row, **_subject(row)} for row in rows], total


def _subject(row: Mapping) -> dict[str, str]:
    """The application of an event's Tool Candidate, addressed as ``app.applications`` does."""
    if row["identity_outcome"] in RESOLVED_OUTCOMES:
        return {"subject_kind": "tool", "subject_id": row["tool_id"]}
    return {"subject_kind": "candidate", "subject_id": str(row["candidate_number"])}
