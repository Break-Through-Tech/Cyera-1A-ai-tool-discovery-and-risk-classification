"""Usage Contexts and their contextual-risk assessments.

PROJECT_PLAN.md, "Initial contextual-risk contract": a Usage Context is one AI Tool's
observed activity for one department, supplied purpose and data-sensitivity tier within the
Batch. Only resolved Tools that AI Determination called AI get contexts, so unresolved
identity or AI status never receives a tier. Dataset B supplies the rubric facts; a Tool
without a Dataset B row has every fact unknown and stays unresolved.
"""

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass

from app.ai_determination.cascade import AiDetermination
from app.pipeline.identity import CandidateIdentity, ToolMetadataSnapshot, normalize_name
from app.pipeline.risk import RISK_RULE_VERSION, Assessment, RiskFacts, assess

RESOLVED_OUTCOMES = {"known_tool", "observed_tool"}
_CONTEXT_FIELDS = ("department", "usage_purpose", "data_sensitivity_tier")


@dataclass(frozen=True)
class UsageContext:
    tool_id: str
    application_name: str
    domain: str
    department: str
    usage_purpose: str
    data_sensitivity_tier: str
    event_ids: tuple[str, ...]
    first_observed_at: str
    last_observed_at: str


@dataclass(frozen=True)
class ContextAssessment:
    context: UsageContext
    metadata_id: str | None
    facts: RiskFacts
    assessment: Assessment
    rule_version: str = RISK_RULE_VERSION


def risk_facts(row: Mapping[str, str] | None) -> RiskFacts:
    """The rubric facts in a Dataset B row; a missing row or blank value is unknown."""
    row = row or {}

    def fact(column: str) -> str:
        return (row.get(column) or "").strip() or "unknown"

    return RiskFacts(
        policy_status=fact("approved_status"),
        training_on_customer_data=fact("training_on_customer_data"),
        admin_controls_available=fact("admin_controls_available"),
    )


def assess_usage_contexts(
    events: Iterable[Mapping[str, str | None]],
    identities: Sequence[CandidateIdentity],
    ai_determinations: Sequence[AiDetermination],
    metadata: ToolMetadataSnapshot,
) -> list[ContextAssessment]:
    by_event_id = {event["event_id"]: event for event in events}
    assessed = []
    for candidate, ai in zip(identities, ai_determinations, strict=True):
        if candidate.outcome not in RESOLVED_OUTCOMES or ai.determination != "ai":
            continue
        row = metadata.find(candidate.domain, normalize_name(candidate.application_names[0]))
        facts = risk_facts(row)
        assessment = assess(facts)
        for context in _usage_contexts(candidate, by_event_id):
            assessed.append(
                ContextAssessment(context, row["metadata_id"] if row else None, facts, assessment)
            )
    return assessed


def _usage_contexts(
    candidate: CandidateIdentity, by_event_id: Mapping[str, Mapping[str, str | None]]
) -> list[UsageContext]:
    groups: dict[tuple[str, ...], list[Mapping[str, str | None]]] = {}
    for event_id in candidate.event_ids:
        event = by_event_id[event_id]
        key = tuple((event.get(field) or "").strip() or "unknown" for field in _CONTEXT_FIELDS)
        groups.setdefault(key, []).append(event)
    return [
        UsageContext(
            candidate.tool_id,
            candidate.application_names[0],
            candidate.domain,
            *key,
            event_ids=tuple(event["event_id"] for event in grouped),
            first_observed_at=min(event["occurred_at"] for event in grouped),
            last_observed_at=max(event["occurred_at"] for event in grouped),
        )
        for key, grouped in sorted(groups.items())
    ]
