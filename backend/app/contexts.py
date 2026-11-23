"""Usage Contexts of the selected Runs: the scoped listing and one stored assessment.

A Usage Context is addressed by its Run and ``context_number``. Its Activity Events are
paged through ``GET /events`` with ``run_ids`` and ``context_number`` (``app.events``)
rather than embedded.
"""

from collections.abc import Sequence

from sqlalchemy import Connection, case, func, select, tuple_

from app.db.tables import usage_context_assessments
from app.scope import RISK_TIERS, Scope, context_conditions, scoped_events

CONTEXT_DEFINITIONS = {
    "contexts": (
        "One row per matching Usage Context (see matching_contexts), narrowed to the given "
        "Tools when tool_ids is set. Ordered by stored tier (High, Medium, Lower, "
        "unresolved), then Run ID and context number."
    ),
    "contexts.event_count": (
        "Every Activity Event the context was assessed on; stored, regardless of filters."
    ),
    "contexts.matching_events": (
        "The context's matching Activity Events (see matching_activity): the total of "
        "GET /events with the same scope, run_ids and context_number."
    ),
}

_TABLE = usage_context_assessments
_POLICY_STATUS = _TABLE.c.facts["policy_status"].as_string()
_LIST_COLUMNS = (
    "run_id",
    "context_number",
    "tool_id",
    "application_name",
    "domain",
    "category",
    "department",
    "usage_purpose",
    "data_sensitivity_tier",
    "event_count",
    "first_observed_at",
    "last_observed_at",
    "tier",
    "investigation_flag",
    "flag_reasons",
    "rule_version",
)


def list_contexts(
    connection: Connection,
    scope: Scope,
    limit: int,
    offset: int,
    tool_ids: Sequence[str] = (),
) -> tuple[list[dict], int]:
    """One page of the scope's matching Usage Contexts and their total; see ``CONTEXT_DEFINITIONS``.

    Each row has the ``_LIST_COLUMNS``, ``policy_status``, ``batch_id`` and ``matching_events``.
    """
    where = context_conditions(scope)
    if tool_ids:
        where.append(_TABLE.c.tool_id.in_(tool_ids))
    total = connection.execute(
        select(func.count()).select_from(_TABLE).where(*where)
    ).scalar_one()
    tier_rank = case(
        {tier: rank for rank, tier in enumerate(RISK_TIERS)},
        value=_TABLE.c.tier,
        else_=len(RISK_TIERS),
    )
    rows = connection.execute(
        select(*(_TABLE.c[name] for name in _LIST_COLUMNS), _POLICY_STATUS.label("policy_status"))
        .where(*where)
        .order_by(tier_rank, _TABLE.c.run_id, _TABLE.c.context_number)
        .limit(limit)
        .offset(offset)
    ).mappings().all()
    keys = [(row["run_id"], row["context_number"]) for row in rows]
    matching = _matching_events(connection, scope, keys)
    batch_ids = {s.run_id: s.batch_id for s in scope.selections}
    return [
        {
            **row,
            "batch_id": batch_ids[row["run_id"]],
            "matching_events": matching.get(key, 0),
        }
        for row, key in zip(rows, keys, strict=True)
    ], total


def get_context(connection: Connection, run_id: str, context_number: int) -> dict | None:
    """One stored Usage Context assessment of a Run without its event IDs, if it exists."""
    row = connection.execute(
        select(*(c for c in _TABLE.c if c.name != "event_ids")).where(
            _TABLE.c.run_id == run_id, _TABLE.c.context_number == context_number
        )
    ).mappings().one_or_none()
    return dict(row) if row else None


def _matching_events(
    connection: Connection, scope: Scope, keys: Sequence[tuple[str, int]]
) -> dict[tuple[str, int], int]:
    """Matching Activity Events per ``(run_id, context_number)`` of ``keys``."""
    if not keys:
        return {}
    events = scoped_events(scope)
    rows = connection.execute(
        select(events.c.run_id, events.c.context_number, func.count())
        .where(tuple_(events.c.run_id, events.c.context_number).in_(keys))
        .group_by(events.c.run_id, events.c.context_number)
    )
    return {(run_id, number): count for run_id, number, count in rows}
