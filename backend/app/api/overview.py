from typing import Literal

from fastapi import APIRouter, Request
from pydantic import BaseModel

from app.api.scope import ReadScope, ScopeOut
from app.overview import DEFINITIONS, overview

router = APIRouter(tags=["overview"])


class HeadlineOut(BaseModel):
    known_ai_tools: int
    ai_positive_events: int
    ai_unresolved_events: int
    flagged_contexts: int


class ActivityOut(BaseModel):
    events: int
    by_ai_determination: dict[str, int]
    ai_positive_by_identity: dict[str, int]


class StageCountOut(BaseModel):
    events: int
    candidates: int


class UnresolvedStagesOut(BaseModel):
    identity: StageCountOut
    ai_determination: StageCountOut
    category: StageCountOut


class BatchFindingsOut(BaseModel):
    batch_id: str
    run_id: str
    events: int
    ai_positive_events: int
    known_ai_tools: int
    observed_ai_tools: int
    flagged_contexts: int


class DepartmentOut(BaseModel):
    department: str
    events: int
    ai_positive_events: int
    flagged_contexts: int


class CategoryOut(BaseModel):
    outcome: Literal["assigned", "unresolved", "inapplicable"]
    category: str | None
    ai_positive_events: int


class TrendPointOut(BaseModel):
    """One UTC bucket ``[start, end)``; counts are null when no selected Batch covers it."""

    start: str
    end: str
    covered: bool
    ai_positive_events: int | None
    known_ai_tools_first_observed: int | None


class TrendOut(BaseModel):
    bucket: Literal["day", "week", "month"] | None
    points: list[TrendPointOut]


class OverviewOut(BaseModel):
    """Overview findings; ``scope.count_definitions`` defines every count."""

    scope: ScopeOut
    headline: HeadlineOut
    activity: ActivityOut
    unresolved_stages: UnresolvedStagesOut
    batches: list[BatchFindingsOut]
    risk_distribution: dict[str, int]
    policy_status_distribution: dict[str, int]
    departments: list[DepartmentOut]
    categories: list[CategoryOut]
    trend: TrendOut


@router.get("/overview")
def read_overview(request: Request, scope: ReadScope) -> OverviewOut:
    with request.app.state.engine.connect() as connection:
        return OverviewOut(
            scope=ScopeOut.load(connection, scope, DEFINITIONS), **overview(connection, scope)
        )
