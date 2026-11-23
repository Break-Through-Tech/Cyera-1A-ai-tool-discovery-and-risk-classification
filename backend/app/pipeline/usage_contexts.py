"""Usage Contexts and their contextual-risk assessments (`owasp-usage-risk-v2`, ADR 0005).

A Usage Context is one Tool's observed activity for one department, supplied purpose,
data-sensitivity tier and interaction class within the Batch. Different kinds of use are
never merged. Only resolved Tools that AI Determination called AI are assessed. Usage of a
Tool whose identity or AI status is unresolved is recorded as ``not_assessed`` (no tier), so
it stays visible; non-AI Tools get no context. Dataset B supplies tool-wide rubric facts; a Tool
without a Dataset B row has every fact unknown, is not in the AI inventory, and stays
unresolved. Each context is assessed on its own and gets a template-built explanation.
"""

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from app.ai_determination.cascade import AiDetermination
from app.category.classify import CategoryClassification
from app.pipeline.identity import CandidateIdentity, ToolMetadataSnapshot, normalize_name
from app.pipeline.risk import (
    FACT_SCOPE,
    RISK_RULE_VERSION,
    TOOL_FACTS,
    Assessment,
    RiskFacts,
    assess,
    interaction_class,
    not_assessed,
    normalize_fact,
    purpose_class,
)
from app.pipeline.risk_explain import explain
from app.pipeline.risk_refs import references

RESOLVED_OUTCOMES = {"known_tool", "observed_tool"}
_CONTEXT_FIELDS = ("department", "usage_purpose", "data_sensitivity_tier", "interaction_class")
_METADATA_COLUMNS = {
    "policy_status": "approved_status",
    "training_on_customer_data": "training_on_customer_data",
    "admin_controls_available": "admin_controls_available",
}


@dataclass(frozen=True)
class UsageContext:
    tool_id: str
    application_name: str
    domain: str
    department: str
    usage_purpose: str
    data_sensitivity_tier: str
    interaction_class: str
    event_ids: tuple[str, ...]
    event_types: tuple[str, ...]
    distinct_employee_count: int
    first_observed_at: str
    last_observed_at: str


@dataclass(frozen=True)
class ContextAssessment:
    context: UsageContext
    metadata_id: str | None
    facts: RiskFacts
    assessment: Assessment
    category: str | None = None
    category_method: str | None = None
    purpose_class: str = "unknown"
    concern_tags: tuple[str, ...] = ()
    framework_refs: list[dict[str, Any]] = field(default_factory=list)
    explanation: str = ""
    explanation_parts: dict[str, Any] = field(default_factory=dict)
    fact_scope: str = FACT_SCOPE
    rule_version: str = RISK_RULE_VERSION


def tool_facts(row: Mapping[str, str] | None) -> tuple[dict[str, str], dict[str, str]]:
    """The tool-wide rubric facts in a Dataset B row, and any unrecognized original values.

    A missing row or blank value is unknown; an unrecognized value is unknown and its original
    value is returned so the explanation parts keep it.
    """
    row = row or {}
    values, unrecognized = {}, {}
    for name, column in _METADATA_COLUMNS.items():
        values[name], original = normalize_fact(name, row.get(column))
        if original is not None:
            unrecognized[name] = original
    return values, unrecognized


def risk_facts(
    row: Mapping[str, str] | None,
    data_sensitivity_tier: str = "unknown",
    interaction_class: str = "unknown",
) -> RiskFacts:
    """The rubric facts for one context: the Tool's Dataset B row plus the context's fields."""
    values, _ = tool_facts(row)
    sensitivity, _ = normalize_fact("data_sensitivity_tier", data_sensitivity_tier)
    return RiskFacts(
        **values,
        data_sensitivity_tier=sensitivity,
        interaction_class=interaction_class,
        in_inventory=row is not None,
    )


def assess_usage_contexts(
    events: Iterable[Mapping[str, str | None]],
    identities: Sequence[CandidateIdentity],
    ai_determinations: Sequence[AiDetermination],
    category_classifications: Sequence[CategoryClassification],
    metadata: ToolMetadataSnapshot,
) -> list[ContextAssessment]:
    by_event_id = {event["event_id"]: event for event in events}
    assessed = []
    for candidate, ai, classification in zip(
        identities, ai_determinations, category_classifications, strict=True
    ):
        if ai.determination == "non_ai":
            continue
        identity_resolved = candidate.outcome in RESOLVED_OUTCOMES
        eligible = identity_resolved and ai.determination == "ai"
        row = metadata.find(candidate.domain, normalize_name(candidate.application_names[0]))
        _, unrecognized_tool = tool_facts(row)
        for context in _usage_contexts(candidate, by_event_id):
            facts = risk_facts(row, context.data_sensitivity_tier, context.interaction_class)
            unrecognized = dict(unrecognized_tool)
            _, original = normalize_fact("data_sensitivity_tier", context.data_sensitivity_tier)
            if original is not None:
                unrecognized["data_sensitivity_tier"] = original
            if eligible:
                assessment = assess(facts, context.event_ids)
            else:
                assessment = not_assessed(facts, identity_resolved, ai.determination)
            assessed.append(
                _assess_context(context, row, facts, assessment, unrecognized, classification, ai)
            )
    return assessed


def _assess_context(
    context: UsageContext,
    row: Mapping[str, str] | None,
    facts: RiskFacts,
    assessment: Assessment,
    unrecognized: dict[str, str],
    classification: CategoryClassification,
    ai: AiDetermination,
) -> ContextAssessment:
    category = classification.category if classification.outcome == "assigned" else None
    method = classification.method if category else None
    explanation = explain(
        context,
        facts,
        assessment,
        category,
        method,
        classification.share if category else None,
        unrecognized,
        ai.stage,
        ai.reason,
    )
    purpose_cls, concern_tags = purpose_class(context.usage_purpose)
    return ContextAssessment(
        context=context,
        metadata_id=row["metadata_id"] if row else None,
        facts=facts,
        assessment=assessment,
        category=category,
        category_method=method,
        purpose_class=purpose_cls,
        concern_tags=concern_tags,
        framework_refs=references([*assessment.reason_codes, *assessment.flag_reasons]),
        explanation=explanation.text,
        explanation_parts=explanation.parts,
    )


def _usage_contexts(
    candidate: CandidateIdentity, by_event_id: Mapping[str, Mapping[str, str | None]]
) -> list[UsageContext]:
    groups: dict[tuple[str, ...], list[Mapping[str, str | None]]] = {}
    for event_id in candidate.event_ids:
        event = by_event_id[event_id]
        values = {
            "department": event.get("department"),
            "usage_purpose": event.get("usage_purpose"),
            "data_sensitivity_tier": event.get("data_sensitivity_tier"),
            "interaction_class": interaction_class(event.get("event_type")),
        }
        key = tuple((values[name] or "").strip() or "unknown" for name in _CONTEXT_FIELDS)
        groups.setdefault(key, []).append(event)
    return [
        UsageContext(
            candidate.tool_id or f"unresolved:{candidate.domain}",
            candidate.application_names[0],
            candidate.domain,
            *key,
            event_ids=tuple(event["event_id"] for event in grouped),
            event_types=tuple(
                sorted({(event.get("event_type") or "").strip() or "unknown" for event in grouped})
            ),
            distinct_employee_count=len(
                {event.get("employee_id") for event in grouped if event.get("employee_id")}
            ),
            first_observed_at=min(event["occurred_at"] for event in grouped),
            last_observed_at=max(event["occurred_at"] for event in grouped),
        )
        for key, grouped in sorted(groups.items())
    ]
