"""Template-built Risk Explanation for one assessed Usage Context.

Implements docs/risk-rubric-v2.md, section 6 (rubric v2.1). The text is filled from fixed slots in a fixed
order, and a slot is never dropped to make room for another. No LLM writes it. It never names
or counts employees, never says content was submitted unless the class is content submission,
never says access was granted unless the class is access grant, and never calls a tier a
compliance finding, an incident or a policy violation.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Any

from app.pipeline.risk import FACT_SCOPE, Assessment, RiskFacts, purpose_class
from app.pipeline.risk_refs import references

if TYPE_CHECKING:
    from app.pipeline.usage_contexts import UsageContext

_PRESENCE = "only visits were observed"
_UNKNOWN_ACTIVITY = "the activity type was not recorded"
# Activity phrases per event type, in the order they are joined.
_ACTIVITY = (
    ("prompt_submit", "prompts were submitted"),
    ("chat_message", "prompts were submitted"),
    ("content_paste", "pasted content was observed"),
    ("file_upload", "file uploads were observed"),
    ("oauth_grant", "the tool was granted OAuth access"),
    ("connector_added", "a connector to company systems was added"),
)
_SUBMISSION_VERBS = (
    ("file_upload", "uploaded"),
    ("content_paste", "pasted"),
    ("prompt_submit", "submitted"),
    ("chat_message", "submitted"),
)
_GRANT_PHRASES = (
    ("oauth_grant", "OAuth access was granted"),
    ("connector_added", "a connector was added"),
)
_ADVERSE_PHRASES = {
    "unapproved_tool": "the tool is not approved",
    "customer_data_training_permitted": "the vendor may train on customer data",
    "admin_controls_absent": "the tool has no admin controls",
}
_GOVERNED_PHRASE = (
    "the tool is approved, the vendor does not train on customer data and admin controls "
    "are available"
)
_UNGOVERNED_PHRASE = "the tool is not approved and the vendor may train on customer data"
_FACT_LABELS = {
    "policy_status": "approval status",
    "training_on_customer_data": "training terms",
    "admin_controls_available": "admin-control terms",
}
_ASSUMPTION = "Sensitivity unknown; tier calculated using the internal-data assumption."


@dataclass(frozen=True)
class Explanation:
    text: str
    parts: dict[str, Any]


def explain(
    context: "UsageContext",
    facts: RiskFacts,
    assessment: Assessment,
    category: str | None = None,
    category_method: str | None = None,
    category_share: float | None = None,
    unrecognized_values: dict[str, str] | None = None,
    ai_stage: str | None = None,
    ai_reason: str | None = None,
) -> Explanation:
    """The explanation text and its structured slots for one Usage Context.

    ``ai_stage`` and ``ai_reason`` (from AI Determination) word a ``not_assessed`` result.
    """
    sensitivity = facts.data_sensitivity_tier
    unresolved = assessment.tier == "unresolved"
    skipped = assessment.tier == "not_assessed"
    review = _review_clauses(assessment, facts)
    purpose_cls, concern_tags = purpose_class(context.usage_purpose)

    # The unresolved template replaces all three sentences; ``usage`` is still kept in parts.
    usage = _usage_sentence(context, facts, assessment, category, category_method)
    detail: list[str] = []
    if skipped:
        reason = _not_assessed_sentence(assessment, ai_stage, ai_reason)
        sentences = [usage, reason]
        review = []
    elif unresolved:
        reason = (
            f"{context.application_name} has no usable approval or vendor facts, "
            "so no risk level was assigned."
        )
        sentences = [reason]
        if "sensitive_use_of_unassessed_tool" in assessment.flag_reasons:
            sentences.append(f"It was used with {sensitivity} data and needs review.")
    else:
        reason = _reason_sentence(context, facts, assessment)
        detail = _detail_clauses(facts, assessment)
        sentences = [usage, reason, *detail]
    sentences += review

    parts = {
        "usage": usage,
        "unresolved_template": unresolved,
        "not_assessed": skipped,
        "ai_stage": ai_stage,
        "ai_reason": ai_reason,
        "reason": reason,
        "detail": detail,
        "review": review,
        "reasons": list(assessment.reason_codes),
        "tier": assessment.tier,
        "base_tier": assessment.base_tier,
        "governance_level": assessment.governance_level,
        "exposure_level": assessment.exposure_level,
        "escalation": assessment.escalation,
        "escalation_reason": assessment.escalation_reason,
        "tier_raised": assessment.tier_raised,
        "escalation_event_ids": list(assessment.escalation_event_ids),
        "assumptions": ["sensitivity_assumed_internal"] if assessment.sensitivity_assumed else [],
        "unknowns": list(assessment.unknown_facts),
        "unrecognized_values": dict(unrecognized_values or {}),
        "review_flags": [
            flag for flag in assessment.flag_reasons if flag.endswith("_with_missing_facts")
        ],
        "flags": list(assessment.flag_reasons),
        "refs": references([*assessment.reason_codes, *assessment.flag_reasons]),
        "category": category,
        "category_method": category_method,
        "category_share": category_share,
        "purpose_class": purpose_cls,
        "concern_tags": list(concern_tags),
        "interaction_class": facts.interaction_class,
        "event_types": list(context.event_types),
        "event_count": len(context.event_ids),
        "first_observed_at": context.first_observed_at,
        "last_observed_at": context.last_observed_at,
        "fact_scope": FACT_SCOPE,
    }
    return Explanation(" ".join(sentences), parts)


# Sentence 1: how the tool was used.


def _usage_sentence(
    context: "UsageContext",
    facts: RiskFacts,
    assessment: Assessment,
    category: str | None,
    category_method: str | None,
) -> str:
    department = context.department if context.department != "unknown" else "An unstated department"
    category_phrase = ""
    if category and category_method == "catalog":
        category_phrase = f", {_article(category)} {category} tool,"
    elif category and category_method == "semantic_neighbor_vote":
        category_phrase = f", likely {_article(category)} {category} tool,"
    purpose = _purpose_phrase(context.usage_purpose)
    sensitivity = (
        "data of unknown sensitivity"
        if assessment.sensitivity_assumed
        else f"{facts.data_sensitivity_tier} data"
    )
    n = len(context.event_ids)
    events = f"{n} event{'s' if n != 1 else ''}, "
    dates = _date_range(context.first_observed_at, context.last_observed_at)
    activity = _activity_phrase(facts.interaction_class, context.event_types)
    return (
        f"{department} used {context.application_name}{category_phrase} for {purpose} "
        f"with {sensitivity} ({events}{dates}); {activity}."
    )


def _activity_phrase(cls: str, event_types: Sequence[str]) -> str:
    if cls == "presence":
        return _PRESENCE
    if cls == "unknown":
        return _UNKNOWN_ACTIVITY
    phrases = _ordered_unique(phrase for type_, phrase in _ACTIVITY if type_ in event_types)
    return _join(phrases) if phrases else _UNKNOWN_ACTIVITY


def _date_range(first: str, last: str) -> str:
    start, end = _parse(first), _parse(last)
    if start.date() == end.date():
        return f"{start.day} {start:%b}"
    if (start.year, start.month) == (end.year, end.month):
        return f"{start.day}–{end.day} {end:%b}"
    if start.year == end.year:
        return f"{start.day} {start:%b}–{end.day} {end:%b}"
    return f"{start.day} {start:%b} {start.year}–{end.day} {end:%b} {end.year}"


def _parse(timestamp: str) -> datetime:
    return datetime.fromisoformat(timestamp.replace("Z", "+00:00"))


# Sentence 2: why it got this level.


def _reason_sentence(
    context: "UsageContext", facts: RiskFacts, assessment: Assessment
) -> str:
    governance = _governance_phrase(facts, assessment)
    # A governance phrase that already joins facts with "and" takes a comma before the next.
    joiner = ", and " if " and " in governance else " and "
    because = f"{governance}{joiner}{_exposure_phrase(facts, assessment)}"
    if assessment.escalation is None:
        return f"Rated {assessment.tier} because {because}."
    escalation = _escalation_phrase(context, facts, assessment)
    if assessment.tier_raised:
        return (
            f"Rated {assessment.tier}: {assessment.base_tier} because {because}, "
            f"raised one step because {escalation}."
        )
    return f"Rated {assessment.tier} because {because}; {escalation} was also observed."


def _governance_phrase(facts: RiskFacts, assessment: Assessment) -> str:
    level = assessment.governance_level
    if level == "governed":
        return _GOVERNED_PHRASE
    if level == "ungoverned":
        return _UNGOVERNED_PHRASE
    if level == "adverse":
        first = next(code for code in assessment.reason_codes if code in _ADVERSE_PHRASES)
        return _ADVERSE_PHRASES[first]
    return _unknown_controls_phrase(assessment.unknown_facts)


def _unknown_controls_phrase(unknown_facts: Sequence[str]) -> str:
    """``controls_unconfirmed``: "the vendor's {unknown facts} {is/are} unknown"."""
    pieces = []
    if "policy_status" in unknown_facts:
        pieces.append("the tool's approval status")
    vendor = [
        _FACT_LABELS[name]
        for name in ("training_on_customer_data", "admin_controls_available")
        if name in unknown_facts
    ]
    if vendor:
        pieces.append("the vendor's " + _join_terms(vendor))
    plural = len(pieces) > 1 or bool(vendor)
    return f"{_join(pieces)} {'are' if plural else 'is'} unknown"


def _exposure_phrase(facts: RiskFacts, assessment: Assessment) -> str:
    if assessment.sensitivity_assumed:
        return "no data sensitivity was supplied"
    sensitivity = facts.data_sensitivity_tier
    if sensitivity == "public":
        return "only public data is involved"
    if sensitivity == "confidential" and assessment.governance_level in {"adverse", "ungoverned"}:
        return "confidential data should not go into a tool that isn't business-managed"
    return f"{sensitivity} data is involved"


def _escalation_phrase(
    context: "UsageContext", facts: RiskFacts, assessment: Assessment
) -> str:
    if assessment.escalation == "X1":
        verbs = _ordered_unique(
            verb for type_, verb in _SUBMISSION_VERBS if type_ in context.event_types
        ) or ["submitted"]
        return (
            f"{facts.data_sensitivity_tier} content was {_join(verbs)} to a tool that is not "
            "fully governed"
        )
    grants = [phrase for type_, phrase in _GRANT_PHRASES if type_ in context.event_types]
    return f"{_join(grants or ['access was granted'])} to a tool with an adverse governance fact"


# Sentence 3: assumptions, unnamed unknown facts and review clauses.


def _detail_clauses(facts: RiskFacts, assessment: Assessment) -> list[str]:
    """The assumption sentence, then unknown vendor facts sentence 2 did not name."""
    clauses = [_ASSUMPTION] if assessment.sensitivity_assumed else []
    if assessment.governance_level == "partial":
        return clauses  # sentence 2 already names every unknown vendor fact
    unknown = [
        _FACT_LABELS[name]
        for name in ("policy_status", "training_on_customer_data", "admin_controls_available")
        if name in assessment.unknown_facts
    ]
    if unknown:
        joined = _join_terms(unknown)
        verb = "is" if unknown == ["approval status"] else "are"
        clauses.append(f"{joined[0].upper()}{joined[1:]} {verb} unknown.")
    return clauses


def _review_clauses(assessment: Assessment, facts: RiskFacts) -> list[str]:
    clauses = []
    if "submission_with_missing_facts" in assessment.flag_reasons:
        missing = []
        if assessment.sensitivity_assumed:
            missing.append("a known data sensitivity")
        if "training_on_customer_data" in assessment.unknown_facts:
            missing.append("known vendor training terms")
        clauses.append(f"Review: content was submitted without {' or '.join(missing)}.")
    if "access_grant_with_missing_facts" in assessment.flag_reasons:
        missing = []
        if facts.policy_status == "unknown":
            missing.append("a known approval status")
        if facts.admin_controls_available == "unknown":
            missing.append("known admin controls")
        clauses.append(f"Review: access was granted without {' or '.join(missing)}.")
    return clauses


def _article(word: str) -> str:
    return "an" if word[:1].lower() in "aeiou" else "a"


def _ordered_unique(items) -> list[str]:
    seen: list[str] = []
    for item in items:
        if item not in seen:
            seen.append(item)
    return seen


def _join(items: Sequence[str]) -> str:
    items = list(items)
    if len(items) <= 1:
        return "".join(items)
    return ", ".join(items[:-1]) + " and " + items[-1]


def _join_terms(labels: Sequence[str]) -> str:
    """Join fact labels, sharing a trailing "terms": "training and admin-control terms"."""
    terms = [label for label in labels if label.endswith(" terms")]
    if len(terms) > 1:
        shared = _join([label.removesuffix(" terms") for label in terms]) + " terms"
        others = [label for label in labels if not label.endswith(" terms")]
        return _join([*others, shared])
    return _join(labels)


# Natural phrases for known purposes; others turn underscores into spaces.
_PURPOSE_PHRASES = {
    "draft_summary": "drafting summaries",
    "text_analysis": "text analysis",
    "code_assistance": "code assistance",
    "software_development": "software development",
    "email_campaigns": "email campaigns",
    "sales_outreach": "sales outreach",
    "visual_testing": "visual testing",
    "product_ideation": "product ideation",
    "team_messaging": "team messaging",
}


def _purpose_phrase(usage_purpose: str) -> str:
    if usage_purpose == "unknown":
        return "an unstated purpose"
    return _PURPOSE_PHRASES.get(usage_purpose, usage_purpose.replace("_", " "))


# Not assessed: why the Tool is not a resolved AI Tool.

_EVIDENCE_GAPS = {
    "no_evidence": "its homepage could not be read and no description was supplied",
    "insufficient_text": "its homepage had too little text to judge and no description was supplied",
    "jev_judge": "the AI judge could not decide from the available text",
}


def _not_assessed_sentence(
    assessment: Assessment, ai_stage: str | None, ai_reason: str | None
) -> str:
    codes = assessment.reason_codes
    if "identity_unresolved" in codes and "ai_status_unresolved" in codes:
        why = "the tool could not be identified and its AI status is unresolved"
    elif "identity_unresolved" in codes:
        why = "the tool could not be identified"
    else:
        why = "its AI status is unresolved"
    gap = _EVIDENCE_GAPS.get(ai_stage or "") if "ai_status_unresolved" in codes else None
    detail = f": {gap}" if gap else ""
    return f"Not assessed because {why}{detail}. No risk level was assigned; review this usage."
