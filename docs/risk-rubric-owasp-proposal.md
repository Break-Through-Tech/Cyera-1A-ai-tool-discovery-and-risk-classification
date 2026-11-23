# Proposal: OWASP-informed usage risk rubric (`synthetic-demo-risk-v2`)

> **Status: Proposed. Not confirmed.** This is a candidate replacement for the confirmed
> `synthetic-demo-risk-v1` rubric. Per the planning protocol in `PROJECT_PLAN.md`, it needs
> team discussion and explicit confirmation before it changes `PROJECT_PLAN.md` or code.
> Like v1, it is a framework-informed **synthetic demonstration policy**. It is not Cyera
> policy, not an OWASP-prescribed tiering, and not a compliance determination.

> **Revised.** Sections 3c, 5 and 6 are superseded by
> [`risk-v2-implementation-guide.md`](risk-v2-implementation-guide.md), revision 2.
> Interaction class is now part of the Usage Context key, access grants are limited to
> OAuth grants and connector additions, and assumptions and missing facts are shown in
> the result.

## 1. Recommendation in one paragraph

Base the rubric on two OWASP GenAI Security Project documents used together:

1. **OWASP LLM AI Cybersecurity & Governance Checklist (v1.1).** This is the OWASP document
   written for organizations that *use* AI tools. It names **Shadow AI** (employees using
   unapproved online AI tools, unsafe browser plugins, and SaaS apps that add LLM features
   through updates) as the most pressing non-adversary LLM threat. It also calls for three
   things that map directly onto our pipeline: an **AI asset inventory** that records data
   sensitivity, an **acceptable use matrix for generative AI tools**, and a rule that
   protected or confidential data must not go into non-business-managed tools. It supplies
   the rubric's *structure*: the tier matrix in section 4 is that acceptable use matrix.
2. **OWASP Top 10 for LLM Applications 2026** (published 3–4 August 2026). This supplies the
   risk *vocabulary* that each reason code cites. Only four entries are mainly the user
   organization's concern, not the vendor's: **LLM02 Sensitive Information Disclosure** (the
   top priority; staff pasting data into tools is the core case), **LLM01 Prompt
   Injection**, **LLM03 Excessive Agency**, and **LLM04 Supply Chain** (the AI apps,
   extensions and MCP servers staff install). LLM07 Misinformation applies in part, where AI
   output drives decisions or leaves the company.

This keeps the existing framework decision intact. NIST AI RMF still provides the governance
structure, and OWASP informs the checks, which is what `PROJECT_PLAN.md` already says. v2
makes the OWASP part concrete.

### Why not the other OWASP options

| OWASP resource | Why it isn't the primary basis |
|---|---|
| Top 10 for LLM Applications (alone) | Written for teams that *build* LLM apps. Most of its controls sit inside the vendor's application, which we cannot see. We use it only as the citation vocabulary. |
| AIVSS (AI Vulnerability Scoring System, v0.8) | It scores *vulnerabilities in agentic systems*, using CVSS v4.0 plus agentic amplification factors. We assess *usage contexts* of third-party tools, not vulnerabilities, and the plan rules out numeric scores. |
| Top 10 for Agentic Applications 2026 | Relevant only where a tool acts with delegated authority (agents, connectors, OAuth). It is cited by the delegated-authority escalation in section 5 and is not a core input. |
| OWASP AI Exchange | A broad threat and control catalogue for AI system builders. It is useful background, but it is not usage-specific. |

## 2. What v1 does today, and what is missing

`backend/app/pipeline/risk.py` (`synthetic-demo-risk-v1`) uses three **Tool-level** facts:
`approved_status`, `training_on_customer_data` and `admin_controls_available`.
`usage_contexts.py` already groups activity by department, `usage_purpose` and
`data_sensitivity_tier`, but `assess()` runs **once per Tool**. Every context of a Tool
therefore gets the same tier.

This contradicts the confirmed principle that "the same Tool may have different assessments
in different contexts". It also means v1 ignores *how* the AI was used. v2 adds the usage
signals we already collect (supplied data sensitivity, observed interaction type, supplied
purpose). It keeps every v1 guardrail.

## 3. Rubric inputs

Each input is an ordinal level with an explicit `unknown`. `unknown` is never treated as the
favourable value.

### 3a. Data exposure (E). Source: supplied `data_sensitivity_tier` on the Usage Context.

| Level | Tier value | OWASP basis |
|---|---|---|
| E0 | `public` | — |
| E1 | `internal` | Checklist: catalogue AI data sources and their sensitivity |
| E2 | `confidential` | LLM02:2026 (confidential business data). Checklist: confidential data must not go into non-business-managed tools |
| E3 | `restricted` (regulated: PII, PHI, credentials, payment data) | LLM02:2026 (PII, health records, credentials). Checklist Regulatory/Legal |
| E? | `unknown` / blank | Assessed **as the organization default (`internal`)** and always listed as a material unknown |

Sensitivity stays *supplied* context. We never infer it from department, role, bytes or
Category, as the plan already requires.

### 3b. Governance control gap (C). Source: Dataset B Policy Status and vendor facts.

The three adverse facts are `unapproved`, `training_on_customer_data = yes` and
`admin_controls_available = no`.

| Level | Rule (evaluate top-down) | OWASP basis |
|---|---|---|
| C? | every fact unknown, including the case where the Tool has no Dataset B row | Checklist: AI asset inventory gap |
| C3 Ungoverned | `unapproved` **and** training = `yes` | Checklist Shadow AI + LLM02 (training on submissions; mitigation is opt-out of training) |
| C2 Adverse | at least one adverse fact | Checklist Shadow AI / Governance (technical enforcement) / Legal (EULA review of prompts and data use) |
| C1 Partially governed | no adverse fact, at least one known fact, and not every fact is confirmed favourable | Checklist Regulatory: confirm how the vendor stores and uses data |
| C0 Governed | `approved` **and** training = `no` **and** admin controls = `yes` | Checklist Governance: business-managed tool with enforceable controls |

`conditional` training terms stay `unknown`, as in v1. SSO and retention are still reported
as evidence but do not change C. Adding them later is a separate policy change.

### 3c. Interaction depth (D). Source: observed `event_type`. The context takes the maximum across its events.

| Level | `event_type` values | Meaning | OWASP basis |
|---|---|---|---|
| D0 Presence | `browser_visit`, `app_open`, `login`, blank | Tool reached; **no evidence of submission** | — |
| D1 Interaction | `prompt_submit`, `chat_message` | Content was sent to the tool | LLM02 |
| D2 Data transfer | `file_upload`, `content_paste` | A document or bulk content was sent | LLM02 |
| D3 Delegated authority | `extension_install`, `oauth_grant`, `connector_added`, `api_key_use`, `agent_action` | The tool can read or act on company systems | LLM03 Excessive Agency, LLM04 Supply Chain, LLM01 Prompt Injection; Agentic Top 10 |

`activity-v1` fixtures contain only D0. D1–D3 are new **allowed values** for the existing
optional `event_type` column. No column needs to be added.

### 3d. Usage purpose class (P). Explanation only; it does not change the tier.

Supplied `usage_purpose` values map to a class through a small versioned lookup.
Unrecognized values become `unknown`.

| Class | Current fixture purposes | OWASP concern tags shown with the result |
|---|---|---|
| `code_generation` | `code_assistance`, `software_development` | LLM02 (source code), LLM04 (hallucinated or "slopsquatted" packages), LLM10 (AI-written code) |
| `external_communication` | `email_campaigns`, `sales_outreach` | LLM07 (output reaches customers), LLM02 (prospect personal data) |
| `content_analysis` | `draft_summary`, `text_analysis` | LLM02 (documents submitted), LLM07 (decisions built on summaries) |
| `automation_testing` | `visual_testing` | LLM03 (the tool acts on systems) |
| `ideation` | `product_ideation` | LLM02 (unreleased plans) |

Category (the 14 AIToolBuzz labels) is deliberately **not** an input. Its expected accuracy
(about 63–71% where answered) is too low to drive a governance tier.

## 4. Tier matrix (the synthetic acceptable use matrix)

| Control gap \ Exposure | E0 public | E1 internal / E? | E2 confidential | E3 restricted |
|---|---|---|---|---|
| **C0 Governed** | Lower | Lower | Lower | Medium |
| **C1 Partially governed** | Lower | Medium | Medium | High |
| **C2 Adverse** | Medium | Medium | **High** | High |
| **C3 Ungoverned** | Medium | High | High | High |
| **C?** | unresolved | unresolved | unresolved | unresolved |

How to read the matrix:

- It is **monotonic**. Moving right (more sensitive data) or down (weaker governance) never
  lowers the tier. Tests should assert this exhaustively, since there are only 25 cells.
- **C2 × E2 = High** encodes the Checklist rule directly: confidential data in a Tool with an
  adverse governance fact.
- **C0 × E3 = Medium.** Regulated data needs explicit review even in a governed Tool.
- **C?** keeps v1's contract that a Tool with no usable facts stays `unresolved`. It does not
  default to Medium. A flag (section 6) still surfaces sensitive use of such a Tool.
- The tiers stay `High / Medium / Lower / unresolved`, so the existing DB check constraint is
  unchanged. There is no numeric score, as before.

## 5. Interaction-depth escalation (at most one step up, never down)

| Rule | Condition | Effect | Reason code |
|---|---|---|---|
| X1 | D ≥ D2 **and** E ≥ E2 **and** C ≥ C1 | Lower→Medium or Medium→High | `sensitive_data_transfer_observed` |
| X2 | D = D3 **and** C ≥ C2 | Lower→Medium or Medium→High | `delegated_authority_to_ungoverned_tool` |

D0 **never lowers** a tier. If no prompt or upload was seen, that is missing telemetry, not
evidence of safe use. This is consistent with the plan's rule that a visit does not prove
submission, and that the absence of a submission event does not prove there was none.

## 6. Investigation flags (independent of tier)

These are v1's flags plus four new ones:

| Flag reason | Trigger | Basis |
|---|---|---|
| `high_tier` | tier = High | v1 |
| `unapproved_tool` | Policy Status = `unapproved` | v1; Checklist Shadow AI |
| `customer_data_training_permitted` | training = `yes` | v1; LLM02 |
| `admin_controls_absent` | admin = `no` | v1 |
| `insufficient_evidence_for_tier` | tier = unresolved | v1 |
| **`sensitive_data_in_non_governed_tool`** | E ≥ E2 **and** C ∈ {C2, C3} | Checklist Governance |
| **`sensitive_use_of_unassessed_tool`** | E ≥ E2 **and** C = C? | Checklist AI asset inventory |
| **`not_in_ai_inventory`** | resolved AI Tool with no Dataset B row | Checklist AI asset inventory; Shadow AI |
| **`delegated_authority_observed`** | D = D3 | LLM03 / LLM04; Agentic Top 10 |

As in v1, a single missing field or a department name never raises a flag on its own. Flags
and tiers describe Usage Contexts, and **individual employees are never ranked**.

## 7. Reason codes and framework references

Each reason code links to a static, versioned framework-reference table. The dashboard and
the RAG assistant can then cite *why* a factor matters without the citation being treated as
proof of a vendor fact. Suggested table (`risk_rule_refs-v2`):

| Reason code | Framework references |
|---|---|
| `unapproved_tool` | OWASP Checklist: Shadow AI; Governance (acceptable use matrix). NIST AI RMF GOVERN 1.6 (AI inventory) |
| `customer_data_training_permitted` | OWASP LLM02:2026 (mitigation: training opt-out, retention transparency). Checklist Legal (EULA: prompts, data privacy) |
| `admin_controls_absent` | Checklist Governance (data policies with technical enforcement). LLM02 (access controls) |
| `confidential_data_context` / `restricted_data_context` | LLM02:2026. Checklist Governance (no confidential data in non-business-managed tools) |
| `sensitive_data_transfer_observed` | LLM02:2026 |
| `delegated_authority_to_ungoverned_tool` | LLM03:2026 Excessive Agency. LLM04:2026 Supply Chain. OWASP Top 10 for Agentic Applications |
| `not_in_ai_inventory` | Checklist AI asset inventory. NIST AI RMF GOVERN 1.6 |
| vendor-fact unknowns | Checklist Regulatory (ask how the vendor stores, deletes and uses data). NIST AI RMF GOVERN 6.1 (third-party policies) |

Store the passage locator and capture date for each reference, as the evidence/provenance
contract requires. A framework passage establishes why a factor matters. It does not
establish an organizational or vendor fact.

## 8. Effect on the current fixture (`synthetic_enterprise_activity/v1`)

| Usage Context | C | E | D | v1 | v2 |
|---|---|---|---|---|---|
| ChatGPT · Engineering · code_assistance | C0 | E1 | D0 | Lower | Lower |
| ChatGPT · Finance · draft_summary | C0 | E2 | D0 | Lower | Lower |
| Cursor · Engineering · software_development | C2 | E1 | D0 | Medium | Medium |
| MeetOscar · Marketing · email_campaigns | C3 | E1 | D0 | High | High |
| Playbooks · Sales · sales_outreach | C3 | E1 | D0 | High | High |
| Magic Inspector · Engineering · visual_testing | C0 | E1 | D0 | Lower | Lower |
| Amazon Comprehend · Research · text_analysis | C1 | E2 | D0 | Medium | Medium |
| Open Canvas AI · Product · product_ideation | C? | E1 | D0 | unresolved | unresolved |

v2 reproduces every existing expected tier, so the hidden `expected_scenarios.csv` stays
valid apart from new flags and reason codes. That also means **the current fixture cannot
show usage-driven differences**. Add a `v2` fixture, or new scenarios, that do:

1. **Same Tool, different usage.** Cursor · Engineering · `confidential` (proprietary source
   code) gives C2 × E2 = **High**, beside the existing Cursor `internal` context at Medium.
   This is the headline demo of "risk depends on how it was used".
2. **Upload escalation.** Amazon Comprehend · `confidential` plus a `file_upload` event: X1
   moves it from Medium to **High**.
3. **Regulated data in an approved Tool.** ChatGPT · Support · `restricted` (customer PII)
   gives C0 × E3 = **Medium**.
4. **Delegated authority.** Cursor plus `extension_install` or `agent_action`: X2 moves it
   from Medium to **High**, and the context gets `delegated_authority_observed`.
5. **Unassessed sensitive use.** Open Canvas AI · `confidential` stays `unresolved` but gets
   `sensitive_use_of_unassessed_tool`.
6. **Public data.** MeetOscar · `public` gives C3 × E0 = **Medium**, which shows that the
   rubric is not uniformly punitive.

## 9. Implementation fit (small, local changes)

- `backend/app/pipeline/risk.py`
  - bump to `RISK_RULE_VERSION = "synthetic-demo-risk-v2"`;
  - add `data_sensitivity_tier` and `interaction_depth` to `RiskFacts`;
  - derive C, look up the matrix, apply X1/X2, then compute flags;
  - keep the existing input validation style (`_ALLOWED`).
- `backend/app/pipeline/usage_contexts.py`
  - call `assess()` **per context**, not per Tool;
  - compute `interaction_depth` as the maximum level over the context's events;
  - map `usage_purpose` to its class for the concern tags.
- `backend/app/db/tables.py`: no schema change is needed. `facts`, `reason_codes` and
  `flag_reasons` are already JSON columns, and the tier constraint is unchanged. Concern tags
  can go in `facts` or in a new nullable JSON column.
- `backend/app/ingestion/activity.py`: `event_type` stays optional free text. Document the
  new allowed values; unknown values map to D0.
- `backend/tests/test_risk.py`: add an exhaustive monotonicity test over the 5×5 matrix,
  "D0 never lowers", unknown-not-false tests, and the six new scenarios in section 8.

## 10. Decisions the team needs to confirm

1. Adopt the OWASP Governance Checklist + LLM Top 10 2026 pairing as the OWASP basis named in
   "Framework and decision boundary".
2. The matrix cells, especially C0×E3 = Medium, C2×E2 = High and C3×E0 = Medium.
3. Treating unknown sensitivity as the `internal` default, which is conservative and always
   disclosed.
4. The D1–D3 `event_type` vocabulary, and whether to generate a v2 fixture with it.
5. Whether purpose classes remain explanation-only. The recommendation is yes until there is
   a justified rule.

## Sources

- OWASP LLM AI Cybersecurity & Governance Checklist v1.1 (OWASP GenAI Security Project, May 2024): https://genai.owasp.org/initiatives/llm-applications-cybersecurity-and-governance-checklist/ (text consulted via the v1.0 PDF mirror: https://ciso2ciso.com/wp-content/uploads/2024/04/LLM-AI-CYBERSECURITY-GOVERNNACE-CHECKLIST.pdf)
- OWASP Top 10 for LLM Applications 2026, summary of changes: https://cloudsecurityalliance.org/blog/2026/10/21/the-owasp-top-10-for-llm-applications-2026-what-changed-and-why-it-matters
- Which 2026 entries apply to organizations that use rather than build AI tools: https://jazz.security/dlp-explained/dlp-basics/what-is-the-owasp-top-10-for-llm-applications/
- LLM02 Sensitive Information Disclosure (2025 text; same ID in 2026): https://genai.owasp.org/llmrisk/llm022025-sensitive-information-disclosure/
- OWASP AIVSS v0.8 (considered, not adopted): https://aivss.owasp.org/
- Consulted 2026-11-18. Verify passage locators against the official 2026 PDF before storing them as evidence.
