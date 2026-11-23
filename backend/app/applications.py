"""Applications of a succeeded Analysis Run: each resolved Tool or unresolved Tool Candidate.

A resolved Tool is addressed as ``("tool", tool_id)`` and gathers every Tool Candidate the
Run resolved to it (several observed names can resolve to one known Tool by domain). An
unresolved Tool Candidate has no Tool ID and is addressed as ``("candidate", number)``.
"""

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass

from sqlalchemy import ColumnElement, Connection, and_, func, select, true

from app.db.tables import (
    activity_events,
    ai_determinations,
    category_classifications,
    tool_candidates,
    usage_context_assessments,
)
from app.pipeline.usage_contexts import RESOLVED_OUTCOMES
from app.results import no_risk_tier_reasons
from app.scope import Scope, context_conditions, scoped_events

# Highest first; an unresolved tier ranks below every resolved one.
TIER_ORDER = ("High", "Medium", "Lower", "unresolved")
_AI_PRECEDENCE = ("ai", "unresolved", "non_ai")

INVENTORY_DEFINITIONS = {
    "applications": (
        "One row per application of a selected Run: a resolved Tool, gathering every Tool "
        "Candidate the Run resolved to it, or an unresolved Tool Candidate. An application "
        "matches when it has at least one matching Activity Event, and its own AI "
        "Determination, Identity Resolution outcome and names or domain match the inventory "
        "filters. Applications are per Run, never merged across Batches: one known Tool "
        "seen in two Batches is two rows. Ordered by first application name (case-"
        "insensitive), domain, Run ID, subject kind and subject ID."
    ),
    "applications.matching_events": (
        "The application's matching Activity Events, as in overview activity counts."
    ),
    "applications.matching_context_numbers": (
        "The application's matching Usage Contexts in its Run."
    ),
    "applications.event_count": (
        "Every Activity Event of the application in its Run, regardless of filters; "
        "context_count, highest_tier, investigation_flag and policy_statuses likewise "
        "describe all of its Usage Contexts in the Run."
    ),
    "applications.ai_determination": (
        "A Tool with several Tool Candidates is AI if any candidate is, non-AI only if every "
        "candidate is, and otherwise unresolved."
    ),
}
_KEYS = ("run_id", "candidate_number")
_CONTEXT_COLUMNS = (
    "context_number",
    "tool_id",
    "department",
    "usage_purpose",
    "data_sensitivity_tier",
    "event_count",
    "first_observed_at",
    "last_observed_at",
    "facts",
    "tier",
    "investigation_flag",
    "flag_reasons",
    "rule_version",
)


@dataclass(frozen=True)
class ApplicationSummary:
    """One application of a Run, as the inventory lists it."""

    run_id: str
    subject_kind: str
    subject_id: str
    application_names: tuple[str, ...]
    domain: str
    identity_outcome: str
    candidate_numbers: tuple[int, ...]
    event_count: int
    ai_determination: str
    category_outcome: str
    category: str | None
    context_count: int
    risk_outcome: str
    highest_tier: str | None
    investigation_flag: bool
    policy_statuses: tuple[str, ...]


def list_application_summaries(
    connection: Connection, run_ids: Sequence[str]
) -> list[ApplicationSummary]:
    """Every application of the Runs, each Run's ordered by its first Tool Candidate."""
    return _summarize(
        _candidates(connection, run_ids, details=False), _contexts(connection, run_ids)
    )


def list_applications(
    connection: Connection,
    scope: Scope,
    limit: int,
    offset: int,
    ai_determinations: Sequence[str] = (),
    identity_outcomes: Sequence[str] = (),
    application: str | None = None,
) -> tuple[list[dict], int]:
    """One page of the scope's matching applications and their total; see ``INVENTORY_DEFINITIONS``.

    ``application`` matches any application name or the domain, case-insensitively, as a
    substring. Each row is an ``ApplicationSummary`` with its ``batch_id``,
    ``matching_events`` and ``matching_context_numbers``.
    """
    events = scoped_events(scope)
    matching_events = {
        (run_id, number): count
        for run_id, number, count in connection.execute(
            select(events.c.run_id, events.c.candidate_number, func.count()).group_by(
                events.c.run_id, events.c.candidate_number
            )
        )
    }
    table = usage_context_assessments
    matching_contexts: dict[tuple[str, str], list[int]] = {}
    for run_id, tool_id, number in connection.execute(
        select(table.c.run_id, table.c.tool_id, table.c.context_number)
        .where(*context_conditions(scope))
        .order_by(table.c.run_id, table.c.context_number)
    ):
        matching_contexts.setdefault((run_id, tool_id), []).append(number)
    batch_ids = {s.run_id: s.batch_id for s in scope.selections}
    needle = application.casefold() if application is not None else None

    rows = []
    for summary in list_application_summaries(connection, scope.run_ids):
        matched = sum(
            matching_events.get((summary.run_id, n), 0) for n in summary.candidate_numbers
        )
        if not matched:
            continue
        if ai_determinations and summary.ai_determination not in ai_determinations:
            continue
        if identity_outcomes and summary.identity_outcome not in identity_outcomes:
            continue
        if needle is not None and not any(
            needle in text.casefold() for text in (*summary.application_names, summary.domain)
        ):
            continue
        contexts = (
            matching_contexts.get((summary.run_id, summary.subject_id), [])
            if summary.subject_kind == "tool"
            else []
        )
        rows.append(
            {
                **asdict(summary),
                "batch_id": batch_ids[summary.run_id],
                "matching_events": matched,
                "matching_context_numbers": contexts,
            }
        )
    rows.sort(
        key=lambda r: (
            r["application_names"][0].casefold(),
            r["domain"],
            r["run_id"],
            r["subject_kind"],
            r["subject_id"],
        )
    )
    return rows[offset : offset + limit], len(rows)


def get_application(
    connection: Connection, run_id: str, batch_id: str, subject_kind: str, subject_id: str
) -> dict | None:
    """One application of a Run with every determination and its context summary, if it exists.

    ``subject_id`` is a Tool ID for ``tool`` and a candidate number for ``candidate``.
    """
    if subject_kind == "tool":
        where = [tool_candidates.c.tool_id == subject_id]
    else:
        where = [
            tool_candidates.c.candidate_number == int(subject_id),
            tool_candidates.c.outcome.not_in(RESOLVED_OUTCOMES),
        ]
    candidates = _candidates(connection, [run_id], *where)
    if not candidates:
        return None
    contexts = (
        _contexts(connection, [run_id], usage_context_assessments.c.tool_id == subject_id)
        if subject_kind == "tool"
        else []
    )
    summary = _summarize(candidates, contexts)[0]
    first = candidates[0]
    reasons = no_risk_tier_reasons(summary.identity_outcome, summary.ai_determination)
    no_context_reason = None if contexts else next(iter(reasons), None)
    return {
        "run_id": run_id,
        "batch_id": batch_id,
        "summary": summary,
        "identity": {
            "outcome": first["outcome"],
            "tool_id": first["tool_id"],
            "basis": first["basis"],
            "reason": first["reason"],
            "catalog_tool_ids": first["catalog_tool_ids"],
        },
        "candidates": [
            {
                "candidate_number": c["candidate_number"],
                "application_names": c["application_names"],
                "event_count": c["event_count"],
                "metadata_id": c["metadata_id"],
                "ai_determination": c["ai"],
                "category_classification": c["category"],
            }
            for c in candidates
        ],
        "activity": _activity(connection, run_id, batch_id, where),
        "usage_contexts": {
            "outcome": "applicable" if contexts else "inapplicable",
            "reason": no_context_reason,
            "count": len(contexts),
            "event_count": sum(c["event_count"] for c in contexts),
            "departments": sorted({c["department"] for c in contexts}),
            "first_observed_at": min((c["first_observed_at"] for c in contexts), default=None),
            "last_observed_at": max((c["last_observed_at"] for c in contexts), default=None),
            "references": [
                {
                    "run_id": run_id,
                    "context_number": c["context_number"],
                    "department": c["department"],
                    "usage_purpose": c["usage_purpose"],
                    "data_sensitivity_tier": c["data_sensitivity_tier"],
                    "event_count": c["event_count"],
                    "tier": c["tier"],
                    "investigation_flag": c["investigation_flag"],
                    "flag_reasons": c["flag_reasons"],
                }
                for c in contexts
            ],
        },
        "policy_status": {
            "outcome": "applicable" if contexts else "inapplicable",
            "reason": None if contexts else "no_usage_context",
            "statuses": list(summary.policy_statuses),
        },
        "risk": {
            "outcome": summary.risk_outcome,
            "reason": no_context_reason,
            "highest_tier": summary.highest_tier,
            "tier_counts": {
                tier: count
                for tier in TIER_ORDER
                if (count := sum(c["tier"] == tier for c in contexts))
            },
            "investigation_flag": summary.investigation_flag,
            "flag_reasons": list(_unique(r for c in contexts for r in c["flag_reasons"])),
            "rule_versions": sorted({c["rule_version"] for c in contexts}),
        },
    }


def _summarize(
    candidates: Sequence[Mapping], contexts: Sequence[Mapping]
) -> list[ApplicationSummary]:
    subjects: dict[tuple[str, str, str], list[Mapping]] = {}
    for candidate in candidates:
        subjects.setdefault((candidate["run_id"], *_subject(candidate)), []).append(candidate)
    contexts_by_tool: dict[tuple[str, str], list[Mapping]] = {}
    for context in contexts:
        contexts_by_tool.setdefault((context["run_id"], context["tool_id"]), []).append(context)

    summaries = []
    for (run_id, kind, subject_id), grouped in subjects.items():
        found = contexts_by_tool.get((run_id, subject_id), []) if kind == "tool" else []
        ai = _tool_ai_determination(c["ai"]["determination"] for c in grouped)
        # Only a known Tool groups several candidates; its AI-positive ones share one catalog
        # Category, so the first candidate with the Tool's AI outcome speaks for all of them.
        category = next(c["category"] for c in grouped if c["ai"]["determination"] == ai)
        tiers = {c["tier"] for c in found}
        summaries.append(
            ApplicationSummary(
                run_id=run_id,
                subject_kind=kind,
                subject_id=subject_id,
                application_names=tuple(
                    _unique(n for c in grouped for n in c["application_names"])
                ),
                domain=grouped[0]["domain"],
                identity_outcome=grouped[0]["outcome"],
                candidate_numbers=tuple(c["candidate_number"] for c in grouped),
                event_count=sum(c["event_count"] for c in grouped),
                ai_determination=ai,
                category_outcome=category["outcome"],
                category=category["category"],
                context_count=len(found),
                risk_outcome="assessed" if found else "inapplicable",
                highest_tier=next((t for t in TIER_ORDER if t in tiers), None),
                investigation_flag=any(c["investigation_flag"] for c in found),
                policy_statuses=tuple(sorted({c["facts"]["policy_status"] for c in found})),
            )
        )
    return summaries


def _subject(candidate: Mapping) -> tuple[str, str]:
    if candidate["outcome"] in RESOLVED_OUTCOMES:
        return "tool", candidate["tool_id"]
    return "candidate", str(candidate["candidate_number"])


def _tool_ai_determination(determinations: Iterable[str]) -> str:
    """AI if any candidate's evidence shows AI work, non-AI only if every candidate is non-AI."""
    found = set(determinations)
    return next(d for d in _AI_PRECEDENCE if d in found)


def _candidates(
    connection: Connection, run_ids: Sequence[str], *where: ColumnElement, details: bool = True
) -> list[dict]:
    """Tool Candidates by Run and number with nested ``ai`` and ``category`` outcomes.

    Event IDs are left out; without ``details`` so are evidence, neighbors and provenance.
    """
    ai, category = ai_determinations, category_classifications
    if details:
        outcomes = [c for c in ai.c if c.name not in _KEYS]
        categories = [c for c in category.c if c.name not in _KEYS]
    else:
        outcomes = [ai.c.determination]
        categories = [category.c.outcome, category.c.category]
    rows = connection.execute(
        select(
            *(c for c in tool_candidates.c if c.name != "event_ids"),
            *(c.label(f"ai.{c.name}") for c in outcomes),
            *(c.label(f"category.{c.name}") for c in categories),
        )
        .join(ai, _same_candidate(ai))
        .join(category, _same_candidate(category))
        .where(tool_candidates.c.run_id.in_(run_ids), *where)
        .order_by(tool_candidates.c.run_id, tool_candidates.c.candidate_number)
    ).mappings().all()
    candidates = []
    for row in rows:
        candidate: dict = {"ai": {}, "category": {}}
        for key, value in row.items():
            prefix, _, name = key.partition(".")
            if name:
                candidate[prefix][name] = value
            else:
                candidate[key] = value
        candidates.append(candidate)
    return candidates


def _same_candidate(table) -> ColumnElement[bool]:
    return and_(
        table.c.run_id == tool_candidates.c.run_id,
        table.c.candidate_number == tool_candidates.c.candidate_number,
    )


def _contexts(connection: Connection, run_ids: Sequence[str], *where: ColumnElement) -> list[dict]:
    """Usage Context assessments by Run and number, without their event IDs."""
    table = usage_context_assessments
    rows = connection.execute(
        select(table.c.run_id, *(table.c[name] for name in _CONTEXT_COLUMNS))
        .where(table.c.run_id.in_(run_ids), *where)
        .order_by(table.c.run_id, table.c.context_number)
    ).mappings().all()
    return [dict(row) for row in rows]


def _activity(
    connection: Connection, run_id: str, batch_id: str, where: Sequence[ColumnElement]
) -> dict:
    """Event count, observed range and departments of the selected candidates' Activity Events."""
    event_ids = func.json_each(tool_candidates.c.event_ids).table_valued("value")
    rows = connection.execute(
        select(
            activity_events.c.department,
            func.count().label("event_count"),
            func.min(activity_events.c.occurred_at).label("first_observed_at"),
            func.max(activity_events.c.occurred_at).label("last_observed_at"),
        )
        .select_from(tool_candidates)
        .join(event_ids, true())
        .join(
            activity_events,
            and_(
                activity_events.c.batch_id == batch_id,
                activity_events.c.event_id == event_ids.c.value,
            ),
        )
        .where(tool_candidates.c.run_id == run_id, *where)
        .group_by(activity_events.c.department)
        .order_by(activity_events.c.department)
    ).mappings().all()
    return {
        "event_count": sum(row["event_count"] for row in rows),
        "first_observed_at": min(row["first_observed_at"] for row in rows),
        "last_observed_at": max(row["last_observed_at"] for row in rows),
        "departments": [row["department"] for row in rows],
    }


def _unique(values: Iterable[str]) -> list[str]:
    return list(dict.fromkeys(values))
