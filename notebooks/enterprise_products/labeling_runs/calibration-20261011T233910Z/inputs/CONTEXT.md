# AI Tool Governance

Language for the challenge-limited prototype that discovers software usage, determines AI relevance, and supports contextual governance-risk decisions.

## Language

**Tool**:
An identifiable software product, service, model, API, extension, or feature that may be observed or catalogued and has a stable project identity independent of its name or domain. Each retained catalog listing initially identifies a separate Tool unless multiple listings are confirmed to describe the same product.
_Avoid_: Using Tool to mean only an AI-related tool; catalog listing

**AI Tool**:
A Tool whose AI-related status has been established under the project's operational definition.
_Avoid_: Any Tool under evaluation; any AIToolBuzz-like name

**Previously Unseen Tool**:
A Tool absent from both the known-Tool reference set and the evidence used to develop the relevant models at a recorded evaluation cutoff. Being previously unseen is evaluation-relative and cites its registry, training-data, and retrieval-corpus basis; an observed identity remains stable across Analysis Runs for its Batch without implying identity across Batches.
_Avoid_: Unresolved Tool Candidate; permanent Tool subtype

**Activity Event**:
One normalized record of observed application activity from an uploaded dataset. It is evidence of activity, not proof of Tool identity, purpose, data sensitivity, or risk.
_Avoid_: Tool use; Usage Context

**Tool Candidate**:
Within one Analysis Run, a deterministic grouping of identity clues from one or more Activity Events that may refer to one Tool but has not yet been resolved. Stable conflicting locators remain separate; unresolved identity does not prevent candidate-scoped classification when controlled metadata is sufficient.
_Avoid_: Provisional Tool; unknown Tool

**Identity Resolution**:
The determination that yields an existing known Tool, a Batch-stable observed Tool, or an unresolved Tool Candidate. Its outcome is independent of AI Determination; unresolved identity does not imply that the candidate is non-AI.
_Avoid_: Classification; Tool detection

**AI Determination**:
The determination that a Tool or Tool Candidate is AI-related, non-AI, or unresolved under the project's operational definition, with its decision method and versioned provenance. It is separate from Tool identity.
_Avoid_: Identity Resolution; Category Classification

**Category**:
One of the 14 supplied AIToolBuzz business-function labels describing what an AI Tool generally does.
_Avoid_: Usage Purpose; department; observed intent

**Category Classification**:
The determination that assigns one Category to an AI Tool or AI-positive Tool Candidate, remains unresolved when category evidence is insufficient, or is inapplicable when AI status does not permit categorization. Assigned catalog and model results retain their distinct decision methods and provenance.
_Avoid_: AI Determination; Usage Purpose

**Semantic Neighbor**:
A versioned retrieval result identifying a catalog Tool or document as semantically similar to a Tool or Tool Candidate. It is supporting comparison evidence, not authority for identity, AI status, or Category.
_Avoid_: Identity match; classification decision; canonical Tool alias

**Abstention**:
A successful, applicable stage outcome that remains unresolved for a stage-specific reason. It is distinct from an inapplicable stage and from Analysis Run failure.
_Avoid_: Pipeline failure; inapplicable result; forced negative result

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

**Usage Context**:
An Analysis Run's grouping of activity involving one resolved Tool within a shared department, Usage Purpose, Data Sensitivity Tier, and time window. Only a Usage Context involving an AI Tool is eligible for contextual governance-risk assessment.
_Avoid_: Activity Event; Tool Candidate; global Tool risk

**Policy Status**:
An organization- or synthetic-scenario-supplied disposition toward a Tool within a Usage Context; it may be unknown. It is contextual evidence for risk assessment, not a decision created by the risk engine.
_Avoid_: Risk tier; inferred approval

**Contextual Risk Assessment**:
A deterministic evaluation of an AI Tool's Usage Context against the project's versioned governance-risk rules, producing risk factors, a tier, reasons, and unknowns. It does not establish Policy Status or compliance.
_Avoid_: Global Tool risk; Policy Status; compliance determination

**Evidence**:
A provenance-preserving source used to support a determination, assessment, or explanation and referenced by stable source identity, version, and explicit role. Evidence does not erase distinctions among observed activity, Tool, contextual or policy, and governance sources.
_Avoid_: Generic evidence blob; unsupported claim; interchangeable authority
