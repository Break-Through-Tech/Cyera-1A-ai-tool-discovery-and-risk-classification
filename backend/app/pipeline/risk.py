"""Deterministic contextual-risk rubric for a Usage Context.

This is the project's versioned synthetic demonstration policy (PROJECT_PLAN.md,
"Initial contextual-risk contract"). It is not Cyera policy, not a compliance
determination, and no LLM chooses the tier.

- High: unapproved AI Tool and submissions may be used for training.
- Lower: approved, no training on customer data, and admin controls available.
- Medium: any other case with at least one usable rubric fact.
- unresolved: every rubric fact is unknown (never defaults to Medium).

`unknown` is never treated as `false`, and conditional training terms count as unknown.
"""

from dataclasses import dataclass

RISK_RULE_VERSION = "synthetic-demo-risk-v1"

_FACT_CODES = {
    ("policy_status", "approved"): "approved_tool",
    ("policy_status", "unapproved"): "unapproved_tool",
    ("training_on_customer_data", "yes"): "customer_data_training_permitted",
    ("training_on_customer_data", "no"): "no_customer_data_training",
    ("admin_controls_available", "yes"): "admin_controls_available",
    ("admin_controls_available", "no"): "admin_controls_absent",
}
_ALLOWED = {
    "policy_status": {"approved", "unapproved", "unknown"},
    "training_on_customer_data": {"yes", "no", "unknown", "conditional"},
    "admin_controls_available": {"yes", "no", "unknown"},
}


@dataclass(frozen=True)
class RiskFacts:
    policy_status: str = "unknown"
    training_on_customer_data: str = "unknown"
    admin_controls_available: str = "unknown"


@dataclass(frozen=True)
class Assessment:
    tier: str
    reason_codes: list[str]
    unknown_facts: list[str]
    investigation_flag: bool
    flag_reasons: list[str]


def assess(facts: RiskFacts) -> Assessment:
    values = {
        "policy_status": facts.policy_status,
        "training_on_customer_data": facts.training_on_customer_data,
        "admin_controls_available": facts.admin_controls_available,
    }
    for name, value in values.items():
        if value not in _ALLOWED[name]:
            raise ValueError(f"{name} must be one of {sorted(_ALLOWED[name])}, not {value!r}")
    if values["training_on_customer_data"] == "conditional":
        values["training_on_customer_data"] = "unknown"

    policy = values["policy_status"]
    training = values["training_on_customer_data"]
    admin = values["admin_controls_available"]
    unknown = [name for name, value in values.items() if value == "unknown"]
    known_codes = [_FACT_CODES[item] for item in values.items() if item in _FACT_CODES]

    if policy == "unapproved" and training == "yes":
        tier, reasons = "High", ["unapproved_tool", "customer_data_training_permitted"]
    elif policy == "approved" and training == "no" and admin == "yes":
        tier, reasons = "Lower", known_codes
    elif len(unknown) == len(values):
        tier, reasons = "unresolved", ["all_rubric_facts_unknown"]
    else:
        tier, reasons = "Medium", ["other_classifiable_case", *known_codes]

    flag_reasons = []
    if tier == "High":
        flag_reasons.append("high_tier")
    if policy == "unapproved":
        flag_reasons.append("unapproved_tool")
    if training == "yes":
        flag_reasons.append("customer_data_training_permitted")
    if admin == "no":
        flag_reasons.append("admin_controls_absent")
    if tier == "unresolved":
        flag_reasons.append("insufficient_evidence_for_tier")

    return Assessment(tier, reasons, unknown, bool(flag_reasons), flag_reasons)
