---
status: accepted
---

# Contextual risk uses an OWASP acceptable-use matrix

Contextual Risk Assessment now follows [`owasp-usage-risk-v2`](../risk-rubric-v2.md), confirmed by the team on 2026-11-23. It replaces `synthetic-demo-risk-v1`, which picked one tier per Tool from three Dataset B facts and copied it to every Usage Context, so the data sensitivity and the kind of activity never changed the tier.

v2 assesses each Usage Context on its own. Its structure comes from the OWASP LLM AI Cybersecurity & Governance Checklist v1.1 (AI asset inventory, Shadow AI, the acceptable use matrix for generative AI tools), and its risk vocabulary from the OWASP Top 10 for LLM Applications 2026. NIST AI RMF remains the governance structure.

- A **Governance Level** (unassessed, ungoverned, adverse, partial, governed) comes from the three tool-wide Dataset B facts: approval, training on customer data and admin controls.
- An **Exposure Level** (E0–E3) comes from the supplied Data Sensitivity Tier.
- A fixed 4×4 acceptable-use matrix turns the two levels into Low, Medium or High. An unassessed Tool stays `unresolved`.
- An **Interaction Class** (presence, content submission, access grant, unknown), derived from `event_type`, is part of the Usage Context key. Two narrow escalations raise the tier one step: sensitive content submitted to a Tool that is not fully governed (X1, LLM02), and OAuth access or a connector granted to a Tool with an adverse fact (X2, LLM03/LLM04).
- Every result carries a template-built **Risk Explanation**, reason codes with framework references, investigation flags, and the assumptions and unknowns behind it.

## Confirmed decisions

1. **Basis:** the OWASP Governance Checklist (structure) with the OWASP LLM Top 10 2026 (vocabulary).
2. **Matrix cells:** accepted as proposed in [the proposal](../risk-rubric-owasp-proposal.md).
3. **Unknown sensitivity:** calculated as `internal`, always disclosed (`sensitivity_assumed`), and never able to trigger an escalation.
4. **Interaction vocabulary:** the revision-2 interaction classes of [the implementation guide](../risk-v2-implementation-guide.md), plus a v2 fixture. `extension_install`, `api_key_use` and `agent_action` stay `unknown` until a confirmed rule says what each proves.
5. **Purpose classes:** used only in the explanation; they never change the tier.

## Scope of tool facts

Dataset B supplies *tool-wide* facts under the synthetic scenario's assumed configuration. The activity data cannot tell a managed company workspace from a personal account, so v2 does not claim the approved configuration was the one in use. Every result records `fact_scope = "tool_wide_scenario_assumption"`. Workspace or account scope can become a grouping field later, once activity data identifies it reliably. Department and purpose group and describe contexts; no rule uses them.

## Consequences

- The same Tool can have Low, Medium and High contexts side by side. A Comprehend app open and a Comprehend file upload with the same department, purpose and sensitivity are two contexts, and only the upload is escalated.
- On the v1 fixture every event is presence, so the contexts and tiers are unchanged apart from the rename `Lower` → `Low`. Stored v1 rows keep `rule_version = synthetic-demo-risk-v1`; migration `0007` renames their tier.
- The tier is still decided deterministically and no LLM writes the explanation. The assistant may cite the stored explanation but cannot change it (ADR 0004).
- The tier remains a project-policy assessment, not Cyera policy, an OWASP-prescribed tiering, an incident or a compliance finding. Framework references explain why a factor matters; they never prove a vendor fact.
- Changing any matrix cell, escalation or flag rule creates a new rule version.
