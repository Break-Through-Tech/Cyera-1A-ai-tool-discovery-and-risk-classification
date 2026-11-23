"""Backend adapters for the assistant's bounded tools (issue #78).

Each handler maps the backend-pinned ``PinnedScope`` onto ``app.scope`` with explicit
``run_ids``, re-verifies the Runs, and calls the deterministic query code in-process,
never the HTTP API. Results are bounded JSON with typed evidence; previews say so and
totals always describe the complete matching population. ``retrieve_context`` is not
connected, so the registry reports it unavailable. ``build_tool_registry`` is the one
construction point.
"""

import asyncio
import json
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from hashlib import sha256
from typing import Any
from urllib.parse import urlencode

from pydantic import ValidationError
from sqlalchemy import Connection, Engine
from sqlalchemy.exc import SQLAlchemyError

from app.assistant.contracts import (
    AggregateEvidence,
    Contract,
    Evidence,
    PinnedScope,
    RecordEvidence,
    RunReference,
    ToolFailure,
    ToolLimitation,
    ToolOutcome,
    ToolSuccess,
)
from app.assistant.graph import ExecutionLimits
from app.assistant.queries import (
    FOCUS_CONDITIONS,
    activity_profile,
    assessment_counts,
    contains,
    grouped_counts,
    list_assessments,
)
from app.assistant.tools import (
    CompareUsageArgs,
    DescribeDatasetArgs,
    GetEvidenceArgs,
    GetRiskAssessmentsArgs,
    SummarizeUsageArgs,
    ToolArguments,
    ToolHandler,
    ToolRegistry,
)
from app.config import Settings
from app.errors import AppError
from app.evidence import (
    AnalysisRunReference,
    EvidenceError,
    EvidenceSources,
    PassageReference,
    RecordReference,
    UsageContextReference,
    record_reference,
    resolve_evidence,
    to_record_evidence,
)
from app.overview import DEFINITIONS as OVERVIEW_DEFINITIONS
from app.pipeline.identity import load_tool_metadata
from app.scope import (
    CATEGORIES,
    CATEGORY_OUTCOMES,
    MATCHING_DEFINITIONS,
    Filters,
    Scope,
    event_time_bound,
    observe_activity,
    resolve_scope,
)

# The registry prefixes each evidence ID with the producing step ID and a colon.
_NAMESPACE_BYTES = 64
_MAX_DEPARTMENTS = 50
_RECORD_TYPES = (
    "activity_event",
    "usage_context",
    "analysis_run",
    "ai_evidence_sentence",
    "website_capture",
    "tool_metadata",
    "category_neighbor",
)
_LISTINGS = {
    "event_count": "GET /events",
    "distinct_employees": "GET /events",
    "tools": "GET /applications",
    "usage_contexts": "GET /contexts",
}
METRIC_DEFINITIONS = {
    "event_count": "event_count: " + MATCHING_DEFINITIONS["matching_activity"],
    "distinct_employees": (
        "distinct_employees: distinct supplied employee IDs among matching Activity Events, "
        "Batch-scoped: the same ID in two Batches counts twice and is not assumed to be one person."
    ),
    "tools": (
        "tools: distinct subjects with matching Activity Events. A known catalog Tool counts "
        "once across Batches, a Batch-stable observed Tool once per Batch, and each "
        "unresolved Tool Candidate is its own subject. For one Batch this equals the "
        "GET /applications total."
    ),
    "usage_contexts": "usage_contexts: " + MATCHING_DEFINITIONS["matching_contexts"],
}
GROUP_DEFINITIONS = {
    "department": "department: the Activity Event's (or Usage Context's) supplied department.",
    "category": (
        "category: the Tool Candidate's assigned Category, or its Category Classification "
        "outcome (unresolved, inapplicable) when none is assigned."
    ),
    "ai_status": (
        "ai_status: the Tool Candidate's AI Determination (ai, non_ai, unresolved). Usage "
        "Contexts exist only for Tools determined AI."
    ),
    "risk_tier": (
        "risk_tier: the stored contextual-risk tier of the event's Usage Context; null when "
        "the event is in no Usage Context (non-AI, unresolved AI status or identity), so it "
        "has no assessment. Tiers are the synthetic demonstration rubric's."
    ),
}
FOCUS_DEFINITIONS = {
    "all": "Every matching Usage Context.",
    "flagged": "Matching Usage Contexts whose stored investigation flag is set.",
    "unapproved": "Matching Usage Contexts whose recorded synthetic Policy Status is "
    "unapproved.",
    "unresolved": "Matching Usage Contexts whose stored tier is unresolved (every rubric "
    "fact unknown).",
    "missing_facts": "Matching Usage Contexts whose assessment lists at least one unknown "
    "rubric fact.",
}


class _Stop(Exception):
    """Ends a tool call early with a limitation or a safe failure."""

    def __init__(self, outcome: ToolLimitation | ToolFailure):
        super().__init__(outcome.message)
        self.outcome = outcome


def _unsupported(message: str) -> _Stop:
    return _Stop(ToolLimitation(reason="unsupported", message=message))


@dataclass(frozen=True)
class _Read:
    """A verified scope: the pinned contract, its backend ``Scope`` and coverage warnings."""

    pinned: PinnedScope
    scope: Scope
    ai_statuses: tuple[str, ...]
    warnings: tuple[str, ...]


class QueryTools:
    """Handlers for every tool except ``retrieve_context``; each call is one read."""

    def __init__(
        self,
        engine: Engine,
        sources: EvidenceSources,
        max_result_bytes: int,
    ):
        self.engine = engine
        self.sources = sources
        self.max_result_bytes = max_result_bytes

    def handlers(self) -> dict[str, ToolHandler]:
        return {
            "describe_dataset": self._handler(self.describe_dataset),
            "summarize_usage": self._handler(self.summarize_usage),
            "compare_usage": self._handler(self.compare_usage),
            "get_risk_assessments": self._handler(self.get_risk_assessments),
            "get_evidence": self._handler(self.get_evidence),
        }

    def _handler(
        self, operation: Callable[[Connection, _Read, Any], ToolOutcome]
    ) -> ToolHandler:
        async def handle(scope: PinnedScope, arguments: ToolArguments) -> ToolOutcome:
            # Sync SQLAlchemy runs in a worker thread so the workflow deadline can stop
            # waiting; a late read finishes in the background and its result is discarded.
            return await asyncio.to_thread(self._execute, operation, scope, arguments)

        return handle

    def _execute(
        self, operation, pinned: PinnedScope, arguments: ToolArguments
    ) -> ToolOutcome:
        try:
            with self.engine.connect() as connection:
                return operation(connection, _verify(connection, pinned), arguments)
        except _Stop as stop:
            return stop.outcome
        except SQLAlchemyError:
            return ToolFailure(
                code="query_failed", message="The backend query failed; retry."
            )

    # --- Tools ---------------------------------------------------------------------------

    def describe_dataset(
        self, connection: Connection, read: _Read, arguments: DescribeDatasetArgs
    ) -> ToolOutcome:
        profile = activity_profile(connection, read.scope, read.ai_statuses)
        contexts = assessment_counts(connection, read.scope, read.ai_statuses)
        departments = profile.pop("departments")
        first, last = profile.pop("first_matching"), profile.pop("last_matching")
        base = {
            "runs": [
                {
                    "batch_id": item.batch.batch_id,
                    "run_id": item.selected_run.run_id,
                    "attempt_number": item.selected_run.attempt_number,
                    "completed_at": item.selected_run.completed_at,
                    "batch_activity_period": {
                        "start": item.batch.activity_start,
                        "end": item.batch.activity_end,
                    },
                    "batch_event_count": item.batch.event_count,
                    "versions": item.selected_run.versions,
                }
                for item in read.scope.batches
            ],
            "event_time": {
                "start": read.scope.filters.start,
                "end": read.scope.filters.end,
                "first_matching": first,
                "last_matching": last,
            },
            "filters": read.pinned.filters.model_dump(mode="json"),
            "activity": profile,
            "usage_contexts": contexts,
        }
        definitions = (
            METRIC_DEFINITIONS["event_count"],
            METRIC_DEFINITIONS["usage_contexts"],
            METRIC_DEFINITIONS["distinct_employees"],
            METRIC_DEFINITIONS["tools"] + " Here split by Identity Resolution outcome.",
            "unresolved_stages: " + OVERVIEW_DEFINITIONS["unresolved_stages"],
            "missing_fields: matching Activity Events whose optional supplied field is absent, "
            "or for usage_purpose and data_sensitivity_tier supplied as 'unknown'.",
        )
        evidence: list[Evidence] = [
            self._aggregate(read, "describe_dataset", "GET /overview", {}, definitions),
            *(_cite(AnalysisRunReference(run=run)) for run in read.pinned.runs),
        ]
        empty = profile["events"] == 0 and contexts["total"] == 0

        def build(count: int) -> ToolSuccess:
            listed = departments[:count]
            qualifications = list(read.warnings)
            if len(listed) < len(departments):
                qualifications.append(
                    f"Preview: {len(listed)} of {len(departments)} departments listed, by "
                    "matching events; every other count covers all matching records."
                )
            return ToolSuccess(
                outcome="no_matches" if empty else "data",
                summary=(
                    "No Activity Events or Usage Contexts match the pinned scope."
                    if empty
                    else f"{profile['events']} matching Activity Events in "
                    f"{len(departments)} departments; {contexts['total']} matching Usage Contexts."
                ),
                data={
                    **base,
                    "departments": {"total": len(departments), "items": listed},
                },
                evidence=tuple(evidence),
                qualifications=tuple(qualifications),
                truncated=len(listed) < len(departments),
            )

        return self._fit(build, min(len(departments), _MAX_DEPARTMENTS))

    def summarize_usage(
        self, connection: Connection, read: _Read, arguments: SummarizeUsageArgs
    ) -> ToolOutcome:
        if len(set(arguments.group_by)) != len(arguments.group_by):
            raise _unsupported("Each group_by dimension may appear only once.")
        fingerprint = _fingerprint("summarize_usage", read.pinned, arguments)
        offset = _offset(arguments.continuation, fingerprint)
        total, rows = grouped_counts(
            connection,
            read.scope,
            read.ai_statuses,
            arguments.metric,
            arguments.group_by,
        )
        definitions = (
            METRIC_DEFINITIONS[arguments.metric],
            *(GROUP_DEFINITIONS[name] for name in arguments.group_by),
        )
        evidence = self._aggregate(
            read,
            "summarize_usage",
            _LISTINGS[arguments.metric],
            {"metric": arguments.metric, "group_by": list(arguments.group_by)},
            definitions,
        )
        notes = list(read.warnings)
        if arguments.metric in ("distinct_employees", "tools") and arguments.group_by:
            notes.append(
                f"{arguments.metric} groups can overlap (one subject in several groups); "
                "do not sum them. The total is counted once over all matching records."
            )
        if arguments.metric == "usage_contexts" and read.ai_statuses:
            notes.append(_CONTEXT_AI_NOTE)

        def build(count: int) -> ToolSuccess:
            page = rows[offset : offset + count]
            return self._page(
                outcome="data" if total else "no_matches",
                summary=f"{arguments.metric} = {total} over the pinned scope"
                + (f", in {len(rows)} groups." if arguments.group_by else "."),
                data={
                    "metric": arguments.metric,
                    "group_by": list(arguments.group_by),
                    "total": total,
                    "group_count": len(rows),
                    "offset": offset,
                    "groups": page,
                },
                evidence=(evidence,),
                notes=notes,
                noun="groups",
                offset=offset,
                returned=len(page),
                available=len(rows),
                fingerprint=fingerprint,
            )

        return self._fit(build, arguments.limit)

    def compare_usage(
        self, connection: Connection, read: _Read, arguments: CompareUsageArgs
    ) -> ToolOutcome:
        window = read.pinned.event_time
        periods = {"baseline": arguments.baseline, "current": arguments.current}
        if any(p.start < window.start or p.end > window.end for p in periods.values()):
            raise _unsupported(
                "Comparison periods must lie within the pinned event-time interval."
            )
        notes = list(read.warnings)
        results: dict[str, dict] = {}
        evidence = []
        for name, period in periods.items():
            start, end = event_time_bound(period.start), event_time_bound(period.end)
            scope = replace(
                read.scope, filters=replace(read.scope.filters, start=start, end=end)
            )
            coverage = _coverage(read.scope, start, end)
            value, _ = grouped_counts(
                connection, scope, read.ai_statuses, arguments.metric
            )
            results[name] = {
                "start": start,
                "end": end,
                "coverage": coverage,
                "value": value if coverage != "none" else None,
            }
            if coverage == "none":
                notes.append(
                    f"The {name} period lies outside every selected Batch's activity period; "
                    "its value is unknown, not zero."
                )
            elif coverage == "partial":
                notes.append(
                    f"The {name} period is only partly covered by the selected Batches' "
                    "activity periods; its value may be incomplete."
                )
            evidence.append(
                self._aggregate(
                    read,
                    "compare_usage",
                    _LISTINGS[arguments.metric],
                    {"metric": arguments.metric, "period": name},
                    (METRIC_DEFINITIONS[arguments.metric],),
                    suffix=name,
                    start=start,
                    end=end,
                )
            )
        baseline, current = results["baseline"]["value"], results["current"]["value"]
        change = current - baseline if None not in (baseline, current) else None
        if periods["baseline"].end > periods["current"].start and (
            periods["current"].end > periods["baseline"].start
        ):
            notes.append(
                "The baseline and current periods overlap; their counts share records."
            )
        lengths = [p.end - p.start for p in periods.values()]
        if lengths[0] != lengths[1]:
            notes.append(
                "The periods have different lengths; compare counts with care."
            )
        if arguments.metric == "usage_contexts":
            notes.append(
                "A Usage Context counts in a period when one of its matching Activity Events "
                "falls in it; assessments are not recalculated per period."
            )
            if read.ai_statuses:
                notes.append(_CONTEXT_AI_NOTE)
        return ToolSuccess(
            outcome="data" if (baseline or current) else "no_matches",
            summary=f"{arguments.metric}: baseline {baseline}, current {current}.",
            data={
                "metric": arguments.metric,
                "baseline": results["baseline"],
                "current": results["current"],
                "change": change,
                "percent_change": (
                    round(change / baseline * 100, 1)
                    if change is not None and baseline
                    else None
                ),
            },
            evidence=tuple(evidence),
            qualifications=tuple(dict.fromkeys(notes)),
        )

    def get_risk_assessments(
        self, connection: Connection, read: _Read, arguments: GetRiskAssessmentsArgs
    ) -> ToolOutcome:
        fingerprint = _fingerprint("get_risk_assessments", read.pinned, arguments)
        offset = _offset(arguments.continuation, fingerprint)
        condition = FOCUS_CONDITIONS[arguments.focus]
        counts = assessment_counts(connection, read.scope, read.ai_statuses, condition)
        total = counts["total"]
        rows = list_assessments(
            connection, read.scope, read.ai_statuses, condition, arguments.limit, offset
        )
        batch_ids = {s.run_id: s.batch_id for s in read.scope.selections}
        evidence_rows = [
            _cite(
                UsageContextReference(
                    run=RunReference(
                        batch_id=batch_ids[row["run_id"]], run_id=row["run_id"]
                    ),
                    context_number=row["context_number"],
                )
            )
            for row in rows
        ]
        aggregate = self._aggregate(
            read,
            "get_risk_assessments",
            "GET /contexts",
            {"focus": arguments.focus},
            (
                METRIC_DEFINITIONS["usage_contexts"],
                f"focus {arguments.focus}: {FOCUS_DEFINITIONS[arguments.focus]}",
                "order: as GET /contexts, by stored tier (High, Medium, Lower, "
                "unresolved), then Run ID and context number.",
                "counts: tiers, Policy Statuses, flags and unknown facts over every context in "
                "focus. Tiers are the synthetic demonstration rubric's; Lower does not mean "
                "safe and unknown Policy Status is not unapproved.",
            ),
            focus=arguments.focus,
        )
        notes = list(read.warnings)
        if read.ai_statuses:
            notes.append(_CONTEXT_AI_NOTE)

        def build(count: int) -> ToolSuccess:
            page = [
                {"batch_id": batch_ids[row["run_id"]], **row} for row in rows[:count]
            ]
            return self._page(
                outcome="data" if total else "no_matches",
                summary=f"{total} matching Usage Contexts in focus '{arguments.focus}'; "
                f"{counts['flagged']} flagged.",
                data={
                    "focus": arguments.focus,
                    "total": total,
                    "counts": counts,
                    "offset": offset,
                    "assessments": page,
                },
                evidence=(aggregate, *evidence_rows[:count]),
                notes=notes,
                noun="Usage Contexts",
                offset=offset,
                returned=len(page),
                available=total,
                fingerprint=fingerprint,
            )

        return self._fit(build, len(rows))

    def get_evidence(
        self, connection: Connection, read: _Read, arguments: GetEvidenceArgs
    ) -> ToolOutcome:
        references: dict[str, RecordReference | PassageReference] = {}
        for text in arguments.references:
            reference = _parse_reference(text, read.pinned)
            references.setdefault(_reference_key(reference), reference)
        resolved, unresolved = [], []
        for key, reference in references.items():
            try:
                item = resolve_evidence(connection, reference, self.sources)
            except EvidenceError as error:
                if error.code == "invalid_reference":
                    raise _unsupported(
                        "A reference is not a valid record reference."
                    ) from None
                status = (
                    "unavailable"
                    if error.status_code == 501
                    or error.code == "source_version_unavailable"
                    else "not_found" if error.status_code == 404 else None
                )
                if status is None:
                    raise
                unresolved.append(
                    {"reference": key, "status": status, "code": error.code}
                )
                continue
            if not isinstance(reference, PassageReference) and not contains(
                connection, read.scope, read.ai_statuses, reference
            ):
                unresolved.append(
                    {
                        "reference": key,
                        "status": "outside_scope",
                        "code": "outside_pinned_scope",
                    }
                )
                continue
            resolved.append((key, reference, item))
        if not resolved:
            statuses = {entry["status"] for entry in unresolved}
            if "unavailable" in statuses:
                raise _Stop(
                    ToolLimitation(
                        reason="unavailable",
                        message="The requested evidence sources are not available to this "
                        "backend (no governance passage corpus or matching Tool metadata "
                        "snapshot is loaded).",
                    )
                )
            if "outside_scope" in statuses:
                raise _unsupported(
                    "The requested records exist but lie outside the pinned event-time "
                    "interval or filters."
                )
            return ToolSuccess(
                outcome="no_matches",
                summary="None of the requested records exist in the pinned Runs.",
                data={
                    "requested": len(references),
                    "resolved": [],
                    "unresolved": unresolved,
                },
                qualifications=read.warnings,
            )

        def build(count: int) -> ToolSuccess:
            shown = resolved[:count]
            omitted = [key for key, _, _ in resolved[count:]]
            notes = list(read.warnings)
            if unresolved:
                notes.append(
                    f"{len(unresolved)} requested reference(s) were not returned; see "
                    "data.unresolved for each status."
                )
            if omitted:
                notes.append(
                    f"Preview: {len(shown)} of {len(resolved)} resolved records fit the result "
                    "size limit; request data.omitted_for_size separately."
                )
            if any(item.truncated for _, _, item in shown):
                notes.append(
                    "Some long record fields are cut; see each record's truncations."
                )
            return ToolSuccess(
                outcome="data",
                summary=f"Resolved {len(resolved)} of {len(references)} requested references.",
                data={
                    "requested": len(references),
                    "resolved": [item.model_dump(mode="json") for _, _, item in shown],
                    "unresolved": unresolved,
                    "omitted_for_size": omitted,
                },
                # A resolved passage would need PassageEvidence; none resolve until #79.
                evidence=tuple(
                    _cite(reference)
                    for _, reference, _ in shown
                    if not isinstance(reference, PassageReference)
                ),
                qualifications=tuple(notes),
                truncated=bool(omitted),
            )

        return self._fit(build, len(resolved))

    # --- Shared pieces -------------------------------------------------------------------

    def _aggregate(
        self,
        read: _Read,
        operation: str,
        listing: str,
        query: dict,
        definitions: Sequence[str],
        *,
        suffix: str | None = None,
        start: str | None = None,
        end: str | None = None,
        focus: str | None = None,
    ) -> AggregateEvidence:
        """Evidence for counts: the full pinned scope, a reproducible listing query and a
        drilldown that opens the counted records."""
        filters = read.scope.filters
        if start is not None:
            filters = replace(filters, start=start, end=end)
        parameters = _parameters(filters, read.ai_statuses, listing)
        drilldown = dict(parameters)
        if focus is not None:
            drilldown.update(_focus_parameters(focus, filters))
        if read.ai_statuses:
            # Applied to Activity Events as GET /events' ai_determinations.
            query = {**query, "ai_statuses": list(read.ai_statuses)}
        return AggregateEvidence(
            evidence_id=":".join(
                ("aggregate", operation, *([suffix] if suffix else []))
            ),
            scope=read.pinned,
            operation=operation,
            query={"listing": listing, "parameters": parameters, **query},
            metric_definitions=tuple(definitions),
            drilldown_reference=f"{listing}?{urlencode(drilldown, doseq=True)}",
        )

    def _page(
        self,
        *,
        outcome: str,
        summary: str,
        data: dict,
        evidence: tuple[Evidence, ...],
        notes: list[str],
        noun: str,
        offset: int,
        returned: int,
        available: int,
        fingerprint: str,
    ) -> ToolSuccess:
        notes = list(notes)
        truncated = returned < available
        more = offset + returned < available
        if truncated:
            notes.append(
                f"Preview: {noun} {offset + 1 if returned else offset}-{offset + returned} of "
                f"{available}; totals and counts cover every matching record."
                + (" Pass the continuation to read more." if more else "")
            )
        return ToolSuccess(
            outcome=outcome,
            summary=summary,
            data={**data, "returned": returned},
            evidence=evidence,
            qualifications=tuple(dict.fromkeys(notes)),
            truncated=truncated,
            continuation=(
                f"{offset + returned}:{fingerprint}" if truncated and more else None
            ),
        )

    def _fit(self, build: Callable[[int], ToolSuccess], upper: int) -> ToolOutcome:
        """The largest result of at most ``upper`` items that fits the byte limit."""
        low, high = 0, upper
        if self._fits(best := build(high)):
            return best
        best = build(0)
        if not self._fits(best):
            raise _unsupported(
                "The result exceeds the assistant's size limit even as an empty preview; "
                "narrow the scope."
            )
        while low < high - 1:
            middle = (low + high) // 2
            if self._fits(candidate := build(middle)):
                low, best = middle, candidate
            else:
                high = middle
        return best

    def _fits(self, result: ToolSuccess) -> bool:
        size = len(
            json.dumps(result.model_dump(mode="json"), ensure_ascii=False).encode()
        )
        return size + _NAMESPACE_BYTES * len(result.evidence) <= self.max_result_bytes


_CONTEXT_AI_NOTE = (
    "Usage Contexts exist only for Tools determined AI: an ai_statuses filter that "
    "includes 'ai' does not restrict them, and one that excludes it matches none."
)


def build_tool_registry(
    engine: Engine,
    settings: Settings,
    *,
    limits: ExecutionLimits | None = None,
    sources: EvidenceSources | None = None,
) -> ToolRegistry:
    """Every query-backed tool, sized to ``limits``; ``retrieve_context`` stays unavailable.

    Pass the same ``limits`` to ``Assistant``. ``sources`` defaults to the Tool metadata
    snapshot at ``settings.tool_metadata_path`` and no passage corpus.
    """
    limits = limits or ExecutionLimits()
    if sources is None:
        path = settings.tool_metadata_path
        sources = EvidenceSources(
            tool_metadata=load_tool_metadata(path) if path.is_file() else None
        )
    tools = QueryTools(engine, sources, limits.max_tool_result_bytes)
    return ToolRegistry(tools.handlers())


# --- Scope mapping ---------------------------------------------------------------------


def _verify(connection: Connection, pinned: PinnedScope) -> _Read:
    """Resolve the pinned scope with explicit Runs and check each belongs to its Batch and
    succeeded. A scope that fails is an integration error, so the call fails safely."""
    filters = _filters(pinned)
    try:
        scope = resolve_scope(connection, filters)
    except AppError as error:
        raise _Stop(
            _SCOPE_FAILURES.get(error.status_code, _SCOPE_FAILURES[422])
        ) from None
    selected = {(s.batch_id, s.run_id) for s in scope.selections}
    if selected != {(r.batch_id, r.run_id) for r in pinned.runs}:
        raise _Stop(_SCOPE_FAILURES[422])
    overlap = observe_activity(connection, scope).warnings
    warnings = tuple(
        dict.fromkeys(_warning_text(w) for w in (*scope.warnings, *overlap))
    )
    return _Read(pinned, scope, pinned.filters.ai_statuses, warnings)


_SCOPE_FAILURES = {
    404: ToolFailure(
        code="scope_run_not_found",
        message="A pinned Batch or Analysis Run was not found.",
    ),
    409: ToolFailure(
        code="scope_run_not_succeeded",
        message="A pinned Analysis Run did not succeed, so it has no results.",
    ),
    422: ToolFailure(
        code="scope_run_batch_mismatch",
        message="A pinned Analysis Run does not belong to its named Batch.",
    ),
}


def _filters(pinned: PinnedScope) -> Filters:
    """Assistant filter names onto ``app.scope.Filters``; ``ai_statuses`` is applied by the
    adapters as ``GET /events``'s ``ai_determinations``."""
    requested = pinned.filters
    allowed = set(CATEGORIES) | set(CATEGORY_OUTCOMES)
    if any(category not in allowed for category in requested.categories):
        raise _unsupported(
            "A Category filter value is not one of the 14 Categories, 'unresolved' or "
            "'inapplicable'."
        )
    return Filters(
        batch_ids=tuple(run.batch_id for run in pinned.runs),
        run_ids=tuple(run.run_id for run in pinned.runs),
        departments=requested.departments,
        categories=requested.categories,
        risk_tiers=requested.risk_tiers,
        flagged=requested.flagged,
        start=event_time_bound(pinned.event_time.start),
        end=event_time_bound(pinned.event_time.end),
    )


def _parameters(
    filters: Filters, ai_statuses: Sequence[str], listing: str
) -> dict[str, Any]:
    """The listing's query parameters for ``filters``, omitting empty ones."""
    parameters: dict[str, Any] = {
        "batch_ids": list(filters.batch_ids),
        "run_ids": list(filters.run_ids),
        "start": filters.start,
        "end": filters.end,
        "departments": list(filters.departments),
        "categories": list(filters.categories),
        "policy_statuses": list(filters.policy_statuses),
        "risk_tiers": list(filters.risk_tiers),
        "flagged": None if filters.flagged is None else str(filters.flagged).lower(),
    }
    if ai_statuses and listing in ("GET /events", "GET /applications"):
        parameters["ai_determinations"] = list(ai_statuses)
    return {key: value for key, value in parameters.items() if value not in (None, [])}


def _focus_parameters(focus: str, filters: Filters) -> dict[str, Any]:
    """``GET /contexts`` parameters narrowing to a focus, where the API can express it."""
    if focus == "flagged" and filters.flagged is None:
        return {"flagged": "true"}
    if focus == "unapproved":
        return {"policy_statuses": ["unapproved"]}
    if focus == "unresolved" and not filters.risk_tiers:
        return {"risk_tiers": ["unresolved"]}
    return {}


def _warning_text(warning) -> str:
    where = ", ".join(
        f"{name} {value}"
        for name, value in (("Batch", warning.batch_id), ("Run", warning.run_id))
        if value
    )
    return f"{warning.code}: {warning.message}" + (f" ({where})" if where else "")


def _coverage(scope: Scope, start: str, end: str) -> str:
    """Whether one selected Batch's activity period spans ``[start, end)`` (full), any
    overlaps it (partial), or none does."""
    periods = [(b.batch.activity_start, b.batch.activity_end) for b in scope.batches]
    if any(first <= start and last >= _before(end) for first, last in periods):
        return "full"
    if any(first < end and last >= start for first, last in periods):
        return "partial"
    return "none"


def _before(end: str) -> str:
    """The last whole second before an exclusive stored-form bound."""
    instant = datetime.strptime(end, "%Y-%m-%dT%H:%M:%SZ") - timedelta(seconds=1)
    return instant.isoformat(timespec="seconds") + "Z"


# --- Continuation and references -------------------------------------------------------


def _fingerprint(tool: str, pinned: PinnedScope, arguments: Contract) -> str:
    """Binds a continuation to its tool, scope and arguments (page size may change)."""
    payload = {
        "tool": tool,
        "scope": pinned.model_dump(mode="json"),
        "arguments": arguments.model_dump(
            mode="json", exclude={"continuation", "limit"}
        ),
    }
    return sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()[:16]


def _offset(continuation: str | None, fingerprint: str) -> int:
    if continuation is None:
        return 0
    offset, _, issued_for = continuation.partition(":")
    if issued_for != fingerprint or not offset.isdigit():
        raise _unsupported(
            "The continuation does not belong to this request and scope; repeat the "
            "request without it."
        )
    return int(offset)


def _parse_reference(
    text: str, pinned: PinnedScope
) -> RecordReference | PassageReference:
    """``<record_type>:<run_id>:<record_id>`` or ``passage:<corpus_version>:<document_id>:
    <document_version>:<passage_id>``, optionally prefixed with the step ID that issued it.
    """
    kind, _, rest = text.partition(":")
    if kind not in (*_RECORD_TYPES, "passage", "aggregate"):
        kind, _, rest = rest.partition(":")
    if kind == "aggregate":
        raise _unsupported(
            "Aggregate evidence is not a stored record; open the records behind it through "
            "its drilldown_reference, or narrow the scope and summarize again."
        )
    if kind == "passage":
        parts = rest.split(":")
        try:
            return PassageReference(
                **dict(
                    zip(
                        (
                            "corpus_version",
                            "document_id",
                            "document_version",
                            "passage_id",
                        ),
                        parts,
                        strict=True,
                    )
                )
            )
        except (ValueError, ValidationError):
            raise _unsupported("A passage reference is malformed.") from None
    if kind not in _RECORD_TYPES:
        raise _unsupported(
            "References must be evidence IDs from earlier tool results or "
            "'<record_type>:<run_id>:<record_id>' for a pinned Run."
        )
    for run in pinned.runs:
        if rest == run.run_id and kind == "analysis_run":
            return AnalysisRunReference(run=run)
        if rest.startswith(f"{run.run_id}:"):
            try:
                return record_reference(run, kind, rest.removeprefix(f"{run.run_id}:"))
            except EvidenceError:
                raise _unsupported(
                    "A reference is not a valid record reference."
                ) from None
    raise _unsupported("A reference names a Run outside the pinned scope.")


def _reference_key(reference: RecordReference | PassageReference) -> str:
    if isinstance(reference, PassageReference):
        return ":".join(
            (
                "passage",
                reference.corpus_version,
                reference.document_id,
                reference.document_version,
                reference.passage_id,
            )
        )
    return _cite(reference).evidence_id


def _cite(reference: RecordReference) -> RecordEvidence:
    """Record evidence whose local ID, ``<record_type>:<run_id>:<record_id>``, reopens it."""
    evidence = to_record_evidence(reference, "local")
    return evidence.model_copy(
        update={
            "evidence_id": f"{evidence.record_type}:{reference.run.run_id}:{evidence.record_id}"
        }
    )
