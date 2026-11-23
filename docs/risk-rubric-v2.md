# Contextual risk rubric v2 (`owasp-usage-risk-v2.1`)

> **Status: Confirmed by the team, 2026-11-23.** This is the rubric the risk analysis
> implements. It replaces `synthetic-demo-risk-v1`. It consolidates
> [the proposal](risk-rubric-owasp-proposal.md) and revision 2 of
> [the implementation guide](risk-v2-implementation-guide.md), with these decisions:
>
> 1. **Basis:** the OWASP LLM AI Cybersecurity & Governance Checklist (structure) together
>    with the OWASP Top 10 for LLM Applications 2026 (risk vocabulary). NIST AI RMF remains
>    the governance structure.
> 2. **Matrix cells:** accepted as proposed.
> 3. **Unknown sensitivity:** calculated as `internal`, always disclosed.
> 4. **Interaction vocabulary:** the revision-2 interaction classes, plus a v2 fixture.
> 5. **Purpose classes:** used for the explanation only; they never change the tier.
>
> **Revision v2.1 (2026-11-23), after the first end-to-end run.** The matrix, escalations and
> existing flags are unchanged. Changes: (a) usage of a Tool whose identity or AI status is
> unresolved is saved as a `not_assessed` row instead of being dropped (sections 1, 4, 6);
> (b) explanation wording: a comma closes the category phrase, purposes use natural phrases,
> shared "terms" are joined ("training and admin-control terms"), and sentence 3 shows both
> the assumption and any unnamed unknown vendor facts (section 6).
>
> Like v1, this is a framework-informed **synthetic demonstration policy**. It is not Cyera
> policy, not an OWASP-prescribed tiering, and not a compliance determination. Changing any
> table below creates a new rule version.

---

## 1. What is assessed

**Unit of assessment.** One **Usage Context** in one Analysis Run: a resolved AI Tool
together with the four grouping fields below.

| Grouping field | Source |
|---|---|
| `department` | activity event |
| `usage_purpose` | activity event (supplied); blank becomes `unknown` |
| `data_sensitivity_tier` | activity event (supplied); blank becomes `unknown` |
| `interaction_class` | derived from `event_type` (section 2.4) |

**Eligibility.** A context is assessed only when two things hold:

- Identity resolution gave `known_tool` or `observed_tool`; and
- AI determination gave `ai`.

Non-AI candidates get no context. Usage of a candidate whose identity or AI status is
unresolved gets a context with the outcome `not_assessed`: no tier is assigned and no rubric
fact is judged, but the usage stays visible and is flagged `tool_not_assessed` for review.
A candidate with no resolved identity uses the Tool ID `unresolved:{domain}`.

**Output.** Each assessment has five parts:

- a tier: `Low`, `Medium`, `High` or `unresolved`, or the outcome `not_assessed` (section 1);
- an explanation of two or three sentences;
- reason codes;
- investigation flags;
- unknowns, assumptions and evidence references.

---

## 2. Inputs

`unknown` is never treated as the favourable value. Unrecognized values become `unknown`, and
the original value is kept in the explanation parts.

### 2.1 Tool facts (Dataset B, tool-wide)

| Fact | Allowed values | Notes |
|---|---|---|
| `policy_status` (`approved_status`) | `approved`, `unapproved`, `unknown` | Synthetic organization-wide Policy Status |
| `training_on_customer_data` | `yes`, `no`, `conditional`, `unknown` | `conditional` counts as `unknown` |
| `admin_controls_available` | `yes`, `no`, `unknown` | |
| `in_inventory` | `true` / `false` | `false` when the Tool has no Dataset B row; all three facts are then `unknown` |

**Fact scope.** These facts are tool-wide, under the synthetic scenario's assumed
configuration. The activity data cannot tell a managed workspace from a personal account, so
the rubric never claims the approved configuration was the one in use. Every result records
`fact_scope = "tool_wide_scenario_assumption"`. SSO and retention may be shown as evidence,
but they are not rubric inputs.

### 2.2 Governance level (from the tool facts)

Evaluate the rows top-down; the first match wins.

| Level | Code | Condition | Basis |
|---|---|---|---|
| Unassessed | `unassessed` | all three facts are `unknown` | Checklist: AI asset inventory |
| C3 Ungoverned | `ungoverned` | `unapproved` **and** training = `yes` | Checklist: Shadow AI. LLM02:2026 |
| C2 Adverse | `adverse` | `unapproved` **or** training = `yes` **or** admin = `no` | Checklist: Shadow AI, Governance, Legal |
| C0 Governed | `governed` | `approved` **and** training = `no` **and** admin = `yes` | Checklist: Governance (business-managed tool) |
| C1 Partial | `partial` | anything else (no adverse fact, at least one unknown) | Checklist: Regulatory (confirm vendor data handling) |

### 2.3 Exposure level (from supplied data sensitivity)

| Value | Level | Basis |
|---|---|---|
| `public` | E0 | — |
| `internal` | E1 | Checklist: catalogue data sources and their sensitivity |
| `unknown` | E1, **assumed** | Calculated as internal; sets `sensitivity_assumed = true` |
| `confidential` | E2 | LLM02:2026. Checklist: no confidential data in non-business-managed tools |
| `restricted` (PII, PHI, credentials, payment data) | E3 | LLM02:2026. Checklist: Regulatory / Legal |

Sensitivity is always **supplied**. It is never inferred from department, role, bytes,
category or content.

### 2.4 Interaction class (from `event_type`; part of the context key)

| `event_type` | Class | What it establishes |
|---|---|---|
| `browser_visit`, `app_open`, `login` | `presence` | The tool was reached. **Not** that anything was submitted |
| `prompt_submit`, `chat_message`, `content_paste`, `file_upload` | `content_submission` | Content was sent to the tool |
| `oauth_grant`, `connector_added` | `access_grant` | The tool was granted access to company systems |
| blank, or anything else (including `extension_install`, `api_key_use`, `agent_action`) | `unknown` | Activity of an uninterpreted type |

Each class forms its own context, so different kinds of use are never merged. A new event
type joins a class only together with a confirmed rule that says what it proves.

### 2.5 Purpose class (explanation only; never changes the tier)

| Class | `usage_purpose` values | Concern tags (shown with the result) |
|---|---|---|
| `code_generation` | `code_assistance`, `software_development` | LLM02 (source code), LLM04 (hallucinated packages), LLM10 (AI-written code) |
| `external_communication` | `email_campaigns`, `sales_outreach` | LLM07 (output reaches customers), LLM02 (prospect personal data) |
| `content_analysis` | `draft_summary`, `text_analysis` | LLM02 (documents submitted), LLM07 (decisions built on output) |
| `automation_testing` | `visual_testing` | LLM03 (the tool acts on systems) |
| `ideation` | `product_ideation` | LLM02 (unreleased plans) |
| `unknown` | anything else | — |

Category (the 14 AIToolBuzz labels) also appears only in the explanation.

---

## 3. Deciding the tier

### 3.1 Acceptable-use matrix: the base tier

| Governance \ Exposure | E0 public | E1 internal (or assumed) | E2 confidential | E3 restricted |
|---|---|---|---|---|
| **C0 Governed** | Low | Low | Low | Medium |
| **C1 Partial** | Low | Medium | Medium | High |
| **C2 Adverse** | Medium | Medium | High | High |
| **C3 Ungoverned** | Medium | High | High | High |
| **Unassessed** | unresolved | unresolved | unresolved | unresolved |

The matrix is monotonic: more sensitive data or weaker governance never lowers the tier.

### 3.2 Escalation: at most one step up, never down

| Rule | Condition | Reason code | Basis |
|---|---|---|---|
| **X1** | class = `content_submission` **and** exposure ≥ E2 (not assumed) **and** governance ≠ `governed` | `sensitive_content_submitted_to_non_governed_tool` | LLM02:2026 |
| **X2** | class = `access_grant` **and** governance ∈ {`adverse`, `ungoverned`} | `access_granted_to_non_governed_tool` | LLM03:2026, LLM04:2026; Agentic Top 10 |

The final tier follows from the base tier:

- If X1 or X2 applies and the base tier is `Low` or `Medium`, raise it one step and set
  `tier_raised = true`.
- If it applies and the base tier is already `High`, keep `High`, set `tier_raised = false`,
  and still record the escalation so it shows in the explanation.
- `unresolved` is never escalated.
- `presence` and `unknown` classes never escalate and never lower a tier.
- Record `base_tier`, `escalation` (`X1`, `X2` or none), `tier_raised` and
  `escalation_event_ids` (the context's event IDs).

---

## 4. Investigation flags (independent of tier)

| Flag | Condition | Basis |
|---|---|---|
| `high_tier` | final tier = High | v1 |
| `unapproved_tool` | policy = `unapproved` | v1; Checklist: Shadow AI |
| `customer_data_training_permitted` | training = `yes` | v1; LLM02 |
| `admin_controls_absent` | admin = `no` | v1 |
| `insufficient_evidence_for_tier` | tier = unresolved | v1 |
| `tool_not_assessed` | outcome = not_assessed | Checklist: AI asset inventory; Shadow AI |
| `sensitive_data_in_non_governed_tool` | exposure ≥ E2 **and** governance ∈ {adverse, ungoverned} | Checklist: Governance |
| `sensitive_use_of_unassessed_tool` | exposure ≥ E2 **and** governance = unassessed | Checklist: AI asset inventory |
| `not_in_ai_inventory` | `in_inventory = false` | Checklist: AI asset inventory; Shadow AI |
| `access_grant_observed` | class = `access_grant` | LLM03 / LLM04 |
| `submission_with_missing_facts` | class = `content_submission` **and** (sensitivity unknown **or** training unknown) | Checklist: Regulatory |
| `access_grant_with_missing_facts` | class = `access_grant` **and** (policy unknown **or** admin unknown) | Checklist: Regulatory |

A single missing fact, or a department name, never raises a flag on its own. The two
`*_with_missing_facts` flags are the only exception: they apply when an action was observed
and a fact needed to judge that action is missing. Flags fire for `unresolved` contexts too.

---

## 5. Reason codes, phrases and references

The explanation uses each code's phrase. The references are stored with the result. A
reference explains why a factor matters; it never proves a vendor fact.

| Code | Phrase used in the explanation | References |
|---|---|---|
| `unapproved_tool` | "the tool is not approved" | Checklist: Shadow AI; Governance (acceptable use matrix). NIST AI RMF GOVERN 1.6 |
| `customer_data_training_permitted` | "the vendor may train on customer data" | LLM02:2026 (training opt-out). Checklist: Legal (EULA, prompts, data privacy) |
| `admin_controls_absent` | "the tool has no admin controls" | Checklist: Governance (technical enforcement). LLM02:2026 (access controls) |
| `approved_tool` + `no_customer_data_training` + `admin_controls_available` | "the tool is approved, the vendor does not train on customer data and admin controls are available" | Checklist: Governance |
| `controls_unconfirmed` (partial) | "the vendor's {unknown facts} {is/are} unknown"; labels ending in "terms" share it ("training and admin-control terms") | Checklist: Regulatory. NIST AI RMF GOVERN 6.1 |
| `restricted_data_context` | "restricted data is involved" | LLM02:2026. Checklist: Regulatory / Legal |
| `confidential_data_context` | "confidential data is involved"; with governance adverse or ungoverned: "confidential data should not go into a tool that isn't business-managed" | LLM02:2026. Checklist: Governance |
| `internal_data_context` | "internal data is involved"; when sensitivity is assumed: "no data sensitivity was supplied" | Checklist: AI asset inventory |
| `public_data_context` | "only public data is involved" | — |
| `sensitive_content_submitted_to_non_governed_tool` | "{sensitivity} content was {uploaded / pasted / submitted} to a tool that is not fully governed" | LLM02:2026 |
| `access_granted_to_non_governed_tool` | "{OAuth access was granted / a connector was added} to a tool with an adverse governance fact" | LLM03:2026. LLM04:2026. Agentic Top 10 |
| `sensitivity_assumed_internal` | (sentence 3) "Sensitivity unknown; tier calculated using the internal-data assumption." | — |
| `all_tool_facts_unknown` | (unresolved template) | Checklist: AI asset inventory |
| `identity_unresolved` | (not-assessed template) | Checklist: AI asset inventory |
| `ai_status_unresolved` | (not-assessed template) | Checklist: AI asset inventory. NIST AI RMF GOVERN 1.6 |
| `not_in_ai_inventory` | used only in parts and flags | Checklist: AI asset inventory. NIST AI RMF GOVERN 1.6 |

Before the demo, check each reference against the official LLM Top 10 2026 PDF and the
Checklist v1.1, and add page numbers.

**Choosing the governance phrase.** Use one governance phrase per explanation:

| Governance level | Phrase |
|---|---|
| ungoverned | "the tool is not approved and the vendor may train on customer data" |
| adverse | the first adverse fact, in the order unapproved → training yes → admin no |
| partial | `controls_unconfirmed` |
| governed | the combined governed phrase |

---

## 6. Explanation templates

Fill the sentences in order. A slot is never dropped to make room for another.

**Sentence 1, how the tool was used:**
`{department} used {tool}{category} for {purpose} with {sensitivity} ({n} events,
{first}–{last}){activity}.`

| Slot | Rule |
|---|---|
| `{category}` | `", a {Category} tool,"` (catalog); `", likely a {Category} tool,"` (neighbor vote); empty when unresolved |
| `{purpose}` | a natural phrase for known purposes (`draft_summary` → "drafting summaries"); otherwise `usage_purpose` with underscores turned into spaces; `unknown` becomes "an unstated purpose" |
| `{sensitivity}` | `"{value} data"`, or "data of unknown sensitivity" |
| `{activity}` | presence: "; only visits were observed". `prompt_submit` / `chat_message`: "; prompts were submitted". `content_paste`: "; pasted content was observed". `file_upload`: "; file uploads were observed". `oauth_grant`: "; the tool was granted OAuth access". `connector_added`: "; a connector to company systems was added". unknown: "; the activity type was not recorded". Join phrases when a context has several event types |

**Sentence 2, why it got this level:**

| Case | Template |
|---|---|
| No escalation | `Rated {tier} because {governance phrase} and {exposure phrase}.` |
| Escalation raised the tier | `Rated {tier}: {base_tier} because {governance phrase} and {exposure phrase}, raised one step because {escalation phrase}.` |
| Escalation, already High | `Rated High because {governance phrase} and {exposure phrase}; {escalation phrase} was also observed.` |

**Sentence 3, only when needed.** Join these clauses in order; each applies on its own:

1. If sensitivity is assumed: "Sensitivity unknown; tier calculated using the internal-data
   assumption."
2. Unknown vendor facts not already named in sentence 2, for example "Training and
   admin-control terms are unknown."
3. If `submission_with_missing_facts`: "Review: content was submitted without {a known data
   sensitivity / known vendor training terms}."
4. If `access_grant_with_missing_facts`: "Review: access was granted without {a known
   approval status / known admin controls}."

**Unresolved:**

- Base sentence: `{tool} has no usable approval or vendor facts, so no risk level was
  assigned.`
- If `sensitive_use_of_unassessed_tool` is set, add: `It was used with {sensitivity} data
  and needs review.`
- Add any "Review:" clauses from sentence 3.

**Not assessed:** sentence 1, then
`Not assessed because {why}[: {evidence gap}]. No risk level was assigned; review this usage.`

- `{why}`: "its AI status is unresolved", "the tool could not be identified", or both.
- `{evidence gap}` (AI status unresolved only), from the AI Determination stage: no evidence →
  "its homepage could not be read and no description was supplied"; too little text → "its
  homepage had too little text to judge and no description was supplied"; judge undecided →
  "the AI judge could not decide from the available text".

**Wording rules:**

- Say content was submitted only for `content_submission`, and access was granted only for
  `access_grant`. Always name the actual event type.
- Never name or count individual employees in the text.
- Never call a tier a compliance finding, an incident or a policy violation.

---

## 7. Stored result

The result keeps all of v1's fields: context fields, event IDs, timestamps, `metadata_id`,
`facts`, `tier`, `reason_codes`, `unknown_facts`, `investigation_flag`, `flag_reasons` and
`rule_version`. It adds:

- `interaction_class` and `event_types`;
- `distinct_employee_count`;
- `category` and `category_method`;
- `governance_level`, `exposure_level` and `sensitivity_assumed`;
- `base_tier`, `escalation`, `tier_raised` and `escalation_event_ids`;
- `purpose_class` and `concern_tags`;
- `fact_scope`;
- `framework_refs`;
- `explanation` (text) and `explanation_parts` (the structured slots above).

`rule_version = "owasp-usage-risk-v2.1"`. Stored v1 rows keep their own version and tier labels
(`Lower` is migrated to `Low`).

---

## 8. Worked examples

### Current fixture (`v1` data): tiers unchanged from v1

| Usage Context | Governance | Exposure | Class | Tier | Flags |
|---|---|---|---|---|---|
| ChatGPT · Engineering · code_assistance · internal | governed | E1 | presence | Low | — |
| ChatGPT · Finance · draft_summary · confidential | governed | E2 | presence | Low | — |
| Cursor · Engineering · software_development · internal | adverse | E1 | presence | Medium | unapproved_tool |
| MeetOscar · Marketing · email_campaigns · internal | ungoverned | E1 | presence | High | high_tier, unapproved_tool, customer_data_training_permitted, admin_controls_absent |
| Playbooks · Sales · sales_outreach · internal | ungoverned | E1 | presence | High | same as MeetOscar |
| Magic Inspector · Engineering · visual_testing · internal | governed | E1 | presence | Low | — |
| Amazon Comprehend · Research · text_analysis · confidential | partial | E2 | presence | Medium | — |
| Open Canvas AI · Product · product_ideation · internal | unassessed | E1 | presence | unresolved | insufficient_evidence_for_tier |

### Fixture v2 scenarios

| Usage Context | Base | Final | Notable flags |
|---|---|---|---|
| Cursor · Engineering · confidential · presence | High | **High** | sensitive_data_in_non_governed_tool |
| Comprehend · Research · confidential · `file_upload` | Medium | **High** (X1) | submission_with_missing_facts |
| ChatGPT · Support · restricted · presence | Medium | **Medium** | — |
| ChatGPT · Engineering · unknown sensitivity · `content_paste` | Low | **Low** | submission_with_missing_facts |
| Cursor · Engineering · internal · `oauth_grant` | Medium | **High** (X2) | access_grant_observed, access_grant_with_missing_facts |
| Cursor · Engineering · internal · `extension_install` (unknown class) | Medium | **Medium** | unapproved_tool |
| Open Canvas AI · Product · confidential · `file_upload` | — | **unresolved** | sensitive_use_of_unassessed_tool, submission_with_missing_facts |
| MeetOscar · Marketing · public · presence | Medium | **Medium** | unapproved_tool, customer_data_training_permitted, admin_controls_absent |

### Example explanations

> **Medium.** Research used Amazon Comprehend for text analysis with confidential data (5
> events, 15–30 Sep); only visits were observed. Rated Medium because the vendor's training
> terms are unknown and confidential data is involved.

> **High.** Research used Amazon Comprehend for text analysis with confidential data (2
> events, 22 Sep); file uploads were observed. Rated High: Medium because the vendor's
> training terms are unknown and confidential data is involved, raised one step because
> confidential content was uploaded to a tool that is not fully governed. Review: content
> was submitted without known vendor training terms.

> **High.** Engineering used Cursor for software development with confidential data (12
> events, 15–30 Sep); only visits were observed. Rated High because the tool is not approved
> and confidential data should not go into a tool that isn't business-managed. Training and
> admin-control terms are unknown.

> **Low.** Engineering used ChatGPT for code assistance with data of unknown sensitivity (4
> events, 20–24 Sep); pasted content was observed. Rated Low because the tool is approved,
> the vendor does not train on customer data and admin controls are available, and no data
> sensitivity was supplied. Sensitivity unknown; tier calculated using the internal-data assumption.
> Review: content was submitted without a known data sensitivity.

The category is omitted from these examples because the fixture's expected categories are
evaluation-only. Event counts and dates are illustrative.

---

## 9. Guardrails carried over from the plan

- The tier is decided deterministically by this rubric. No LLM chooses the tier or writes
  the explanation. The assistant may cite the stored explanation, but it cannot change it.
- `unknown` never counts as favourable, and a tool with no usable facts stays `unresolved`.
- Sensitivity and purpose are supplied, never inferred. Presence never proves submission.
- Contexts are assessed, not people: no employee is named or ranked.
- Tiers are project-policy assessments, not incidents, compliance findings or Cyera policy.

## Sources

- OWASP LLM AI Cybersecurity & Governance Checklist v1.1: https://genai.owasp.org/initiatives/llm-applications-cybersecurity-and-governance-checklist/
- OWASP Top 10 for LLM Applications 2026, summary of changes: https://cloudsecurityalliance.org/blog/2026/10/21/the-owasp-top-10-for-llm-applications-2026-what-changed-and-why-it-matters
- Which 2026 entries apply to organizations that use AI tools: https://jazz.security/dlp-explained/dlp-basics/what-is-the-owasp-top-10-for-llm-applications/
- LLM02 Sensitive Information Disclosure: https://genai.owasp.org/llmrisk/llm022025-sensitive-information-disclosure/
