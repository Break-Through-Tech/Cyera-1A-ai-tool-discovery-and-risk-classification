"""Deterministic contextual-risk rubric for one Usage Context (`owasp-usage-risk-v2`).

This is the project's versioned synthetic demonstration policy, confirmed in
docs/risk-rubric-v2.md and ADR 0005. It is not Cyera policy, not an OWASP-prescribed tiering,
and not a compliance determination. No LLM chooses the tier.

1. The three tool-wide Dataset B facts give a Governance Level.
2. The supplied data sensitivity gives an Exposure Level; unknown is calculated as internal
   and always disclosed.
3. The acceptable-use matrix turns the two levels into a base tier; an unassessed Tool stays
   ``unresolved``.
4. Content submission or an access grant may raise the tier one step (never down).

`unknown` is never treated as the favourable value, and conditional training counts as unknown.
"""

from collections.abc import Sequence
from dataclasses import dataclass, field

RISK_RULE_VERSION = "owasp-usage-risk-v2"
FACT_SCOPE = "tool_wide_scenario_assumption"
TIERS = ("Low", "Medium", "High", "unresolved")

_ALLOWED = {
    "policy_status": {"approved", "unapproved", "unknown"},
    "training_on_customer_data": {"yes", "no", "conditional", "unknown"},
    "admin_controls_available": {"yes", "no", "unknown"},
    "data_sensitivity_tier": {"public", "internal", "confidential", "restricted", "unknown"},
    "interaction_class": {"presence", "content_submission", "access_grant", "unknown"},
}
TOOL_FACTS = ("policy_status", "training_on_customer_data", "admin_controls_available")

# Section 2.3: exposure level of the supplied sensitivity. ``unknown`` is the assumed internal.
EXPOSURE = {"public": 0, "internal": 1, "unknown": 1, "confidential": 2, "restricted": 3}
EXPOSURE_LABELS = ("E0", "E1", "E2", "E3")

# Section 3.1: the acceptable-use matrix. Changing a cell is a new rule version.
MATRIX = {  # exposure: public    internal  confidential  restricted
    "governed": ("Low", "Low", "Low", "Medium"),
    "partial": ("Low", "Medium", "Medium", "High"),
    "adverse": ("Medium", "Medium", "High", "High"),
    "ungoverned": ("Medium", "High", "High", "High"),
}
STEP_UP = {"Low": "Medium", "Medium": "High", "High": "High"}
ESCALATION_CODES = {
    "X1": "sensitive_content_submitted_to_non_governed_tool",
    "X2": "access_granted_to_non_governed_tool",
}
_EXPOSURE_CODES = (
    "public_data_context",
    "internal_data_context",
    "confidential_data_context",
    "restricted_data_context",
)

# Section 2.4: event type -> interaction class. Anything else is ``unknown``, deliberately
# including extension_install, api_key_use and agent_action, until a rule says what they prove.
INTERACTION_CLASS = {
    "browser_visit": "presence",
    "app_open": "presence",
    "login": "presence",
    "prompt_submit": "content_submission",
    "chat_message": "content_submission",
    "content_paste": "content_submission",
    "file_upload": "content_submission",
    "oauth_grant": "access_grant",
    "connector_added": "access_grant",
}

# Section 2.5: purpose classes inform the explanation only and never change the tier.
PURPOSE_CLASSES = {
    "code_assistance": "code_generation",
    "software_development": "code_generation",
    "email_campaigns": "external_communication",
    "sales_outreach": "external_communication",
    "draft_summary": "content_analysis",
    "text_analysis": "content_analysis",
    "visual_testing": "automation_testing",
    "product_ideation": "ideation",
}
CONCERN_TAGS = {
    "code_generation": (
        "LLM02 (source code)",
        "LLM04 (hallucinated packages)",
        "LLM10 (AI-written code)",
    ),
    "external_communication": ("LLM07 (output reaches customers)", "LLM02 (prospect personal data)"),
    "content_analysis": ("LLM02 (documents submitted)", "LLM07 (decisions built on output)"),
    "automation_testing": ("LLM03 (the tool acts on systems)",),
    "ideation": ("LLM02 (unreleased plans)",),
    "unknown": (),
}


def interaction_class(event_type: str | None) -> str:
    """The interaction class of one event type; blank or unrecognized types are ``unknown``."""
    return INTERACTION_CLASS.get((event_type or "").strip().lower(), "unknown")


def purpose_class(usage_purpose: str | None) -> tuple[str, tuple[str, ...]]:
    """The purpose class of a supplied purpose and the concern tags shown with the result."""
    cls = PURPOSE_CLASSES.get((usage_purpose or "").strip().lower(), "unknown")
    return cls, CONCERN_TAGS[cls]


def normalize_fact(name: str, value: str | None) -> tuple[str, str | None]:
    """A rubric value and, when it was not recognized, the original value it replaced.

    Blank becomes ``unknown`` silently; an unrecognized value also becomes ``unknown`` but is
    returned so the explanation parts can keep it (rubric section 2).
    """
    cleaned = (value or "").strip()
    if not cleaned:
        return "unknown", None
    lowered = cleaned.lower()
    if lowered in _ALLOWED[name]:
        return lowered, None
    return "unknown", cleaned


@dataclass(frozen=True)
class RiskFacts:
    policy_status: str = "unknown"
    training_on_customer_data: str = "unknown"
    admin_controls_available: str = "unknown"
    data_sensitivity_tier: str = "unknown"
    interaction_class: str = "unknown"
    in_inventory: bool = True  # False when the Tool has no Dataset B row


@dataclass(frozen=True)
class Assessment:
    tier: str
    reason_codes: list[str]
    unknown_facts: list[str]
    investigation_flag: bool
    flag_reasons: list[str]
    governance_level: str
    exposure_level: str
    sensitivity_assumed: bool
    base_tier: str
    escalation: str | None = None
    escalation_reason: str | None = None
    tier_raised: bool = False
    escalation_event_ids: list[str] = field(default_factory=list)


def governance_level(policy: str, training: str, admin: str) -> str:
    """Section 2.2, top-down; ``training`` must already have conditional mapped to unknown."""
    if (policy, training, admin) == ("unknown", "unknown", "unknown"):
        return "unassessed"
    if policy == "unapproved" and training == "yes":
        return "ungoverned"
    if policy == "unapproved" or training == "yes" or admin == "no":
        return "adverse"
    if (policy, training, admin) == ("approved", "no", "yes"):
        return "governed"
    return "partial"


def assess(facts: RiskFacts, event_ids: Sequence[str] = ()) -> Assessment:
    """Assess one Usage Context. ``event_ids`` are the context's events, kept on escalation."""
    for name, allowed in _ALLOWED.items():
        value = getattr(facts, name)
        if value not in allowed:
            raise ValueError(f"{name} must be one of {sorted(allowed)}, not {value!r}")

    policy = facts.policy_status
    training = "unknown" if facts.training_on_customer_data == "conditional" else (
        facts.training_on_customer_data
    )
    admin = facts.admin_controls_available
    sensitivity = facts.data_sensitivity_tier
    cls = facts.interaction_class

    level = governance_level(policy, training, admin)
    exposure = EXPOSURE[sensitivity]
    assumed = sensitivity == "unknown"
    tool_values = {
        "policy_status": policy,
        "training_on_customer_data": training,
        "admin_controls_available": admin,
    }
    unknown = [name for name, value in tool_values.items() if value == "unknown"]
    if assumed:
        unknown.append("data_sensitivity_tier")

    # Tier: matrix, then at most one step up. Assumed sensitivity never meets X1's E2 bar.
    escalation = None
    if level == "unassessed":
        base_tier = tier = "unresolved"
    else:
        base_tier = MATRIX[level][exposure]
        x1 = (
            cls == "content_submission"
            and exposure >= 2
            and not assumed
            and level != "governed"
        )
        x2 = cls == "access_grant" and level in {"adverse", "ungoverned"}
        escalation = "X1" if x1 else "X2" if x2 else None
        tier = STEP_UP[base_tier] if escalation else base_tier

    # Reason codes in priority order: governance, exposure, escalation, assumption, inventory.
    reasons: list[str] = []
    if level == "unassessed":
        reasons.append("all_tool_facts_unknown")
    elif level == "governed":
        reasons += ["approved_tool", "no_customer_data_training", "admin_controls_available"]
    elif level == "partial":
        reasons.append("controls_unconfirmed")
        if policy == "approved":
            reasons.append("approved_tool")
        if training == "no":
            reasons.append("no_customer_data_training")
        if admin == "yes":
            reasons.append("admin_controls_available")
    else:  # adverse or ungoverned: every adverse fact, in phrase order
        if policy == "unapproved":
            reasons.append("unapproved_tool")
        if training == "yes":
            reasons.append("customer_data_training_permitted")
        if admin == "no":
            reasons.append("admin_controls_absent")
    reasons.append(_EXPOSURE_CODES[exposure])
    escalation_reason = ESCALATION_CODES[escalation] if escalation else None
    if escalation_reason:
        reasons.append(escalation_reason)
    if assumed:
        reasons.append("sensitivity_assumed_internal")
    if not facts.in_inventory:
        reasons.append("not_in_ai_inventory")

    # Section 4: flags are independent of the tier and fire for unresolved contexts too.
    flags: list[str] = []
    if tier == "High":
        flags.append("high_tier")
    if policy == "unapproved":
        flags.append("unapproved_tool")
    if training == "yes":
        flags.append("customer_data_training_permitted")
    if admin == "no":
        flags.append("admin_controls_absent")
    if tier == "unresolved":
        flags.append("insufficient_evidence_for_tier")
    if exposure >= 2 and level in {"adverse", "ungoverned"}:
        flags.append("sensitive_data_in_non_governed_tool")
    if exposure >= 2 and level == "unassessed":
        flags.append("sensitive_use_of_unassessed_tool")
    if not facts.in_inventory:
        flags.append("not_in_ai_inventory")
    if cls == "access_grant":
        flags.append("access_grant_observed")
    if cls == "content_submission" and (assumed or training == "unknown"):
        flags.append("submission_with_missing_facts")
    if cls == "access_grant" and (policy == "unknown" or admin == "unknown"):
        flags.append("access_grant_with_missing_facts")

    return Assessment(
        tier=tier,
        reason_codes=reasons,
        unknown_facts=unknown,
        investigation_flag=bool(flags),
        flag_reasons=flags,
        governance_level=level,
        exposure_level=EXPOSURE_LABELS[exposure],
        sensitivity_assumed=assumed,
        base_tier=base_tier,
        escalation=escalation,
        escalation_reason=escalation_reason,
        tier_raised=escalation is not None and tier != base_tier,
        escalation_event_ids=list(event_ids) if escalation else [],
    )
