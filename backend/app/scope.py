"""Read scope: which Analysis Runs a read uses and which of their results match its filters.

API contract (#20, "Read scope, overview, and pagination"): by default each Batch contributes
its latest succeeded Run, optionally restricted by ``batch_ids``; ``run_ids`` pins succeeded
Runs, at most one per Batch. Without ``batch_ids`` the pinned Runs' Batches are the scope.
Filters combine with AND and the values of one filter with OR.

How a read endpoint uses it:

1. Declare ``scope: ReadScope`` (``app.api.scope``). FastAPI validates the shared query
   parameters and ``resolve_scope`` turns them into a ``Scope``, raising the contract's
   404/409/422 errors.
2. Read only the selected Runs' results:
   - Usage Contexts: ``select(...).where(*context_conditions(scope))`` on
     ``usage_context_assessments``.
   - Activity Events: ``scoped_events(scope)`` is a subquery of the matching events, each
     with its Run's Tool Candidate, AI and Category outcomes and Usage Context.
3. Return ``ScopeOut.load(connection, scope, definitions)`` as the response's ``scope``.
"""

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from typing import Any, NoReturn

from sqlalchemy import (
    CTE,
    ColumnElement,
    Connection,
    Subquery,
    and_,
    distinct,
    false,
    func,
    or_,
    select,
    true,
    tuple_,
)

from app.batches import Batch
from app.db.tables import (
    activity_events,
    ai_determinations,
    analysis_runs,
    batches,
    category_classifications,
    tool_candidates,
    usage_context_assessments,
)
from app.errors import AppError
from app.runs import Run

RISK_TIERS = ("High", "Medium", "Lower", "unresolved")
POLICY_STATUSES = ("approved", "unapproved", "unknown")
# The 14 supplied AIToolBuzz Categories (CONTEXT.md, "Category").
CATEGORIES = (
    "Ai And Machine Learning",
    "Business And Finance",
    "Communication And Support",
    "Creative And Entertainment",
    "Data And Analytics",
    "Education And Learning",
    "Industry Specific",
    "Marketing And Sales",
    "Media And Content Creation",
    "Operations And Management",
    "Personal And Lifestyle",
    "Security And Privacy",
    "Specialized Technologies",
    "Technology And Development",
)
# Category filter values that select a Category Classification outcome instead of a Category.
CATEGORY_OUTCOMES = ("unresolved", "inapplicable")

# Every scoped response carries these alongside its own count definitions.
MATCHING_DEFINITIONS = {
    "matching_activity": (
        "Activity Events of each selected Run's Batch, counted as supplied: an event ID "
        "supplied in several Batches counts once per Batch. An event matches when it is in "
        "the event-time window [start, end), is in a selected department, and its Tool "
        "Candidate's Category Classification is a selected Category or outcome. With a Policy "
        "Status, risk tier or investigation-flag filter, only events of Usage Contexts "
        "matching every one of those filters match, so non-AI and unresolved activity drops out."
    ),
    "matching_contexts": (
        "Stored Usage Context assessments of the selected Runs. A context matches the "
        "event-time and department filters when at least one of its Activity Events does, "
        "and the other filters by its own stored Category, Policy Status, tier and "
        "investigation flag. Assessments are not recalculated for the filtered period."
    ),
}

_EVENT_DATA = (
    "occurred_at",
    "employee_id",
    "department",
    "job_role",
    "application_name",
    "domain",
    "event_type",
    "usage_purpose",
    "data_sensitivity_tier",
)
_OVERLAP_SAMPLE = 20


@dataclass(frozen=True)
class Filters:
    """Validated read parameters as requested; empty tuples and ``None`` restrict nothing.

    ``start`` (inclusive) and ``end`` (exclusive) are UTC timestamps in the stored
    ``YYYY-MM-DDTHH:MM:SSZ`` form (see ``event_time_bound``).
    """

    batch_ids: tuple[str, ...] = ()
    run_ids: tuple[str, ...] = ()
    departments: tuple[str, ...] = ()
    categories: tuple[str, ...] = ()
    policy_statuses: tuple[str, ...] = ()
    risk_tiers: tuple[str, ...] = ()
    flagged: bool | None = None
    start: str | None = None
    end: str | None = None

    @property
    def selects_contexts(self) -> bool:
        """Whether a context-only filter restricts activity to matching Usage Contexts."""
        return bool(self.policy_statuses or self.risk_tiers) or self.flagged is not None


@dataclass(frozen=True)
class RunSelection:
    batch_id: str
    run_id: str


@dataclass(frozen=True)
class BatchCoverage:
    """One Batch in scope: the Run whose findings it contributes, if any, and its latest attempt."""

    batch: Batch
    selected_run: Run | None
    pinned: bool
    latest_attempt: Run | None


@dataclass(frozen=True)
class CoverageWarning:
    code: str
    message: str
    batch_id: str | None = None
    run_id: str | None = None
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Scope:
    filters: Filters
    batches: tuple[BatchCoverage, ...]
    warnings: tuple[CoverageWarning, ...]

    @property
    def selections(self) -> tuple[RunSelection, ...]:
        return tuple(
            RunSelection(b.batch.batch_id, b.selected_run.run_id)
            for b in self.batches
            if b.selected_run is not None
        )

    @property
    def run_ids(self) -> tuple[str, ...]:
        return tuple(selection.run_id for selection in self.selections)


@dataclass(frozen=True)
class ObservedActivity:
    """The matching activity's actual time range and its cross-Batch overlap warnings."""

    first: str | None
    last: str | None
    warnings: tuple[CoverageWarning, ...]


def event_time_bound(value: datetime) -> str:
    """A UTC instant as a stored timestamp, rounded up to a whole second.

    Events have whole-second times, so rounding up keeps both ``event >= start`` and
    ``event < end`` exact.
    """
    value = value.astimezone(UTC).replace(tzinfo=None)
    if value.microsecond:
        value = value.replace(microsecond=0) + timedelta(seconds=1)
    return value.isoformat(timespec="seconds") + "Z"


def resolve_scope(connection: Connection, filters: Filters) -> Scope:
    """Select each in-scope Batch's Run, or raise the contract's 404/409/422 ``AppError``."""
    requested = _load_batches(connection, filters.batch_ids) if filters.batch_ids else []
    found_batches = {b.batch_id for b in requested}
    _reject_missing("batch_ids", filters.batch_ids, found_batches, "batch_not_found", "Batch not found.")
    pinned = {
        run.run_id: run
        for run in _load_runs(connection, analysis_runs.c.run_id.in_(filters.run_ids))
    }
    _reject_missing("run_ids", filters.run_ids, set(pinned), "run_not_found", "Analysis Run not found.")
    pinned_by_batch = _reject_contradictions(filters, pinned)
    not_succeeded = [
        index
        for index, run_id in enumerate(filters.run_ids)
        if pinned[run_id].status != "succeeded"
    ]
    if not_succeeded:
        _raise(
            409,
            "run_not_succeeded",
            "Only a succeeded Analysis Run has results.",
            "run_ids",
            not_succeeded,
            "not_succeeded",
        )

    if filters.batch_ids:
        in_scope = requested
    elif pinned_by_batch:
        in_scope = _load_batches(connection, tuple(pinned_by_batch))
    else:
        in_scope = _load_batches(connection, None)
    runs_by_batch: dict[str, list[Run]] = {b.batch_id: [] for b in in_scope}
    for run in sorted(
        _load_runs(connection, analysis_runs.c.batch_id.in_(runs_by_batch)),
        key=lambda r: r.attempt_number,
        reverse=True,
    ):
        runs_by_batch[run.batch_id].append(run)

    covered = []
    for batch in in_scope:
        history = runs_by_batch[batch.batch_id]
        pin = pinned_by_batch.get(batch.batch_id)
        latest_success = next((r for r in history if r.status == "succeeded"), None)
        covered.append(
            BatchCoverage(
                batch=batch,
                selected_run=pin or latest_success,
                pinned=pin is not None,
                latest_attempt=history[0] if history else None,
            )
        )
    selected = [b.selected_run.run_id for b in covered if b.selected_run is not None]
    with_stage_results = set(
        connection.execute(
            select(tool_candidates.c.run_id).where(tool_candidates.c.run_id.in_(selected)).distinct()
        ).scalars()
    )
    return Scope(
        filters=filters,
        batches=tuple(covered),
        warnings=_coverage_warnings(covered, runs_by_batch, with_stage_results),
    )


def context_conditions(scope: Scope) -> list[ColumnElement[bool]]:
    """Where-clauses selecting the matching rows of ``usage_context_assessments``."""
    table = usage_context_assessments
    filters = scope.filters
    where = [table.c.run_id.in_(scope.run_ids), *_context_only_conditions(filters)]
    if filters.departments:
        where.append(table.c.department.in_(filters.departments))
    if filters.categories:
        named = [c for c in filters.categories if c not in CATEGORY_OUTCOMES]
        # A context is an AI Tool's, so its Category is assigned or, when null, unresolved.
        where.append(
            or_(
                table.c.category.in_(named),
                table.c.category.is_(None) if "unresolved" in filters.categories else false(),
            )
        )
    if filters.start is not None or filters.end is not None:
        where.append(_has_event_in_window(scope))
    return where


def scoped_events(scope: Scope) -> Subquery:
    """Matching Activity Events, one row per event and selected Run.

    Columns: every ``activity_events`` column, ``run_id``, ``candidate_number``,
    ``identity_outcome``, ``tool_id``, ``ai_determination``, ``category_outcome``,
    ``category`` and ``context_number`` (null when the event is in no Usage Context).
    A selected Run without saved Tool Candidates contributes no rows.
    """
    filters = scope.filters
    member = _candidate_events(scope.run_ids)
    context = _context_events(scope.run_ids)
    query = (
        select(
            *activity_events.c,
            member.c.run_id,
            member.c.candidate_number,
            tool_candidates.c.outcome.label("identity_outcome"),
            tool_candidates.c.tool_id,
            ai_determinations.c.determination.label("ai_determination"),
            category_classifications.c.outcome.label("category_outcome"),
            category_classifications.c.category,
            context.c.context_number,
        )
        .select_from(member)
        .join(activity_events, _same_event(member))
        .join(
            tool_candidates,
            and_(
                tool_candidates.c.run_id == member.c.run_id,
                tool_candidates.c.candidate_number == member.c.candidate_number,
            ),
        )
        .join(ai_determinations, _same_candidate(ai_determinations))
        .join(category_classifications, _same_candidate(category_classifications))
        .join(
            context,
            and_(context.c.run_id == member.c.run_id, context.c.event_id == member.c.event_id),
            isouter=not filters.selects_contexts,
        )
    )
    where = _event_conditions(filters)
    if filters.categories:
        where.append(_category_condition(filters.categories))
    if filters.selects_contexts:
        table = usage_context_assessments
        query = query.join(
            table,
            and_(
                table.c.run_id == context.c.run_id,
                table.c.context_number == context.c.context_number,
            ),
        )
        where.extend(_context_only_conditions(filters))
    return query.where(*where).subquery("scoped_events")


def observe_activity(connection: Connection, scope: Scope) -> ObservedActivity:
    """The first and last matching event times, and warnings for event IDs counted in several Batches."""
    events = scoped_events(scope)
    first, last = connection.execute(
        select(func.min(events.c.occurred_at), func.max(events.c.occurred_at))
    ).one()
    if len(scope.run_ids) < 2:
        return ObservedActivity(first, last, ())
    repeated = connection.execute(
        select(
            events.c.event_id,
            func.count(distinct(func.json_array(*(events.c[n] for n in _EVENT_DATA)))),
            func.group_concat(events.c.batch_id),
        )
        .group_by(events.c.event_id)
        .having(func.count() > 1)
        .order_by(events.c.event_id)
    ).all()
    warnings = []
    for code, identical, message in (
        (
            "exact_event_overlap",
            True,
            "The same event ID with identical event data was supplied in several Batches; "
            "counts include it once per Batch.",
        ),
        (
            "conflicting_event_ids",
            False,
            "The same event ID with different event data was supplied in several Batches; "
            "they are counted separately and are not proven duplicates.",
        ),
    ):
        found = [row for row in repeated if (row[1] == 1) == identical]
        if found:
            warnings.append(
                CoverageWarning(
                    code,
                    message,
                    details={
                        "event_id_count": len(found),
                        "event_ids": [row[0] for row in found[:_OVERLAP_SAMPLE]],
                        "batch_ids": sorted({b for row in found for b in row[2].split(",")}),
                    },
                )
            )
    return ObservedActivity(first, last, tuple(warnings))


def _load_batches(connection: Connection, batch_ids: Sequence[str] | None) -> list[Batch]:
    """Batches in directory order (newest upload first, ties by ID); every Batch for ``None``."""
    query = select(*(batches.c[name] for name in Batch.__dataclass_fields__))
    if batch_ids is not None:
        query = query.where(batches.c.batch_id.in_(batch_ids))
    rows = connection.execute(
        query.order_by(batches.c.uploaded_at.desc(), batches.c.batch_id)
    ).mappings()
    return [Batch(**row) for row in rows]


def _load_runs(connection: Connection, where: ColumnElement[bool]) -> list[Run]:
    return [Run(**row) for row in connection.execute(select(analysis_runs).where(where)).mappings()]


def _reject_missing(
    parameter: str, requested: Sequence[str], found: set[str], code: str, message: str
) -> None:
    missing = [index for index, value in enumerate(requested) if value not in found]
    if missing:
        _raise(404, code, message, parameter, missing, "not_found")


def _reject_contradictions(filters: Filters, pinned: dict[str, Run]) -> dict[str, Run]:
    """Pinned Runs by Batch; two Runs of one Batch, or a Run outside ``batch_ids``, is a 422."""
    by_batch: dict[str, Run] = {}
    errors = []
    for index, run_id in enumerate(filters.run_ids):
        run = pinned[run_id]
        if filters.batch_ids and run.batch_id not in filters.batch_ids:
            errors.append((index, "outside_selected_batches"))
        elif by_batch.setdefault(run.batch_id, run).run_id != run_id:
            errors.append((index, "multiple_runs_for_batch"))
    if errors:
        raise AppError(
            422,
            "invalid_request",
            "The request is invalid.",
            {
                "errors": [
                    {"location": ["query", "run_ids", index], "problem": problem}
                    for index, problem in errors
                ]
            },
        )
    return by_batch


def _raise(
    status: int, code: str, message: str, parameter: str, indexes: Sequence[int], problem: str
) -> NoReturn:
    raise AppError(
        status,
        code,
        message,
        {
            "errors": [
                {"location": ["query", parameter, index], "problem": problem}
                for index in indexes
            ]
        },
    )


def _coverage_warnings(
    covered: Sequence[BatchCoverage],
    runs_by_batch: dict[str, list[Run]],
    with_stage_results: set[str],
) -> tuple[CoverageWarning, ...]:
    """``runs_by_batch`` lists each Batch's Runs newest attempt first."""
    warnings = []
    if not covered:
        warnings.append(
            CoverageWarning("no_batches", "No Batch has been uploaded, so there are no findings.")
        )
    for item in covered:
        batch_id, selected, latest = item.batch.batch_id, item.selected_run, item.latest_attempt
        if selected is None:
            warnings.append(
                CoverageWarning(
                    "no_successful_run",
                    "This Batch has no succeeded Analysis Run, so it contributes no findings.",
                    batch_id,
                    latest.run_id if latest else None,
                    {"status": latest.status} if latest else {},
                )
            )
            continue
        if latest.attempt_number > selected.attempt_number and latest.status != "succeeded":
            warnings.append(
                CoverageWarning(
                    "newer_attempt_not_succeeded",
                    f"A newer Analysis Run of this Batch is {latest.status}; findings come "
                    "from the selected earlier Run.",
                    batch_id,
                    latest.run_id,
                    {"status": latest.status},
                )
            )
        latest_success = next(r for r in runs_by_batch[batch_id] if r.status == "succeeded")
        if latest_success.attempt_number > selected.attempt_number:
            warnings.append(
                CoverageWarning(
                    "newer_successful_run",
                    "This read is pinned to an earlier Run; a newer succeeded Run exists.",
                    batch_id,
                    latest_success.run_id,
                )
            )
        if selected.run_id not in with_stage_results:
            warnings.append(
                CoverageWarning(
                    "run_without_stage_results",
                    "This Run saved no Tool Candidates, so its Activity Events are not "
                    "counted; its Usage Contexts are.",
                    batch_id,
                    selected.run_id,
                )
            )
    selected_runs = [b.selected_run for b in covered if b.selected_run is not None]
    names = sorted({name for run in selected_runs for name in run.versions})
    differing = [
        name for name in names if len({run.versions.get(name) for run in selected_runs}) > 1
    ]
    if differing:
        warnings.append(
            CoverageWarning(
                "version_differences",
                "The selected Runs used different model, data or rule versions.",
                details={"versions": differing},
            )
        )
    return tuple(warnings)


def _event_conditions(filters: Filters) -> list[ColumnElement[bool]]:
    where = []
    if filters.start is not None:
        where.append(activity_events.c.occurred_at >= filters.start)
    if filters.end is not None:
        where.append(activity_events.c.occurred_at < filters.end)
    if filters.departments:
        where.append(activity_events.c.department.in_(filters.departments))
    return where


def _context_only_conditions(filters: Filters) -> list[ColumnElement[bool]]:
    table = usage_context_assessments
    where = []
    if filters.policy_statuses:
        where.append(table.c.facts["policy_status"].as_string().in_(filters.policy_statuses))
    if filters.risk_tiers:
        where.append(table.c.tier.in_(filters.risk_tiers))
    if filters.flagged is not None:
        where.append(table.c.investigation_flag == filters.flagged)
    return where


def _category_condition(categories: Sequence[str]) -> ColumnElement[bool]:
    outcome, category = category_classifications.c.outcome, category_classifications.c.category
    named = [c for c in categories if c not in CATEGORY_OUTCOMES]
    return or_(
        and_(outcome == "assigned", category.in_(named)),
        outcome.in_([c for c in categories if c in CATEGORY_OUTCOMES]),
    )


# Event IDs are stored as JSON arrays. Expanding them once into materialized CTEs keeps
# SQLite from re-scanning an array per Activity Event. Each CTE is cached per Run set so a
# statement that uses several helpers for one scope references one CTE, not two of a name.


@lru_cache(maxsize=64)
def _candidate_events(run_ids: tuple[str, ...]) -> CTE:
    """``(run_id, candidate_number, batch_id, event_id)`` of the Runs' Tool Candidates."""
    event = func.json_each(tool_candidates.c.event_ids).table_valued("value", name="candidate_event")
    return (
        select(
            tool_candidates.c.run_id,
            tool_candidates.c.candidate_number,
            analysis_runs.c.batch_id,
            event.c.value.label("event_id"),
        )
        .select_from(tool_candidates)
        .join(event, true())
        .join(analysis_runs, analysis_runs.c.run_id == tool_candidates.c.run_id)
        .where(tool_candidates.c.run_id.in_(run_ids))
        .cte("candidate_events")
        .prefix_with("MATERIALIZED")
    )


@lru_cache(maxsize=64)
def _context_events(run_ids: tuple[str, ...]) -> CTE:
    """``(run_id, context_number, batch_id, event_id)`` of the Runs' Usage Contexts."""
    table = usage_context_assessments
    event = func.json_each(table.c.event_ids).table_valued("value", name="context_event")
    return (
        select(
            table.c.run_id,
            table.c.context_number,
            analysis_runs.c.batch_id,
            event.c.value.label("event_id"),
        )
        .select_from(table)
        .join(event, true())
        .join(analysis_runs, analysis_runs.c.run_id == table.c.run_id)
        .where(table.c.run_id.in_(run_ids))
        .cte("context_events")
        .prefix_with("MATERIALIZED")
    )


def _has_event_in_window(scope: Scope) -> ColumnElement[bool]:
    table = usage_context_assessments
    context = _context_events(scope.run_ids)
    filters = scope.filters
    within = [activity_events.c.occurred_at >= filters.start] if filters.start else []
    if filters.end is not None:
        within.append(activity_events.c.occurred_at < filters.end)
    return tuple_(table.c.run_id, table.c.context_number).in_(
        select(context.c.run_id, context.c.context_number)
        .join(activity_events, _same_event(context))
        .where(*within)
    )


def _same_event(member: CTE) -> ColumnElement[bool]:
    return and_(
        activity_events.c.batch_id == member.c.batch_id,
        activity_events.c.event_id == member.c.event_id,
    )


def _same_candidate(table) -> ColumnElement[bool]:
    return and_(
        table.c.run_id == tool_candidates.c.run_id,
        table.c.candidate_number == tool_candidates.c.candidate_number,
    )
