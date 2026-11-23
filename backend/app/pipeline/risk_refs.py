"""Framework references for each contextual-risk reason code and investigation flag.

A reference explains why a factor matters; it never proves a vendor fact
(docs/risk-rubric-v2.md, section 5). Page numbers are still to be checked against the
official OWASP LLM Top 10 2026 PDF and the Governance Checklist v1.1 before the demo.
"""

from collections.abc import Iterable

RISK_REFS_VERSION = "owasp-refs-v1"

CHECKLIST = "OWASP LLM AI Cybersecurity & Governance Checklist v1.1"
TOP10 = "OWASP Top 10 for LLM Applications 2026"
AGENTIC = "OWASP Top 10 for Agentic Applications"
NIST = "NIST AI RMF 1.0"

Ref = tuple[str, str, str]  # framework, item, short label

_SHADOW_AI = (CHECKLIST, "Shadow AI", "Unapproved AI tools in use")
_GOVERNANCE = (CHECKLIST, "Governance", "Acceptable use matrix for generative AI tools")
_GOVERNANCE_NO_CONFIDENTIAL = (
    CHECKLIST,
    "Governance",
    "No confidential data in non-business-managed tools",
)
_REGULATORY = (CHECKLIST, "Regulatory", "Confirm how the vendor stores, deletes and uses data")
_INVENTORY = (CHECKLIST, "AI asset inventory", "Catalogue AI tools and data sensitivity")
_LLM02 = (TOP10, "LLM02:2026", "Sensitive Information Disclosure")
_LLM03 = (TOP10, "LLM03:2026", "Excessive Agency")
_LLM04 = (TOP10, "LLM04:2026", "Supply Chain")
_AGENTIC = (AGENTIC, "Agentic Top 10", "Agents granted access to company systems")
_GOVERN_1_6 = (NIST, "GOVERN 1.6", "Inventory of AI systems")
_GOVERN_6_1 = (NIST, "GOVERN 6.1", "Third-party AI risk policies")

REFERENCES: dict[str, tuple[Ref, ...]] = {
    # Reason codes
    "unapproved_tool": (_SHADOW_AI, _GOVERNANCE, _GOVERN_1_6),
    "customer_data_training_permitted": (
        (TOP10, "LLM02:2026", "Training opt-out"),
        (CHECKLIST, "Legal", "EULA, prompts and data privacy"),
    ),
    "admin_controls_absent": (
        (CHECKLIST, "Governance", "Technical enforcement"),
        (TOP10, "LLM02:2026", "Access controls"),
    ),
    "approved_tool": (_GOVERNANCE,),
    "no_customer_data_training": (_GOVERNANCE,),
    "admin_controls_available": (_GOVERNANCE,),
    "controls_unconfirmed": (_REGULATORY, _GOVERN_6_1),
    "restricted_data_context": (_LLM02, (CHECKLIST, "Regulatory / Legal", "Regulated data")),
    "confidential_data_context": (_LLM02, _GOVERNANCE_NO_CONFIDENTIAL),
    "internal_data_context": (_INVENTORY,),
    "public_data_context": (),
    "sensitive_content_submitted_to_non_governed_tool": (_LLM02,),
    "access_granted_to_non_governed_tool": (_LLM03, _LLM04, _AGENTIC),
    "sensitivity_assumed_internal": (),
    "all_tool_facts_unknown": (_INVENTORY,),
    "not_in_ai_inventory": (_INVENTORY, _GOVERN_1_6),
    # Investigation flags not already covered above
    "high_tier": (),
    "insufficient_evidence_for_tier": (_INVENTORY,),
    "sensitive_data_in_non_governed_tool": (_GOVERNANCE_NO_CONFIDENTIAL,),
    "sensitive_use_of_unassessed_tool": (_INVENTORY,),
    "access_grant_observed": (_LLM03, _LLM04, _AGENTIC),
    "submission_with_missing_facts": (_REGULATORY, _GOVERN_6_1),
    "access_grant_with_missing_facts": (_REGULATORY, _GOVERN_6_1),
}


def references(codes: Iterable[str]) -> list[dict[str, str]]:
    """The references of reason codes and flags, each listed once with the codes citing it."""
    cited: dict[Ref, list[str]] = {}
    for code in codes:
        for ref in REFERENCES.get(code, ()):
            cited.setdefault(ref, [])
            if code not in cited[ref]:
                cited[ref].append(code)
    return [
        {"framework": framework, "item": item, "label": label, "codes": codes_}
        for (framework, item, label), codes_ in cited.items()
    ]
