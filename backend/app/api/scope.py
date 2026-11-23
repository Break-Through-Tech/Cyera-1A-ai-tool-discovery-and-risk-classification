"""Shared read-scope query parameters and response envelope (see ``app.scope``).

An endpoint declares ``scope: ReadScope`` and returns ``ScopeOut.load(...)`` as its
``scope`` field; a record collection returns ``ScopedPage[T]``. Query parameters, each
optional and repeatable where plural: ``batch_ids``, ``run_ids``, ``departments``,
``categories``, ``policy_statuses``, ``risk_tiers``, ``flagged``, ``start``, ``end``.
"""

from collections.abc import Mapping
from datetime import datetime, timedelta
from typing import Annotated, Literal

from fastapi import Depends, Query, Request
from pydantic import AwareDatetime, BaseModel, JsonValue, StringConstraints
from sqlalchemy import Connection

from app.api.batches import ActivityPeriod
from app.api.pagination import Page
from app.api.runs import RunOut
from app.errors import AppError
from app.scope import (
    CATEGORIES,
    CATEGORY_OUTCOMES,
    MATCHING_DEFINITIONS,
    POLICY_STATUSES,
    RISK_TIERS,
    Filters,
    Scope,
    event_time_bound,
    observe_activity,
    resolve_scope,
)

NonEmpty = Annotated[str, StringConstraints(min_length=1)]
CategoryValue = Literal[CATEGORIES + CATEGORY_OUTCOMES]
PolicyStatus = Literal[POLICY_STATUSES]
RiskTier = Literal[RISK_TIERS]


def _read_scope(
    request: Request,
    batch_ids: Annotated[list[NonEmpty], Query()] = [],
    run_ids: Annotated[list[NonEmpty], Query()] = [],
    departments: Annotated[list[NonEmpty], Query()] = [],
    categories: Annotated[list[CategoryValue], Query()] = [],
    policy_statuses: Annotated[list[PolicyStatus], Query()] = [],
    risk_tiers: Annotated[list[RiskTier], Query()] = [],
    flagged: bool | None = None,
    start: AwareDatetime | None = None,
    end: AwareDatetime | None = None,
) -> Scope:
    errors = [
        {"location": ["query", name], "problem": "not_utc"}
        for name, value in (("start", start), ("end", end))
        if value is not None and value.utcoffset() != timedelta(0)
    ]
    if not errors and start is not None and end is not None and start >= end:
        errors.append({"location": ["query", "end"], "problem": "not_after_start"})
    if errors:
        raise AppError(422, "invalid_request", "The request is invalid.", {"errors": errors})
    filters = Filters(
        batch_ids=tuple(batch_ids),
        run_ids=tuple(run_ids),
        departments=tuple(departments),
        categories=tuple(categories),
        policy_statuses=tuple(policy_statuses),
        risk_tiers=tuple(risk_tiers),
        flagged=flagged,
        start=_bound(start),
        end=_bound(end),
    )
    with request.app.state.engine.connect() as connection:
        return resolve_scope(connection, filters)


def _bound(value: datetime | None) -> str | None:
    return None if value is None else event_time_bound(value)


ReadScope = Annotated[Scope, Depends(_read_scope)]


class RunSelectionOut(BaseModel):
    batch_id: str
    run_id: str


class FiltersOut(BaseModel):
    """The scope and filter parameters as requested."""

    batch_ids: list[str]
    run_ids: list[str]
    departments: list[str]
    categories: list[str]
    policy_statuses: list[str]
    risk_tiers: list[str]
    flagged: bool | None


class ObservedRangeOut(BaseModel):
    """First and last matching event times, inclusive; null when nothing matches."""

    first: str | None
    last: str | None


class EventTimeOut(BaseModel):
    """Requested half-open UTC window ``[start, end)``; null bounds are open."""

    start: str | None
    end: str | None
    observed: ObservedRangeOut


class BatchCoverageOut(BaseModel):
    batch_id: str
    activity_period: ActivityPeriod
    event_count: int
    selected_run: RunOut | None
    selected_by: Literal["latest_success", "pinned"] | None
    latest_attempt: RunOut | None


class CoverageWarningOut(BaseModel):
    code: str
    message: str
    batch_id: str | None
    run_id: str | None
    details: dict[str, JsonValue]


class CoverageOut(BaseModel):
    state: Literal["no_batches", "no_successful_runs", "available"]
    batches: list[BatchCoverageOut]
    warnings: list[CoverageWarningOut]


class ScopeOut(BaseModel):
    """What a scoped read covered: Runs used, filters, time bounds, definitions, coverage."""

    selections: list[RunSelectionOut]
    filters: FiltersOut
    event_time: EventTimeOut
    count_definitions: dict[str, str]
    coverage: CoverageOut

    @classmethod
    def load(
        cls, connection: Connection, scope: Scope, definitions: Mapping[str, str]
    ) -> "ScopeOut":
        observed = observe_activity(connection, scope)
        f = scope.filters
        if not scope.batches:
            state = "no_batches"
        elif not scope.selections:
            state = "no_successful_runs"
        else:
            state = "available"
        return cls(
            selections=[RunSelectionOut(batch_id=s.batch_id, run_id=s.run_id) for s in scope.selections],
            filters=FiltersOut(
                batch_ids=list(f.batch_ids),
                run_ids=list(f.run_ids),
                departments=list(f.departments),
                categories=list(f.categories),
                policy_statuses=list(f.policy_statuses),
                risk_tiers=list(f.risk_tiers),
                flagged=f.flagged,
            ),
            event_time=EventTimeOut(
                start=f.start,
                end=f.end,
                observed=ObservedRangeOut(first=observed.first, last=observed.last),
            ),
            count_definitions={**MATCHING_DEFINITIONS, **definitions},
            coverage=CoverageOut(
                state=state,
                batches=[
                    BatchCoverageOut(
                        batch_id=b.batch.batch_id,
                        activity_period=ActivityPeriod(
                            start=b.batch.activity_start, end=b.batch.activity_end
                        ),
                        event_count=b.batch.event_count,
                        selected_run=RunOut.of(b.selected_run) if b.selected_run else None,
                        selected_by=(
                            None if b.selected_run is None
                            else "pinned" if b.pinned else "latest_success"
                        ),
                        latest_attempt=RunOut.of(b.latest_attempt) if b.latest_attempt else None,
                    )
                    for b in scope.batches
                ],
                warnings=[
                    CoverageWarningOut(
                        code=w.code,
                        message=w.message,
                        batch_id=w.batch_id,
                        run_id=w.run_id,
                        details=w.details,
                    )
                    for w in (*scope.warnings, *observed.warnings)
                ],
            ),
        )


class ScopedPage[T](Page[T]):
    """One page of a scoped record collection and the scope it was read under."""

    scope: ScopeOut
