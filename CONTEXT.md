# AI Tool Governance

Language for the challenge-limited prototype that discovers software usage, determines AI relevance, and supports contextual governance-risk decisions.

## Language

**Tool**:
An identifiable software product, service, model, API, extension, or feature that may be observed or catalogued and has a stable project identity independent of its name or domain. Each retained catalog listing initially identifies a separate Tool unless multiple listings are confirmed to describe the same product.
_Avoid_: Using Tool to mean only an AI-related tool; catalog listing

**AI Tool**:
A Tool whose AI-related status has been established under the project's operational definition.
_Avoid_: Any Tool under evaluation; any AIToolBuzz-like name

**Activity Event**:
One normalized record of observed application activity from an uploaded dataset. It is evidence of activity, not proof of Tool identity, purpose, data sensitivity, or risk.
_Avoid_: Tool use; Usage Context

**Category**:
One of the 14 supplied AIToolBuzz business-function labels describing what an AI Tool generally does.
_Avoid_: Usage Purpose; department; observed intent

**Usage Purpose**:
The supplied or synthetic reason a Tool is used within one Usage Context.
_Avoid_: Category; general Tool function

**Data Sensitivity Tier**:
The supplied or synthetic sensitivity of the data involved in one Usage Context; it may be unknown. The prototype consumes this context but does not infer sensitivity or inspect content to establish it.
_Avoid_: Predicted sensitivity; content inspection; risk tier

**Batch**:
One immutable uploaded dataset of Activity Events. Re-analysis does not change the Batch.
_Avoid_: Analysis Run; upload attempt

**Analysis Run**:
One execution of a particular discovery, classification, and risk-rule version against a Batch; a Batch may have multiple runs, and execution failure is distinct from an unresolved domain determination.
_Avoid_: Batch; model version; unresolved determination

