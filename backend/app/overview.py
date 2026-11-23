"""Overview findings under one read scope (PROJECT_PLAN.md, "Dashboard interaction and
information contract"): headline counts, contextual-risk and Policy Status distributions,
department and Category breakdowns, and an activity trend, over every matching record.

Only known catalog Tools are counted across Batches; Batch-stable observed Tools are counted
per Batch. Activity Events are counted as supplied, without cross-Batch deduplication.
"""

from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from datetime import date, datetime, timedelta

from sqlalchemy import Connection, case, func, select

from app.db.tables import usage_context_assessments
from app.scope import POLICY_STATUSES, RISK_TIERS, Scope, context_conditions, scoped_events

# Adaptive trend buckets: daily up to this many days, weekly up to the next limit, else monthly.
DAILY_TREND_MAX_DAYS = 62
WEEKLY_TREND_MAX_DAYS = 366

AI_DETERMINATIONS = ("ai", "non_ai", "unresolved")
IDENTITY_OUTCOMES = ("known_tool", "observed_tool", "unresolved_candidate")

DEFINITIONS = {
    "headline.known_ai_tools": (
        "Distinct known catalog Tools (Identity Resolution outcome known_tool) with matching "
        "AI-positive activity. Known Tools are the only identity counted across Batches."
    ),
    "headline.ai_positive_events": (
        "Matching Activity Events whose Tool Candidate the selected Run determined to be AI."
    ),
    "headline.ai_unresolved_events": (
        "Matching Activity Events whose Tool Candidate's AI Determination is unresolved."
    ),
    "headline.flagged_contexts": (
        "Matching Usage Contexts whose stored investigation flag is set, including "
        "unresolved assessments; not only High-tier contexts."
    ),
    "activity": (
        "Matching Activity Events by AI Determination, and AI-positive ones by the Identity "
        "Resolution outcome of their Tool Candidate."
    ),
    "unresolved_stages": (
        "Per stage, matching Activity Events and Tool Candidates (once per Run) with an "
        "unresolved outcome at that stage. Stages overlap and must not be summed."
    ),
    "batches": (
        "Per selected Run: matching and AI-positive Activity Events, distinct known and "
        "Batch-stable observed AI Tools, and flagged Usage Contexts. Observed Tools are "
        "Batch-scoped and never summed across Batches."
    ),
    "risk_distribution": (
        "Matching Usage Contexts by stored contextual-risk tier. Tiers are the synthetic "
        "demonstration rubric's; Lower does not mean safe."
    ),
    "policy_status_distribution": (
        "Matching Usage Contexts by the synthetic Policy Status their assessment recorded; "
        "unknown is not unapproved."
    ),
    "departments": (
        "Per Activity Event department: matching and AI-positive Activity Events, and "
        "matching flagged Usage Contexts of that department."
    ),
    "categories": (
        "Matching AI-positive Activity Events by their Tool Candidate's Category "
        "Classification; an unresolved Category is its own row."
    ),
    "trend": (
        "Matching AI-positive Activity Events per UTC bucket: a day for spans up to "
        f"{DAILY_TREND_MAX_DAYS} days, a week from Monday up to {WEEKLY_TREND_MAX_DAYS} "
        "days, else a calendar month. Buckets span the selected Batches' activity periods "
        "within the event-time window. A bucket outside every selected Batch's activity "
        "period is not covered and has null counts, not zero; edge buckets may be partly "
        "covered."
    ),
    "trend.known_ai_tools_first_observed": (
        "Known AI Tools whose earliest matching AI-positive Activity Event falls in the "
        "bucket: first observed within this scope and window, not a Previously Unseen Tool."
    ),
}


def overview(connection: Connection, scope: Scope) -> dict:
    """The overview body for ``scope``; ``ScopeOut`` reports the scope itself."""
    events = scoped_events(scope)
    is_ai = events.c.ai_determination == "ai"
    candidates = connection.execute(
        select(
            events.c.run_id,
            events.c.candidate_number,
            events.c.identity_outcome,
            events.c.tool_id,
            events.c.ai_determination,
            events.c.category_outcome,
            events.c.category,
            func.count().label("events"),
        ).group_by(
            events.c.run_id,
            events.c.candidate_number,
            events.c.identity_outcome,
            events.c.tool_id,
            events.c.ai_determination,
            events.c.category_outcome,
            events.c.category,
        )
    ).mappings().all()
    departments = connection.execute(
        select(
            events.c.department,
            func.count().label("events"),
            func.sum(case((is_ai, 1), else_=0)).label("ai_positive_events"),
        ).group_by(events.c.department)
    ).mappings().all()
    day = func.substr(events.c.occurred_at, 1, 10)
    daily = connection.execute(
        select(day, func.count()).where(is_ai).group_by(day)
    ).all()
    first_observed = connection.execute(
        select(func.min(events.c.occurred_at))
        .where(is_ai, events.c.identity_outcome == "known_tool")
        .group_by(events.c.tool_id)
    ).scalars().all()
    table = usage_context_assessments
    policy_status = table.c.facts["policy_status"].as_string()
    contexts = connection.execute(
        select(
            table.c.run_id,
            table.c.department,
            table.c.tier,
            policy_status.label("policy_status"),
            table.c.investigation_flag,
            func.count().label("contexts"),
        )
        .where(*context_conditions(scope))
        .group_by(
            table.c.run_id,
            table.c.department,
            table.c.tier,
            policy_status,
            table.c.investigation_flag,
        )
    ).mappings().all()

    flagged = [row for row in contexts if row["investigation_flag"]]
    ai_events = [row for row in candidates if row["ai_determination"] == "ai"]
    return {
        "headline": {
            "known_ai_tools": len(_known_ai_tools(candidates)),
            "ai_positive_events": _total(ai_events),
            "ai_unresolved_events": _total(
                row for row in candidates if row["ai_determination"] == "unresolved"
            ),
            "flagged_contexts": _total(flagged, "contexts"),
        },
        "activity": {
            "events": _total(candidates),
            "by_ai_determination": _counts(AI_DETERMINATIONS, candidates, "ai_determination"),
            "ai_positive_by_identity": _counts(IDENTITY_OUTCOMES, ai_events, "identity_outcome"),
        },
        "unresolved_stages": {
            stage: {
                "events": _total(rows),
                "candidates": len(rows),
            }
            for stage, rows in (
                ("identity", [r for r in candidates if r["identity_outcome"] == "unresolved_candidate"]),
                ("ai_determination", [r for r in candidates if r["ai_determination"] == "unresolved"]),
                ("category", [r for r in candidates if r["category_outcome"] == "unresolved"]),
            )
        },
        "batches": _batches(scope, candidates, flagged),
        "risk_distribution": _counts(RISK_TIERS, contexts, "tier", "contexts"),
        "policy_status_distribution": _counts(POLICY_STATUSES, contexts, "policy_status", "contexts"),
        "departments": _departments(departments, flagged),
        "categories": _categories(ai_events),
        "trend": trend(scope, {date.fromisoformat(d): n for d, n in daily}, first_observed),
    }


def trend(scope: Scope, daily: Mapping[date, int], first_observed: Sequence[str]) -> dict:
    """AI-positive events and first-observed known AI Tools per adaptive bucket.

    ``daily`` maps a UTC day to its matching AI-positive events; ``first_observed`` holds each
    known AI Tool's earliest matching event time.
    """
    periods = [
        (b.batch.activity_start, b.batch.activity_end)
        for b in scope.batches
        if b.selected_run is not None
    ]
    start, end = scope.filters.start, scope.filters.end
    if not periods:
        return {"bucket": None, "points": []}
    first = max([min(p[0] for p in periods), *([start] if start else [])])
    # ``end`` is exclusive and event times are whole seconds.
    last_in_window = [_text(_instant(end) - timedelta(seconds=1))] if end else []
    last = min([max(p[1] for p in periods), *last_in_window])
    if first > last:
        return {"bucket": None, "points": []}
    first_day, last_day = _instant(first).date(), _instant(last).date()
    size = bucket_size(first_day, last_day)
    events = Counter()
    for day, count in daily.items():
        events[bucket_start(day, size)] += count
    new_tools = Counter(bucket_start(_instant(t).date(), size) for t in first_observed)

    points = []
    current = bucket_start(first_day, size)
    while current <= last_day:
        following = _next_bucket(current, size)
        lower, upper = _text(current), _text(following)
        clipped_lower, clipped_upper = max(lower, start or lower), min(upper, end or upper)
        covered = any(p_start < clipped_upper and p_end >= clipped_lower for p_start, p_end in periods)
        points.append(
            {
                "start": lower,
                "end": upper,
                "covered": covered,
                "ai_positive_events": events[current] if covered else None,
                "known_ai_tools_first_observed": new_tools[current] if covered else None,
            }
        )
        current = following
    return {"bucket": size, "points": points}


def bucket_size(first: date, last: date) -> str:
    days = (last - first).days + 1
    if days <= DAILY_TREND_MAX_DAYS:
        return "day"
    if days <= WEEKLY_TREND_MAX_DAYS:
        return "week"
    return "month"


def bucket_start(day: date, size: str) -> date:
    if size == "week":
        return day - timedelta(days=day.weekday())
    if size == "month":
        return day.replace(day=1)
    return day


def _next_bucket(start: date, size: str) -> date:
    if size == "week":
        return start + timedelta(days=7)
    if size == "month":
        return (start.replace(day=28) + timedelta(days=4)).replace(day=1)
    return start + timedelta(days=1)


def _instant(text: str) -> datetime:
    return datetime.strptime(text, "%Y-%m-%dT%H:%M:%SZ")


def _text(value: date) -> str:
    if not isinstance(value, datetime):
        value = datetime(value.year, value.month, value.day)
    return value.isoformat(timespec="seconds") + "Z"


def _total(rows: Iterable[Mapping], key: str = "events") -> int:
    return sum(row[key] for row in rows)


def _counts(
    keys: Sequence[str], rows: Iterable[Mapping], by: str, count: str = "events"
) -> dict[str, int]:
    """Counts by ``by`` with every expected key present; an unexpected value is kept, not dropped."""
    counts = dict.fromkeys(keys, 0)
    for row in rows:
        counts[row[by]] = counts.get(row[by], 0) + row[count]
    return counts


def _known_ai_tools(candidates: Iterable[Mapping]) -> set[str]:
    return {
        row["tool_id"]
        for row in candidates
        if row["ai_determination"] == "ai" and row["identity_outcome"] == "known_tool"
    }


def _batches(scope: Scope, candidates: Sequence[Mapping], flagged: Sequence[Mapping]) -> list[dict]:
    by_run: dict[str, list[Mapping]] = {}
    for row in candidates:
        by_run.setdefault(row["run_id"], []).append(row)
    flagged_by_run = Counter()
    for row in flagged:
        flagged_by_run[row["run_id"]] += row["contexts"]
    found = []
    for selection in scope.selections:
        rows = by_run.get(selection.run_id, [])
        ai = [row for row in rows if row["ai_determination"] == "ai"]
        found.append(
            {
                "batch_id": selection.batch_id,
                "run_id": selection.run_id,
                "events": _total(rows),
                "ai_positive_events": _total(ai),
                "known_ai_tools": len(_known_ai_tools(ai)),
                "observed_ai_tools": len(
                    {row["tool_id"] for row in ai if row["identity_outcome"] == "observed_tool"}
                ),
                "flagged_contexts": flagged_by_run[selection.run_id],
            }
        )
    return found


def _departments(activity: Sequence[Mapping], flagged: Sequence[Mapping]) -> list[dict]:
    rows = {
        row["department"]: {
            "department": row["department"],
            "events": row["events"],
            "ai_positive_events": row["ai_positive_events"],
            "flagged_contexts": 0,
        }
        for row in activity
    }
    for row in flagged:
        rows.setdefault(
            row["department"],
            {"department": row["department"], "events": 0, "ai_positive_events": 0, "flagged_contexts": 0},
        )["flagged_contexts"] += row["contexts"]
    return sorted(rows.values(), key=lambda r: (-r["ai_positive_events"], r["department"]))


def _categories(ai_events: Iterable[Mapping]) -> list[dict]:
    counts = Counter()
    for row in ai_events:
        counts[(row["category_outcome"], row["category"])] += row["events"]
    return [
        {"outcome": outcome, "category": category, "ai_positive_events": count}
        for (outcome, category), count in sorted(
            counts.items(), key=lambda item: (item[0][0] != "assigned", -item[1], item[0][1] or "")
        )
    ]
