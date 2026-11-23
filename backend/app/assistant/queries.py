"""Thin read helpers over ``app.scope`` that the listing modules do not expose.

The assistant adapters need an Activity Event AI-status condition (``GET /events``'s
``ai_determinations``), grouped distinct counts, assessment columns that
``app.contexts.list_contexts`` omits, and scope membership checks for evidence
references. Everything is built from ``scoped_events`` and ``context_conditions``, so a
count here matches the listing endpoints for the same scope. Read-only.
"""

from collections.abc import Mapping, Sequence
from typing import Literal

from sqlalchemy import (
    ColumnElement,
    Connection,
    and_,
    case,
    distinct,
    false,
    func,
    literal,
    select,
    tuple_,
)

from app.db.tables import tool_candidates, usage_context_assessments
from app.evidence import (
    ActivityEventReference,
    AiEvidenceSentenceReference,
    AnalysisRunReference,
    CategoryNeighborReference,
    RecordReference,
    ToolMetadataReference,
    UsageContextReference,
    WebsiteCaptureReference,
)
from app.overview import AI_DETERMINATIONS, IDENTITY_OUTCOMES
from app.pipeline.usage_contexts import RESOLVED_OUTCOMES
from app.scope import POLICY_STATUSES, RISK_TIERS, Scope, context_conditions, scoped_events

Metric = Literal["event_count", "distinct_employees", "tools", "usage_contexts"]
Dimension = Literal["department", "category", "ai_status", "risk_tier"]

_TABLE = usage_context_assessments
_POLICY_STATUS = _TABLE.c.facts["policy_status"].as_string()
_HAS_UNKNOWN_FACTS = func.json_array_length(_TABLE.c.unknown_facts) > 0
_TIER_RANK = case(
    {tier: rank for rank, tier in enumerate(RISK_TIERS)}, value=_TABLE.c.tier, else_=len(RISK_TIERS)
)
_OPTIONAL_FIELDS = ("job_role", "event_type", "usage_purpose", "data_sensitivity_tier")
# Supplied fields where the literal value "unknown" also means the fact is missing.
_UNKNOWN_VALUED = ("usage_purpose", "data_sensitivity_tier")
_ASSESSMENT_COLUMNS = (
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
    "metadata_id",
    "facts",
    "tier",
    "reason_codes",
    "unknown_facts",
    "investigation_flag",
    "flag_reasons",
    "rule_version",
)

FOCUS_CONDITIONS: Mapping[str, ColumnElement[bool] | None] = {
    "all": None,
    "flagged": _TABLE.c.investigation_flag.is_(True),
    "unapproved": _POLICY_STATUS == "unapproved",
    "unresolved": _TABLE.c.tier == "unresolved",
    "missing_facts": _HAS_UNKNOWN_FACTS,
}


def _events(scope: Scope, ai_statuses: Sequence[str]):
    """Matching events with their Usage Context's row, and the AI-status condition."""
    events = scoped_events(scope)
    joined = events.outerjoin(
        _TABLE,
        and_(_TABLE.c.run_id == events.c.run_id, _TABLE.c.context_number == events.c.context_number),
    )
    where = [events.c.ai_determination.in_(ai_statuses)] if ai_statuses else []
    return events, joined, where


def _context_where(scope: Scope, ai_statuses: Sequence[str]) -> list[ColumnElement[bool]]:
    # Only Tool Candidates determined AI get Usage Contexts.
    where = context_conditions(scope)
    if ai_statuses and "ai" not in ai_statuses:
        where.append(false())
    return where


def _tool_key(events) -> ColumnElement:
    """Known Tool IDs are shared across Batches, observed Tool IDs are Batch-scoped, and an
    unresolved Tool Candidate is its own Run-scoped subject."""
    return case(
        (events.c.identity_outcome.in_(RESOLVED_OUTCOMES), events.c.tool_id),
        else_=func.json_array(events.c.run_id, events.c.candidate_number),
    )


def grouped_counts(
    connection: Connection,
    scope: Scope,
    ai_statuses: Sequence[str],
    metric: Metric,
    group_by: Sequence[Dimension] = (),
) -> tuple[int, list[dict]]:
    """``metric`` over every matching record, and per combination of ``group_by`` values.

    Groups are ordered by value (highest first), then by their dimension values.
    """
    if metric == "usage_contexts":
        dimensions = {
            "department": _TABLE.c.department,
            "category": func.coalesce(_TABLE.c.category, "unresolved"),
            "ai_status": literal("ai"),
            "risk_tier": _TABLE.c.tier,
        }
        source, where, value = _TABLE, _context_where(scope, ai_statuses), func.count()
    else:
        events, source, where = _events(scope, ai_statuses)
        dimensions = {
            "department": events.c.department,
            "category": case(
                (events.c.category_outcome == "assigned", events.c.category),
                else_=events.c.category_outcome,
            ),
            "ai_status": events.c.ai_determination,
            "risk_tier": _TABLE.c.tier,
        }
        value = {
            "event_count": func.count(),
            "distinct_employees": func.count(
                distinct(func.json_array(events.c.batch_id, events.c.employee_id))
            ),
            "tools": func.count(distinct(_tool_key(events))),
        }[metric]
    total = connection.execute(select(value).select_from(source).where(*where)).scalar_one()
    if not group_by:
        return total, []
    columns = [dimensions[name].label(name) for name in group_by]
    rows = connection.execute(
        select(*columns, value.label("value"))
        .select_from(source)
        .where(*where)
        .group_by(*columns)
    ).mappings().all()
    groups = [dict(row) for row in rows]
    groups.sort(
        key=lambda g: (-g["value"], *((g[n] is None, g[n] or "") for n in group_by))
    )
    return total, groups


def activity_profile(connection: Connection, scope: Scope, ai_statuses: Sequence[str]) -> dict:
    """What the matching Activity Events cover: time range, departments, Categories, AI and
    identity outcomes, distinct subjects, unresolved stages and missing supplied fields."""
    events, _, where = _events(scope, ai_statuses)
    category = case(
        (events.c.category_outcome == "assigned", events.c.category),
        else_=events.c.category_outcome,
    )
    first, last, employees = connection.execute(
        select(
            func.min(events.c.occurred_at),
            func.max(events.c.occurred_at),
            func.count(distinct(func.json_array(events.c.batch_id, events.c.employee_id))),
        ).where(*where)
    ).one()
    missing = []
    for name in _OPTIONAL_FIELDS:
        missing.append(func.sum(case((events.c[name].is_(None), 1), else_=0)).label(f"{name}.absent"))
        if name in _UNKNOWN_VALUED:
            missing.append(
                func.sum(case((func.lower(events.c[name]) == "unknown", 1), else_=0)).label(
                    f"{name}.unknown"
                )
            )
    rows = connection.execute(
        select(
            events.c.department,
            events.c.ai_determination,
            events.c.identity_outcome,
            events.c.category_outcome,
            category.label("category"),
            func.count().label("events"),
            *missing,
        )
        .where(*where)
        .group_by(
            events.c.department,
            events.c.ai_determination,
            events.c.identity_outcome,
            events.c.category_outcome,
            category,
        )
    ).mappings().all()
    # Each Tool Candidate has one outcome per stage, so its distinct count sums across rows.
    outcomes = connection.execute(
        select(
            events.c.identity_outcome,
            events.c.ai_determination,
            events.c.category_outcome,
            func.count().label("events"),
            func.count(distinct(func.json_array(events.c.run_id, events.c.candidate_number))).label(
                "candidates"
            ),
        )
        .where(*where)
        .group_by(events.c.identity_outcome, events.c.ai_determination, events.c.category_outcome)
    ).mappings().all()
    tools = dict(
        connection.execute(
            select(events.c.identity_outcome, func.count(distinct(_tool_key(events))))
            .where(*where)
            .group_by(events.c.identity_outcome)
        ).all()
    )

    departments: dict[str, dict] = {}
    categories: dict[str, int] = {}
    for row in rows:
        entry = departments.setdefault(
            row["department"], {"department": row["department"], "events": 0, "ai_positive_events": 0}
        )
        entry["events"] += row["events"]
        entry["ai_positive_events"] += row["events"] if row["ai_determination"] == "ai" else 0
        categories[row["category"]] = categories.get(row["category"], 0) + row["events"]
    stages = {
        "identity": ("identity_outcome", "unresolved_candidate"),
        "ai_determination": ("ai_determination", "unresolved"),
        "category": ("category_outcome", "unresolved"),
    }
    return {
        "first_matching": first,
        "last_matching": last,
        "events": _sum(rows, "events"),
        "distinct_employees": employees,
        "by_ai_status": _counts(AI_DETERMINATIONS, rows, "ai_determination"),
        "by_identity": _counts(IDENTITY_OUTCOMES, rows, "identity_outcome"),
        "tools": {
            "known_tools": tools.get("known_tool", 0),
            "observed_tools": tools.get("observed_tool", 0),
            "unresolved_candidates": tools.get("unresolved_candidate", 0),
        },
        "departments": sorted(
            departments.values(), key=lambda d: (-d["events"], d["department"])
        ),
        "categories": [
            {"category": name, "events": count}
            for name, count in sorted(categories.items(), key=lambda item: (-item[1], item[0]))
        ],
        "unresolved_stages": {
            stage: {
                "events": _sum((r for r in outcomes if r[column] == value), "events"),
                "candidates": _sum((r for r in outcomes if r[column] == value), "candidates"),
            }
            for stage, (column, value) in stages.items()
        },
        "missing_fields": {
            name: {
                kind: _sum(rows, f"{name}.{kind}")
                for kind in (("absent", "unknown") if name in _UNKNOWN_VALUED else ("absent",))
            }
            for name in _OPTIONAL_FIELDS
        },
    }


def assessment_counts(
    connection: Connection,
    scope: Scope,
    ai_statuses: Sequence[str],
    condition: ColumnElement[bool] | None = None,
) -> dict:
    """Tier, Policy Status, flag and unknown-fact counts over every matching Usage Context."""
    where = _context_where(scope, ai_statuses)
    if condition is not None:
        where.append(condition)
    has_unknown = _HAS_UNKNOWN_FACTS.label("has_unknown")
    rows = connection.execute(
        select(
            _TABLE.c.tier,
            _POLICY_STATUS.label("policy_status"),
            _TABLE.c.investigation_flag,
            has_unknown,
            func.count().label("contexts"),
        )
        .where(*where)
        .group_by(_TABLE.c.tier, _POLICY_STATUS, _TABLE.c.investigation_flag, has_unknown)
    ).mappings().all()
    return {
        "total": _sum(rows, "contexts"),
        "by_tier": _counts(RISK_TIERS, rows, "tier", "contexts"),
        "by_policy_status": _counts(POLICY_STATUSES, rows, "policy_status", "contexts"),
        "flagged": _sum((r for r in rows if r["investigation_flag"]), "contexts"),
        "with_unknown_facts": _sum((r for r in rows if r["has_unknown"]), "contexts"),
    }


def list_assessments(
    connection: Connection,
    scope: Scope,
    ai_statuses: Sequence[str],
    condition: ColumnElement[bool] | None,
    limit: int,
    offset: int,
) -> list[dict]:
    """One page of matching Usage Context assessments, ordered as ``GET /contexts`` orders
    them, with their reason codes, unknown facts, matching events and Tool Candidates."""
    where = _context_where(scope, ai_statuses)
    if condition is not None:
        where.append(condition)
    rows = connection.execute(
        select(*(_TABLE.c[name] for name in _ASSESSMENT_COLUMNS))
        .where(*where)
        .order_by(_TIER_RANK, _TABLE.c.run_id, _TABLE.c.context_number)
        .limit(limit)
        .offset(offset)
    ).mappings().all()
    if not rows:
        return []
    keys = [(row["run_id"], row["context_number"]) for row in rows]
    events, _, event_where = _events(scope, ai_statuses)
    matching = {
        (run_id, number): count
        for run_id, number, count in connection.execute(
            select(events.c.run_id, events.c.context_number, func.count())
            .where(tuple_(events.c.run_id, events.c.context_number).in_(keys), *event_where)
            .group_by(events.c.run_id, events.c.context_number)
        )
    }
    candidates: dict[tuple[str, str], list[int]] = {}
    for run_id, tool_id, number in connection.execute(
        select(tool_candidates.c.run_id, tool_candidates.c.tool_id, tool_candidates.c.candidate_number)
        .where(
            tuple_(tool_candidates.c.run_id, tool_candidates.c.tool_id).in_(
                sorted({(row["run_id"], row["tool_id"]) for row in rows})
            )
        )
        .order_by(tool_candidates.c.candidate_number)
    ):
        candidates.setdefault((run_id, tool_id), []).append(number)
    return [
        {
            **row,
            "matching_events": matching.get(key, 0),
            "candidate_numbers": candidates.get((row["run_id"], row["tool_id"]), []),
        }
        for row, key in zip(rows, keys, strict=True)
    ]


def contains(
    connection: Connection, scope: Scope, ai_statuses: Sequence[str], reference: RecordReference
) -> bool:
    """Whether a record reference lies within the scope: its event, Usage Context or Tool
    Candidate (by number, captured domain or metadata row) has matching activity."""
    run_id = reference.run.run_id
    if run_id not in scope.run_ids:
        return False
    if isinstance(reference, AnalysisRunReference):
        return True
    if isinstance(reference, UsageContextReference):
        found = connection.execute(
            select(literal(1)).where(
                *_context_where(scope, ai_statuses),
                _TABLE.c.run_id == run_id,
                _TABLE.c.context_number == reference.context_number,
            )
        ).first()
        return found is not None
    events, _, where = _events(scope, ai_statuses)
    source = events
    where.append(events.c.run_id == run_id)
    match reference:
        case ActivityEventReference():
            where.append(events.c.event_id == reference.event_id)
        case AiEvidenceSentenceReference() | CategoryNeighborReference():
            where.append(events.c.candidate_number == reference.candidate_number)
        case WebsiteCaptureReference() | ToolMetadataReference():
            source = events.join(
                tool_candidates,
                and_(
                    tool_candidates.c.run_id == events.c.run_id,
                    tool_candidates.c.candidate_number == events.c.candidate_number,
                ),
            )
            where.append(
                tool_candidates.c.domain == reference.domain
                if isinstance(reference, WebsiteCaptureReference)
                else tool_candidates.c.metadata_id == reference.metadata_id
            )
        case _:
            raise TypeError(reference)
    return connection.execute(select(literal(1)).select_from(source).where(*where).limit(1)).first() is not None


def _sum(rows, key: str) -> int:
    return sum(row[key] or 0 for row in rows)


def _counts(keys: Sequence[str], rows, by: str, count: str = "events") -> dict[str, int]:
    """Counts by ``by`` with every expected key present; an unexpected value is kept."""
    counts = dict.fromkeys(keys, 0)
    for row in rows:
        counts[row[by]] = counts.get(row[by], 0) + row[count]
    return counts
