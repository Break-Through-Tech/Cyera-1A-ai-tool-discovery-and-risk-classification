# Synthetic enterprise activity v2

v2 extends [v1](../v1/README.md) for the contextual-risk rubric
[`owasp-usage-risk-v2`](../../../docs/risk-rubric-v2.md)
([ADR 0005](../../../docs/adr/0005-contextual-risk-uses-owasp-acceptable-use-matrix.md)).
`activity.csv` is a fictional Dataset A upload: 315 Activity Events across 20
evaluation scenarios. Scenarios 01–12 are v1's, generated with the same seed and
parameters; scenarios 13–20 are new. Because the new events are interleaved by
timestamp, event IDs differ from v1.

`generate_activity.py` uses only the Python standard library and fixed seed
`20261014`. Its sampling assumptions are the same as v1's: department and role
weights, adoption rates, event-count parameters and time weights are
illustrative, not fitted to real telemetry, and each scenario has at least two
active employees. Regenerate and verify with:

```powershell
python -B data\synthetic_enterprise_activity\v2\generate_activity.py --write
python -B data\synthetic_enterprise_activity\v2\generate_activity.py --check
```

## Event types and interaction classes

The rubric derives an **interaction class** from each event's `event_type`, and
the class is part of the Usage Context key, so different kinds of use are never
merged:

| `event_type` in this fixture | Class | What it establishes |
|---|---|---|
| `app_open`, `browser_visit` | `presence` | The tool was reached, not that anything was submitted |
| `content_paste`, `file_upload` | `content_submission` | Content was sent to the tool |
| `oauth_grant` | `access_grant` | The tool was granted access to company systems |
| `extension_install` | `unknown` | Activity of an uninterpreted type |

Presence scenarios mix `app_open` and `browser_visit`, as in v1. Every other
scenario emits only its own event type, so each scenario maps to exactly one
Usage Context. The generator checks this.

## New scenarios

| Scenario | Usage Context | Expected |
|---|---|---|
| 13 | Cursor · Engineering · confidential · presence | High, beside the Cursor internal context (Medium) |
| 14 | Amazon Comprehend · Research · confidential · `file_upload` | Medium → High (X1), beside the Comprehend presence context (Medium) |
| 15 | ChatGPT · Support · restricted · presence | Medium |
| 16 | ChatGPT · Engineering · unknown sensitivity · `content_paste` | Low, with the internal-data assumption disclosed |
| 17 | Cursor · Engineering · internal · `oauth_grant` | Medium → High (X2) |
| 18 | Cursor · Engineering · internal · `extension_install` | Medium in its own `unknown` context, no escalation |
| 19 | Open Canvas AI · Product · confidential · `file_upload` | unresolved, flagged for review |
| 20 | MeetOscar · Marketing · public · presence | Medium |

## Inputs and evaluation files

`scenario_tool_metadata.csv` is identical to v1's. Its `approved_status`,
`training_on_customer_data` and `admin_controls_available` values are synthetic
demonstration facts, **not claims about the real named vendors**, and `unknown`
stays unknown. They are **tool-wide**: the activity data cannot tell a managed
workspace from a personal account, so approval of a tool does not show the
approved configuration was the one in use. Each result records
`fact_scope = "tool_wide_scenario_assumption"`.

Purpose and sensitivity are supplied synthetic context; neither is inferred from
department, role or activity. Only the two CSVs above are inference inputs. Do not
upload or index `evaluation_only/`.

`evaluation_only/expected_scenarios.csv` maps each scenario to its `event_id`
values and expected Tool identity, AI status, Category and risk outcome. v2 adds
`expected_interaction_class`, `expected_base_tier` (the matrix tier before
escalation), `expected_first_reason_code` and `expected_flag_reasons`.
`expected_risk_behavior` is the final tier. v1's `Lower` tier is now `Low`.
Non-AI cases get no context (`not_applicable`). A Tool whose identity or AI status is unresolved gets no tier; since rubric v2.1 its usage is saved as a `not_assessed` context (`not_assessed_ai_unresolved`). An end-to-end run
matches when each scenario's events form one context with these values.

The identity, AI-status, Category and held-out contract notes in the
[v1 README](../v1/README.md) apply unchanged; the partition contract carries the
same IDs and exclusions with `risk_rule_version = owasp-usage-risk-v2.1`.

## Risk rule in brief

The tool facts set a Governance Level (governed, partial, adverse, ungoverned or
unassessed). The supplied sensitivity sets an Exposure Level; unknown is
calculated as internal and always disclosed. A fixed acceptable-use matrix gives
Low, Medium or High, and a Tool with no usable facts stays unresolved. The tier
rises one step when sensitive content was submitted to a Tool that is not fully
governed, or OAuth access or a connector was granted to a Tool with an adverse
fact. Investigation flags are independent of the tier. These rules assess Usage
Contexts, not global Tool risk, and are not a security certification,
compliance finding or organizational policy claim.
