# Implementation guide: contextual risk v2 (OWASP-informed)

> Companion to [`risk-rubric-owasp-proposal.md`](risk-rubric-owasp-proposal.md). This guide
> assumes the team has confirmed the five decisions in section 10 of that proposal. Like v1,
> it builds a **synthetic demonstration policy**, not Cyera policy or a compliance claim.
>
> **The confirmed rubric is [`risk-rubric-v2.md`](risk-rubric-v2.md).** Where this guide
> and the rubric differ (for example the `tier_raised` handling when the base tier is
> already High, and the exact explanation phrases), the rubric wins.
>
> **Revision 2 (after review feedback).** Where this guide and the proposal differ, this
> guide wins. It changes four things:
> 1. Interaction class is part of the Usage Context key, replacing the proposal's
>    "maximum depth" rule.
> 2. Signals match the evidence exactly. Only OAuth grants and connector additions count as
>    access grants, and escalations keep the event IDs that triggered them and always appear
>    in the explanation.
> 3. Assumptions and missing facts are shown in the result.
> 4. The scope of Dataset B's tool-wide facts is stated.

## Overview

**Today (v1).** The pipeline runs identity resolution → website enrichment → AI
determination → category classification → risk assessment → save.

- Risk assessment (`pipeline/risk.py`) reads three Dataset B facts about the *tool*:
  approval, training on customer data, and admin controls. It picks a tier once per tool.
- `pipeline/usage_contexts.py` then groups the tool's events into **Usage Contexts** (tool +
  department + usage purpose + data sensitivity) and attaches that *same* tier to each one.
- Category is attached only when results are saved, and `event_type` is never read. How a
  tool was used therefore never affects its risk.

**After v2.** A Usage Context becomes tool + department + purpose + sensitivity +
**interaction class** (presence, content submission, access grant, or unknown). Different
kinds of use are scored side by side and never merged. The risk step takes **each Usage
Context** and decides its level from two things:

1. **how well governed the tool is**, using the same three Dataset B facts; and
2. **how sensitive the data in that context is**, using the supplied `data_sensitivity_tier`.

A fixed 4×4 **acceptable-use matrix** turns those two levels into **Low, Medium or High**.
That matrix structure comes from the OWASP LLM AI Cybersecurity & Governance Checklist.
`unresolved` stays as the outcome when there is no usable evidence about the tool. The tier
goes up one step when the context's events show sensitive content being submitted to a tool
that isn't fully governed, or access to company systems being granted to a tool with an
adverse fact. The explanation always names that step-up and the event type behind it.

AI determination still decides *whether* a context is assessed: only resolved AI tools get
one. Category appears in the **explanation**, not in the tier decision, because it is only
correct about 63–71% of the time when the classifier answers. Every result gets a two-sentence
explanation built from fixed templates, with a third sentence when there is an assumption or
missing fact to show. It also gets reason codes that cite OWASP LLM Top
10 (2026) entries and Checklist items. No LLM picks the tier or writes the explanation.

**Example outputs: the same tool, two contexts side by side.**

> **Medium.** Research used Amazon Comprehend for text analysis
> with confidential data (5 events, 15–30 Sep); only visits were observed. Rated Medium
> because confidential data is involved and the vendor's training terms are unknown.

> **High.** Research used Amazon Comprehend for text analysis
> with confidential data (2 events, 22 Sep); file uploads were observed. Rated High:
> Medium because confidential data is involved and the vendor's training terms are
> unknown, raised one step because confidential content was uploaded to a tool that is not
> fully governed. Review: an upload was observed without known training terms.

## What changes, by file

| File | Change |
|---|---|
| `backend/app/pipeline/risk.py` | Rewritten as v2: levels, matrix, escalation, flags, reason codes |
| `backend/app/pipeline/risk_refs.py` (new) | Reason code → OWASP/NIST reference table |
| `backend/app/pipeline/risk_explain.py` (new) | Template-based explanation builder |
| `backend/app/pipeline/usage_contexts.py` | Add interaction class to the grouping key; assess **per context**; counts, category input |
| `backend/app/pipeline/default.py` | Risk phase reads `event_type` and `employee_id`; passes category classifications into risk |
| `backend/app/results.py` | Save the new fields |
| `backend/app/db/tables.py` + migration `0007` | New columns; tier constraint `Lower` → `Low` |
| `backend/app/api/runs.py` | Extend `AssessmentOut` / `RiskFactsOut`; tier filter literal |
| `backend/app/assistant/contracts.py` | Tier literal `Lower` → `Low` |
| `backend/tests/…` | New rubric, explanation and pipeline tests; update the v1 tests |
| `data/synthetic_enterprise_activity/` | v2 fixture scenarios and expected outcomes |
| `docs/adr/0005-…`, `PROJECT_PLAN.md`, `CONTEXT.md` | Record the confirmed decision |

## Step-by-step

### Step 1: Record the decision (docs first)

Per the planning protocol, write down what was confirmed before changing code.

1. Add `docs/adr/0005-contextual-risk-uses-owasp-acceptable-use-matrix.md`. Summarize the
   proposal's context, decision, consequences and the five confirmed decisions.
2. In `PROJECT_PLAN.md`, update **"Framework and decision boundary"** so the OWASP lens names
   the Governance Checklist + LLM Top 10 2026. Replace the rubric bullets in **"Initial
   contextual-risk contract"** with v2 and link the ADR. Keep every guardrail bullet
   (unknown ≠ false, no inferred sensitivity, no employee ranking, LLM never picks the tier).
3. In `CONTEXT.md`:
   - add the new terms: **Governance Level**, **Exposure Level**, **Interaction Class** and
     **Risk Explanation**;
   - change the **Usage Context** definition to include the interaction class in its
     grouping;
   - rename the `Lower` tier to `Low`.
4. Record the **scope of tool facts** (see the box below) in the plan, in the ADR, and in the
   fixture README.

> **Scope of tool facts (v2).** Dataset B supplies *tool-wide* facts (approval, training on
> customer data, admin controls) under the synthetic scenario's assumed configuration. The
> activity data cannot tell a managed company workspace from a personal account, so v2 does
> not claim the approved configuration was the one in use. Each result carries
> `fact_scope = "tool_wide_scenario_assumption"`, and the limitations section says so.
> Workspace or account scope can become a grouping field later, once activity data
> identifies it reliably. Department and purpose remain grouping and explanation fields
> only. No rule uses them until an explicit policy rule is confirmed.

**Done when:** the ADR is merged and the plan no longer describes v1 as current.

### Step 2: Rewrite the rubric in `risk.py`

Keep the existing style: frozen dataclasses, an `_ALLOWED` validation dict, and no I/O.

```python
RISK_RULE_VERSION = "owasp-usage-risk-v2"

@dataclass(frozen=True)
class RiskFacts:
    policy_status: str = "unknown"              # approved | unapproved | unknown
    training_on_customer_data: str = "unknown"  # yes | no | conditional | unknown
    admin_controls_available: str = "unknown"   # yes | no | unknown
    data_sensitivity_tier: str = "unknown"      # public | internal | confidential | restricted | unknown
    interaction_class: str = "unknown"          # presence | content_submission | access_grant | unknown
    in_inventory: bool = True                   # False when the Tool has no Dataset B row
```

The interaction class is a **context key** (step 5), not a maximum over events. Every event in
a context therefore has the same class, and the rubric never mixes evidence from different
kinds of use.

**2a. Governance level (C)**, evaluated top-down. `conditional` training counts as `unknown`.

```python
def governance_level(f) -> str:
    facts = (f.policy_status, training, f.admin_controls_available)
    if all(v == "unknown" for v in facts):
        return "unassessed"                                   # C?
    if f.policy_status == "unapproved" and training == "yes":
        return "ungoverned"                                   # C3
    if f.policy_status == "unapproved" or training == "yes" or f.admin_controls_available == "no":
        return "adverse"                                      # C2
    if (f.policy_status, training, f.admin_controls_available) == ("approved", "no", "yes"):
        return "governed"                                     # C0
    return "partial"                                          # C1
```

**2b. Exposure level (E).** `unknown` is *calculated* as `internal`, but the result never
hides that.

```python
EXPOSURE = {"public": 0, "internal": 1, "unknown": 1, "confidential": 2, "restricted": 3}
sensitivity_assumed = facts.data_sensitivity_tier == "unknown"
```

When `sensitivity_assumed` is true:

- add `data_sensitivity_tier` to `unknown_facts`;
- add reason code `sensitivity_assumed_internal`;
- return `sensitivity_assumed=True` on the `Assessment`.

The explanation (step 4) then prints the assumption. A reviewer can always tell confirmed
internal data from the fallback.

**2c. The acceptable-use matrix.** This is a constant, so changing a cell means a new rule
version.

```python
MATRIX = {            # exposure:  public  internal  confidential  restricted
    "governed":   ("Low",    "Low",    "Low",     "Medium"),
    "partial":    ("Low",    "Medium", "Medium",  "High"),
    "adverse":    ("Medium", "Medium", "High",    "High"),
    "ungoverned": ("Medium", "High",   "High",    "High"),
}
# "unassessed" → tier "unresolved" (never defaults to Medium)
```

**2d. Escalation.** At most one step up, and never down. Each rule depends on a single,
evidence-exact signal.

```python
STEP_UP = {"Low": "Medium", "Medium": "High", "High": "High"}
base_tier = MATRIX[level][EXPOSURE[sensitivity]]   # kept for the explanation
x1 = cls == "content_submission" and EXPOSURE[sensitivity] >= 2 and level != "governed"
x2 = cls == "access_grant" and level in {"adverse", "ungoverned"}
escalation = "X1" if x1 else "X2" if x2 else None
tier = STEP_UP[base_tier] if escalation else base_tier
```

- X1 uses reason code `sensitive_content_submitted_to_non_governed_tool` (LLM02).
- X2 uses `access_granted_to_non_governed_tool` (LLM03 / LLM04).
- Return `base_tier`, `escalation` (`"X1"`, `"X2"` or `None`) and `escalation_event_ids`.
  Because the class is part of the context key, `escalation_event_ids` is every event ID in
  the escalated context. Store it explicitly anyway, so the explanation and API never have
  to re-derive which events caused the step-up.
- X1 uses unknown sensitivity only at its assumed internal value, so a fallback can never
  trigger an escalation.
- Presence and unknown classes never lower a tier.

**2e. Reason codes, in priority order.** These drive the explanation, so put the most
important first.

- **Governance:** `unapproved_tool`, `customer_data_training_permitted`,
  `admin_controls_absent`. If the level is governed, use `approved_tool`,
  `no_customer_data_training` and `admin_controls_available`.
- **Exposure:** `restricted_data_context`, `confidential_data_context`,
  `internal_data_context` or `public_data_context`.
- **Escalation:** the X1 or X2 code from step 2d, when it applies.
- **Assumption:** `sensitivity_assumed_internal`, when it applies.
- **Unresolved:** `all_tool_facts_unknown`.

Keep the escalation code in its own `escalation_reason` field as well as in `reason_codes`, so
the explanation can never drop it.

**2f. Flags.** Keep the five v1 flags, then add:

| Flag | Condition |
|---|---|
| `sensitive_data_in_non_governed_tool` | exposure ≥ confidential and level ∈ {adverse, ungoverned} |
| `sensitive_use_of_unassessed_tool` | exposure ≥ confidential and level = unassessed |
| `not_in_ai_inventory` | `in_inventory` is False |
| `access_grant_observed` | class = access_grant |
| `submission_with_missing_facts` | class = content_submission **and** (sensitivity unknown **or** training = unknown) |
| `access_grant_with_missing_facts` | class = access_grant **and** (policy status unknown **or** admin controls unknown) |

The two `*_with_missing_facts` flags are a deliberate, narrow exception to v1's rule that a
single missing field never raises a flag. The exception applies only when an action was
actually observed and the fact needed to judge that action is missing. These flags also
fire when the tier is `unresolved`, so an unassessed tool with an observed upload still
carries a concrete reason to investigate.

Return the same `Assessment` shape as v1, plus `governance_level`, `exposure_level`,
`base_tier`, `escalation`, `escalation_reason`, `escalation_event_ids` and
`sensitivity_assumed`.

**Done when:** the step-8 rubric tests pass.

### Step 3: Add the framework reference table (`risk_refs.py`)

Add a static dict that maps each reason code and flag to its references. Each reference is a
tuple of framework, item and short label. Version it as `RISK_REFS_VERSION =
"owasp-refs-v1"` and add it to the pipeline's `versions`.

| Code | References |
|---|---|
| `unapproved_tool` | OWASP Checklist: Shadow AI; Governance (acceptable use matrix). NIST AI RMF GOVERN 1.6 |
| `customer_data_training_permitted` | OWASP LLM02:2026 (training opt-out). Checklist: Legal (EULA, prompts, data privacy) |
| `admin_controls_absent` | Checklist: Governance (technical enforcement). LLM02:2026 (access controls) |
| `confidential_data_context`, `restricted_data_context` | LLM02:2026. Checklist: Governance (no confidential data in non-business-managed tools) |
| `sensitive_content_submitted_to_non_governed_tool` | LLM02:2026 |
| `access_granted_to_non_governed_tool`, `access_grant_observed` | LLM03:2026 Excessive Agency. LLM04:2026 Supply Chain. OWASP Top 10 for Agentic Applications |
| `submission_with_missing_facts`, `access_grant_with_missing_facts` | Checklist: Regulatory (confirm how the vendor stores, deletes and uses data). NIST AI RMF GOVERN 6.1 |
| `not_in_ai_inventory` | Checklist: AI asset inventory. NIST AI RMF GOVERN 1.6 |

Before the demo, check each item against the official 2026 PDF and the Checklist v1.1, and
add page numbers. A reference explains why a factor matters. It never proves a vendor fact.

### Step 4: Build the explanation (`risk_explain.py`)

Write a pure function: `explain(context, assessment, category) -> Explanation(text, parts)`.

The explanation has fixed slots, filled in this order. A slot is never dropped to make room
for another.

- **Sentence 1, how the tool was used:**
  `"{department} used {tool}{category_phrase} for {purpose} with {sensitivity_phrase}
  ({n} events, {first}–{last}){activity_phrase}."`
  - `category_phrase`:
    - `", a {Category} tool"` when the method is `catalog`;
    - `", likely a {Category} tool"` when the method is `semantic_neighbor_vote`;
    - empty when the category is unresolved.
  - `sensitivity_phrase` is `"{tier} data"`, or `"data of unknown sensitivity"` when
    `sensitivity_assumed` is true.
  - `activity_phrase` is worded **per event type**, never per class, so it says exactly what
    was observed:

    | Event types in the context | Phrase |
    |---|---|
    | presence only | `"; only visits were observed"` |
    | `prompt_submit`, `chat_message` | `"; prompts were submitted"` |
    | `content_paste` | `"; pasted content was observed"` |
    | `file_upload` | `"; file uploads were observed"` |
    | `oauth_grant` | `"; the tool was granted OAuth access"` |
    | `connector_added` | `"; a connector to company systems was added"` |
    | unknown class | `"; the activity type was not recorded"` |

    If a submission context mixes types, join their phrases, for example "prompts were
    submitted and file uploads were observed".
  - Turn underscores in `usage_purpose` into spaces. When the purpose is `unknown`, write
    "for an unstated purpose".
- **Sentence 2, why it got this level.**
  - Without escalation: `"Rated {tier} because {base reason 1}[ and {base reason 2}]."`
  - With escalation: `"Rated {tier}: {base_tier} because {base reason 1}[ and {base reason 2}],
    raised one step because {escalation phrase}."` The escalation slot is reserved and always
    printed when `escalation` is set. Example escalation phrases:
    - X1: "confidential content was uploaded to a tool that is not fully governed". Use
      "submitted" or "pasted" to match the event type.
    - X2: "OAuth access was granted to a tool with an adverse governance fact".
  - Base reasons come from the governance and exposure codes, mapped to phrases. For example,
    `unapproved_tool` becomes "the tool is not approved", and `confidential_data_context` +
    adverse becomes "confidential data should not go into a non-business-managed tool".
- **Sentence 3, only when needed: assumptions and missing facts.**
  - If `sensitivity_assumed`: `"Sensitivity unknown; tier calculated using the internal-data
    assumption."`
  - Otherwise, list the material unknown vendor facts, for example "Training and
    admin-control terms are unknown."
  - Append `" Review: {action} was observed without {missing fact}."` when a
    `*_with_missing_facts` flag is set.

  This makes the explanation two sentences in the common case, and three when there is an
  assumption or a gap to show.
- **Unresolved:** `"{tool} has no usable approval or vendor facts, so no risk level was
  assigned."`
  - If `sensitive_use_of_unassessed_tool` is set, add `" It was used with {sensitivity} data
    and needs review."`
  - If a `*_with_missing_facts` flag is set, add the same "Review: …" sentence.
- `parts` keeps the structured pieces: `reasons`, `base_tier`, `escalation`,
  `escalation_event_ids`, `assumptions`, `unknowns`, `review_flags`, `refs`, `category`,
  `category_method`, `interaction_class`, `event_types` and `fact_scope`. The dashboard and
  assistant can then cite them without parsing text.

Rules for the wording:

- Never state that content was submitted unless the class is `content_submission`. Never
  state that access was granted unless the class is `access_grant`. Always name the actual
  event type.
- Never name employees.
- Never call the tier a compliance finding.

**Done when:** snapshot tests in step 8 match.

### Step 5: Assess per context (`usage_contexts.py`)

1. Add `employee_id` and `event_type` to the event fields `_usage_contexts` reads.
2. Map each event's type to an **interaction class** and add the class to the grouping key:
   `_CONTEXT_FIELDS = ("department", "usage_purpose", "data_sensitivity_tier",
   "interaction_class")`.

   ```python
   INTERACTION_CLASS = {  # blank or unrecognized → "unknown" (its own class, never merged)
       "browser_visit": "presence", "app_open": "presence", "login": "presence",
       "prompt_submit": "content_submission", "chat_message": "content_submission",
       "content_paste": "content_submission", "file_upload": "content_submission",
       "oauth_grant": "access_grant", "connector_added": "access_grant",
   }
   ```

   `extension_install`, `api_key_use` and `agent_action` are deliberately **not** in this
   map. On their own they don't establish that content was sent or that access to company
   systems was granted, so they land in `unknown`. Add each one only together with a
   confirmed rule that says what it proves.
3. Add two fields to `UsageContext`: `distinct_employee_count` (a count only) and
   `event_types` (a sorted tuple, used for the explanation wording).
4. Change `assess_usage_contexts` so it:
   - takes `category_classifications` as a new argument (aligned with `identities`);
   - keeps the gate `candidate.outcome in RESOLVED_OUTCOMES and ai.determination == "ai"`;
   - looks up the Dataset B row once per tool, as now;
   - **calls `assess()` inside the per-context loop**, building `RiskFacts` from the row plus
     the context's `data_sensitivity_tier`, `interaction_class` and `in_inventory = row is not
     None`;
   - calls `explain(...)` and stores the text and parts on `ContextAssessment`, together with
     the category, its method and share.

**Done when:** in a unit test, two ChatGPT contexts with different sensitivity get
different tiers. A Comprehend `app_open` and a Comprehend `file_upload` with identical
department, purpose and sensitivity also come out as **two contexts**, with only the upload
context escalated.

All current fixture events are `app_open` or `browser_visit`, which are both presence. The
existing fixture therefore produces exactly the same set of contexts as v1.

### Step 6: Wire the pipeline (`default.py`)

In `risk_assessment`:

1. Add `activity_events.c.employee_id` and `activity_events.c.event_type` to the select.
2. Pass `context.results["category_classifications"]` to `assess_usage_contexts`.
3. In `save`, take the category from each `ContextAssessment` instead of the separate
   `categories` map.
4. In `versions`, `risk_assessment` now reports `RISK_RULE_VERSION`, and `risk_references`
   reports `RISK_REFS_VERSION`.

### Step 7: Persistence, API and assistant

1. **Migration `0007_risk_v2_columns.py`** on `usage_context_assessments`. Use
   `batch_alter_table`, which SQLite needs.
   - Add nullable columns:
     - `category_method`, `interaction_class`, `event_types` (JSON) and
       `distinct_employee_count`;
     - `governance_level`, `exposure_level`, `base_tier`, `escalation`,
       `escalation_event_ids` (JSON) and `sensitivity_assumed`;
     - `fact_scope`, `explanation` (text) and `explanation_parts` (JSON).
   - Run `UPDATE ... SET tier = 'Low' WHERE tier = 'Lower'`.
   - Recreate the check constraint as `tier IN ('High','Medium','Low','unresolved')`.
   - v1 rows keep `rule_version = synthetic-demo-risk-v1`, so it stays clear which rules
     produced them.
2. **`tables.py`:** mirror the migration.
3. **`results.py`:** `asdict` already spreads context and assessment fields. Add the
   explanation fields, and drop the `categories` parameter.
4. **`api/runs.py`:**
   - extend `RiskFactsOut` (sensitivity, interaction class, in_inventory) and `AssessmentOut`
     (the new columns);
   - add an `interaction_class` query filter, so the dashboard can show contexts side by side;
   - change the tier `Literal` to `"Low"`;
   - optionally add `tool_id`, `department` and `flag_reason` query filters to
     `list_assessments`.
5. **`assistant/contracts.py`:** change the tier `Literal` to `"Low"`. Its
   `get_risk_assessments` tool should return `explanation` and `explanation_parts`, so the
   assistant can cite the stored explanation instead of composing its own (ADR 0004 already
   forbids it from changing tiers).

**Done when:** `alembic upgrade head` succeeds on an existing dev database, and
`GET /runs/{id}/assessments` shows the explanation.

### Step 8: Tests

Add to or replace in `backend/tests/`:

- **`test_risk.py`, rewritten for v2:**
  - every one of the 4×4 matrix cells, plus `unassessed` → `unresolved`;
  - **monotonicity**: raising exposure or worsening governance never lowers the tier (loop
    over all pairs);
  - escalation X1/X2 apply once and are capped at High, and `base_tier` and
    `escalation_event_ids` are set whenever the tier is escalated;
  - presence and unknown classes never escalate or lower a tier;
  - X1 never fires on assumed (unknown) sensitivity;
  - unknown ≠ false (for example, unapproved + training unknown is never C3);
  - `conditional` training counts as unknown;
  - unknown sensitivity is calculated as internal, sets `sensitivity_assumed`, and appears in
    `unknown_facts`;
  - both `*_with_missing_facts` flags fire, including when the tier is `unresolved`;
  - invalid values raise `ValueError`.
- **`test_risk_explain.py` (new):**
  - snapshot strings for the eight current fixture contexts and every new scenario;
  - an escalated result always contains the escalation phrase and its base tier, even when
    there are several base reasons;
  - `sensitivity_assumed` always prints the assumption sentence;
  - presence text never says content was submitted, a `content_paste` context never says
    "upload", and no text says access was granted unless the class is `access_grant`;
  - no `employee_id` appears in any text.
- **`test_usage_contexts.py`:**
  - the same tool with two sensitivities gives two tiers;
  - `app_open` and `file_upload` with the same other fields give two contexts;
  - a blank or unrecognized `event_type` (including `extension_install`) gives its own
    `unknown` context;
  - non-AI and unresolved-AI candidates get no context.
- **`test_risk_results.py` / `test_default_pipeline.py`:** v2 columns are saved and returned
  by the API; `Low` is accepted and `Lower` rejected.

### Step 9: Fixture v2 (`data/synthetic_enterprise_activity/`)

1. Copy `v1/` to `v2/`. Extend `generate_activity.py` with the scenarios below. Keep the
   fixed seed.

   | Scenario | Expected |
   |---|---|
   | Cursor · Engineering · confidential · presence | High, side by side with the existing Cursor internal context (Medium) |
   | Comprehend · Research · confidential · `file_upload` | Medium → High (X1), side by side with the existing Comprehend presence context (Medium); `submission_with_missing_facts` (training unknown) |
   | ChatGPT · Support · restricted · presence | Medium |
   | ChatGPT · Engineering · `content_paste` · unknown sensitivity | Low, with the assumption sentence and `submission_with_missing_facts` |
   | Cursor · Engineering · internal · `oauth_grant` | Medium → High (X2); `access_grant_observed`, `access_grant_with_missing_facts` |
   | Cursor · Engineering · internal · `extension_install` | its own `unknown` context: Medium, no escalation, "activity type was not recorded" |
   | Open Canvas AI · confidential · `file_upload` | unresolved, with `sensitive_use_of_unassessed_tool` and `submission_with_missing_facts` |
   | MeetOscar · public · presence | Medium |

2. Update `evaluation_only/expected_scenarios.csv` with tiers *and* the expected first reason
   code.
3. Update the fixture README: v2 rules, the new event types, and `Lower` → `Low`.

**Done when:** an end-to-end run on v2 matches every expected tier and flag. That gives you
the "risk scoring consistency against predefined governance criteria" metric the challenge
asks for.

### Step 10: Verify and hand off

1. Run the full backend test suite and the full pipeline on fixture v2.
2. Check the dashboard and assistant still work with `Low` (the tier filter and the
   assistant's tier literal).
3. Read the explanations for every fixture context aloud as a sanity check: each should make
   sense to an analyst who has not seen this guide.
4. Update `approaches.md` with a short "Risk assessment v2" entry: method, fixture results,
   known limitations.

## Known limitations to state in the demo

- Data sensitivity and purpose are **supplied** by the synthetic data, not detected. Unknown
  sensitivity is calculated as internal, and the result says so.
- Presence events (visits, app opens) do not prove anything was submitted. Extension
  installs, API key use and agent actions are not yet interpreted.
- Approval and vendor facts are synthetic demonstration assumptions, not claims about real
  vendors. They are **tool-wide**: v2 cannot tell a managed workspace from a personal
  account, so approval of a tool does not show the approved configuration was the one in
  use.
- Department and purpose group and describe contexts, but no rule uses them.
- Category informs the explanation only. It is model-predicted for unknown tools and can be
  wrong.
- Tiers are project-policy assessments, not security incidents or compliance findings.

## Out of scope for this guide

- Reading window or page *content* to infer sensitivity. That would reverse a confirmed plan
  decision and needs its own ADR.
- Numeric scores.
- SSO and retention as tier inputs.
- Category-driven tiers.
- Per-department policy exceptions.
