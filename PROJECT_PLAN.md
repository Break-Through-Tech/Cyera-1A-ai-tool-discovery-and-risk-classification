# AI Tool Discovery & Risk Classification — Project Plan

> Canonical planning record. Only decisions explicitly discussed and confirmed are listed as confirmed.

## Status legend

- **Confirmed** — discussed, implications understood, and explicitly accepted.
- **Provisional** — current direction, pending external guidance or evidence.
- **Deferred** — intentionally postponed until its project phase.

## Planning protocol — Confirmed

Before recording an architecture or design choice as confirmed, discuss realistic alternatives, implications, limitations, and failure modes; recommend an option; and receive explicit user confirmation. Feedback-only discussion does not authorize edits to planning artifacts.

## Baseline scope — Confirmed

`VISION.md` is the current source of truth for product scope and success; it supersedes the deliverable list in `Challenge-Project-Overview.md`. Build a governance-analyst decision-support prototype that turns synthetic enterprise activity into investigable, explainable AI-governance insights. The product provides oversight and recommendations, not real-time security hardening or automated enforcement.

The assistant, trained-model experiments, 14 AIToolBuzz categories, and local-first stack remain deliberate team choices even where the vision leaves implementation open. Suggested techniques are not separate deliverables; ignore clustering, fine-tuning, XGBoost, orchestration frameworks, or other components unless an experiment or explicit need justifies them.

### Primary user — Confirmed

A **Governance Analyst** who needs visibility into organizational AI-tool usage, classification, contextual risk, trends, and grounded governance insights. The Challenge Advisor accepted the planned end-to-end flow in `VISION.md`.

## Requirements traceability

The vision sets the outcomes; detailed methods and metrics below are our chosen ways to build and check them, not additional requirements imposed by `VISION.md`.

| Source | Outcome or chosen capability | Planned capability | Evidence |
|---|---|---|---|
| Vision | Ingest synthetic enterprise activity | Upload and process versioned browser/network/application batches | Valid batch succeeds; invalid batch fails clearly |
| Vision | Identify AI-related tools | Known-catalog lookup plus binary detection for unresolved candidates | Accuracy, precision, recall, F1, PR-AUC, confusion matrix, and error counts |
| Vision | Categorize business function | Classify into the 14 supplied AIToolBuzz categories (chosen taxonomy) | Accuracy, macro and weighted or micro F1, per-class precision/recall and support, and confusion matrix |
| Vision | Detect previously unseen tools | Evaluate held-out catalog tools and reviewed out-of-catalog candidates | Separate unseen-tool classification and retrieval results |
| Vision | Explainable governance assessment | Framework-grounded deterministic contextual-risk rules | Consistency, monotonic scenarios, unknown handling, reason codes |
| Team choice | Semantic retrieval for the assistant | Retrieve relevant tool and governance evidence | Retrieval relevance metrics defined during the RAG phase |
| Team choice | RAG conversational assistant | Database-wide, cross-Batch grounded chat; selected-Batch chat is a stretch goal | Response quality, groundedness, and citations defined during the RAG phase |
| Vision | Investigation interface | Read-only batch ingestion, inventory, trends, risk views, and details | Demonstrated filters, risk visualization, trend reporting, and usability tasks |
| Vision | Governance insights | Explain classifications and risk factors from stored evidence | Traceable evidence, confidence, rule reasons, and limitations |
| Team choice | Trained ML classification pipeline | Offline training and versioned inference artifacts | Reproducible experiments and comparisons in `approaches.md` |
| Optional | Timed manual-effort comparison | If useful, compare fixed governance tasks manually and with the prototype | Compare time and records inspected alongside correctness or completeness; label results as a limited project simulation |
| Team choice | Technical documentation and presentation | Reproducible setup, methodology, results, limitations, and demo workflow | Final README and presentation artifacts |

## End-to-end workflow — Confirmed

```text
Synthetic activity batch
        ↓
Validate and normalize
        ↓
Resolve known AIToolBuzz tools
        ↓
Run AI detection for unresolved candidates
        ↓
Classify unresolved AI tools into AIToolBuzz categories
        ↓
Apply contextual governance-risk rules
        ↓
Persist a versioned Analysis Run
        ↓
Read-only dashboard and conversational assistant
```

The final product is a batch governance application, not a notebook-only demonstration or real-time monitoring platform. Notebooks remain appropriate for EDA and offline model experiments.

## Data boundaries

### AIToolBuzz definition of an AI Tool — Confirmed

AIToolBuzz is sufficient ground truth for the project's operational definition of an AI Tool:

> An AI Tool is any cleaned AIToolBuzz catalog entry, plus a previously unseen product, service, model, API, extension, or identifiable feature that satisfies the same AI-functionality definition after review.

- AIToolBuzz records are project-positive AI examples.
- Absence from AIToolBuzz does not imply non-AI.
- Claims must be scoped to this operational definition rather than presented as universal truth.

### Observed AI-tool activity — Confirmed

A visit to ordinary SaaS that offers AI features is not evidence that its AI feature was used. Report observed AI-tool activity only when the event identifies an AI-specific application or feature sufficiently; a visit to an AI-specific application does not prove a prompt, document, or sensitive content was submitted. Ambiguous activity is not counted as observed AI use.

### Category target — Confirmed

The initial supervised business-function target is the existing 14-value AIToolBuzz `Category` field, unchanged:

1. Ai And Machine Learning
2. Business And Finance
3. Communication And Support
4. Creative And Entertainment
5. Data And Analytics
6. Education And Learning
7. Industry Specific
8. Marketing And Sales
9. Media And Content Creation
10. Operations And Management
11. Personal And Lifestyle
12. Security And Privacy
13. Specialized Technologies
14. Technology And Development

`Primary Task`, `Keywords`, and `technologies` must not be used in the primary category baseline until leakage analysis demonstrates that their use is legitimate.

### Binary non-AI controls — Confirmed boundary, implementation deferred

A small matched set of independently verified ordinary software/SaaS records will support binary AI/non-AI evaluation. The CompanyEnrich Kaggle SaaS dataset is a candidate pool for reviewed non-AI examples, not a negative label source: SaaS and AI overlap, and keyword exclusion does not establish non-AI status. Review only selected Tool-level controls, retain their labels separately from inference, and keep evaluation examples out of training and lookup. Random unrelated websites are unsuitable because source and writing-style differences could make the task artificially easy.

Exact training ratios, class weighting, calibration, threshold selection, and final sample sizes are deferred to model development.

### Previously unseen Tool — Confirmed

A previously unseen Tool has no canonical identity, alias, domain mapping, same-tool description, or retrieval document present in model training or the known-tool registry at the evaluation cutoff. At runtime, it may arrive with controlled observed metadata such as name, domain, and short description. If that evidence is insufficient, the result remains unresolved.

Two cohorts are required:

1. Entire AIToolBuzz tools held out from training and lookup.
2. A small reviewed set of out-of-catalog AI candidates.

Vendor-held-out evaluation is an additional stress test, not the primary definition.

### Catalog lifecycle — Confirmed

AIToolBuzz is a fixed, versioned snapshot. The application performs no runtime catalog crawling or status refresh. Future catalog snapshots create new dataset and model versions.

### Controlled metadata — Confirmed

Unknown tools must arrive with controlled metadata such as name, domain, short description, source, and capture date. Runtime web crawling is out of scope. An unknown domain without sufficient metadata remains unresolved.

### Cleaning and deduplication — Confirmed

Preserve the supplied source file and create a cleaned view:

- normalize names, websites, domains, and category formatting;
- remove malformed or unusable modeling records;
- drop only confirmed duplicates;
- retain same-name records when domains or products differ;
- keep suspected duplicate or near-duplicate groups within one model partition.

A runtime product-identity knowledge graph or manual deduplication UI is out of scope.

## Synthetic activity — Confirmed baseline; final schema deferred

Synthetic data is a scenario-driven end-to-end evaluation and demonstration dataset, not a claim about real enterprise prevalence. Dataset A contains observable Activity Events and may carry optional, explicitly supplied purpose and sensitivity context alongside them; neither becomes an inferred observation. Valid Activity Events require a unique `event_id` within the upload, a valid `Z`-formatted UTC timestamp, synthetic employee ID, department, application name, and domain. Generated fixtures use `event_id` as a stable cross-file event key: repeated appearances of the same synthetic event retain the same ID. Dataset B remains separate Tool metadata. Expected identity, AI status, category, and risk behavior are held in a separate evaluation-only file, never supplied to inference.

A frozen, versioned partition record covers known-Tool lookup, model-development data, retrieval evidence, and evaluation. Suspected same-product listings stay together; holding a Tool out of lookup alone does not establish unseen status. Controlled name, domain, and description may be supplied at inference, but held-out answers cannot. Catalog-held-out and reviewed out-of-catalog cohorts are evaluated separately. Each Analysis Run pins the retained, file-backed Dataset B metadata snapshot by path and SHA-256 checksum; infrequent corrections produce a new snapshot for explicit re-analysis, without a metadata-management UI.

Fixtures use entirely fictional employees and activity with no real submitted content. Public vendor evidence is source-dated and distinguished from invented demonstration attributes; neither is presented as verified current policy without support. The Challenge Advisor accepted the synthetic approach without additional schema, scale, realism, or validation requirements. Optional employee Dataset C is not required.

Uploads validate atomically: any malformed row, duplicate `event_id`, invalid timestamp, or missing required input rejects the whole file with row-specific errors and creates no Batch. Sparse optional evidence is valid and may lead to unresolved analysis rather than ingestion failure. A valid Batch's activity period is the minimum through maximum UTC event timestamp, not the upload time. Event references combine Batch identity with the supplied `event_id` and remain stable across its Analysis Runs.

Scenario generation deliberately and reproducibly covers known, unseen, non-AI, ambiguous, and differing-risk paths, with optional seeded variation. Fixture frequencies are not estimates of enterprise prevalence; report scenario coverage rather than population-level rates. AIToolBuzz supplies AI and category labels; a reviewed subset of SaaS candidates supplies non-AI controls. Scenario definitions establish the intended Tool identity, and a small set of explicit rule examples checks risk tiers, reasons, and unknown handling. These evaluation answers remain hidden from inference; no exhaustive event-by-event hand-labeling or mandatory Tool-level `risk_label` is needed.

```text
Synthetic scenario
    ├── expected Tool identity
    ├── expected AI/non-AI status
    ├── department
    ├── business context
    ├── data-sensitivity tier
    ├── approval status
    └── expected governance behavior
            ↓
Generated browser/network/application events
```

The application receives observable event fields and supplied contextual metadata. Hidden expected outcomes remain separate and are available only to evaluation code.

The Challenge Advisor accepted the synthetic-data baseline; final input schema details remain implementation decisions.

## Discovery pipeline — Confirmed

Use lookup first and models only for unresolved candidates:

```text
Known domain/application
    → resolve from cleaned AIToolBuzz catalog

Unknown + sufficient controlled metadata
    → binary AI detection
    → 14-category classification when AI-related
    → semantic-neighbor evidence

Unknown + insufficient metadata
    → unresolved
```

Low-confidence cases must not receive forced labels.

## Risk assessment

### Assessment unit — Confirmed

Risk belongs to a **Usage Context**, not globally to a Tool and not independently to every raw event:

```text
Tool + department + purpose + data sensitivity + time window
    → contextual assessment
```

The same Tool may have different assessments in different contexts.

### Framework and decision boundary — Confirmed

- NIST AI RMF provides the governance structure.
- NIST's Generative AI Profile informs risk dimensions.
- OWASP informs technical-security checks.
- The project does not claim formal framework compliance or certification.

The final risk result is deterministic. An LLM may retrieve or extract cited evidence and explain a result, but it does not choose the risk tier. A learned risk classifier is deferred unless genuine adjudicated risk labels later exist.

```text
Evidence + Usage Context + Policy Status
        ↓
Versioned project rules
        ↓
Risk factors + tier + reasons + unknowns
```

Tool evidence, contextual risk, organizational Policy Status, and missing evidence remain distinct.

### Policy source — Confirmed

The Challenge Advisor supplied no organization policy or example. Use a clearly labeled, research- and framework-informed synthetic demonstration policy. It must never be represented as Cyera's actual policy or a certification.

### Initial contextual-risk contract — Confirmed

- Within each Analysis Run, group observed activity for a resolved AI Tool by department, supplied purpose and data-sensitivity tier (each `unknown` when absent), over the selected Batch's activity period. The Batch period is the earliest through latest normalized event timestamp; each context also retains its own observed first/last timestamps and event references. These ranges do not imply continuous use. Trends use event timestamps separately. Unresolved identity or AI status does not receive a contextual-risk tier.
- Dataset B's `approved_status` is supplied synthetic organization-wide Policy Status for the Tool, applied to each context without inventing department-specific exceptions. Vendor attributes are separate Tool evidence. The initial rules use only approval, `training_on_customer_data`, and `admin_controls_available`; `unknown` is never treated as `false`. Conditional training terms without a known applicable plan remain unknown. SSO availability and retention may be reported as evidence but do not yet change the tier.
- The versioned synthetic demonstration rubric assigns **High** when an unapproved AI Tool has observed activity and applicable evidence says customer submissions may be used for training; this is potential governance exposure, not proof that data was submitted. It assigns **Lower** when the Tool is approved, applicable evidence says customer data is not used for training, and admin controls are available. It assigns **Medium** for other classifiable cases with at least one usable rubric fact. If all rubric facts are unknown, the assessment remains unresolved rather than defaulting to Medium. No numeric score or invented retention cutoff is used.
- A separate investigation flag records specific reasons: High tier, unapproved status, documented training permission, documented absence of admin controls, or insufficient evidence for any tier. A department name, SSO unknown, or any other single missing field does not itself trigger the flag. If two contexts have the same applicable facts, they may legitimately have the same tier; do not infer data sensitivity from department or bytes uploaded.
- **Every** tier and flag retains the Usage Context, policy/rule version, triggered factor and reason codes, typed references to supporting activity, synthetic policy and vendor evidence, and material unknowns. An unresolved assessment explains missing evidence. Jev may interpret supplied text with its source and model version retained, but neither its output nor a framework citation proves a vendor claim or substitutes for the rule explanation. These tiers are project-policy assessments, not safety, incident, or compliance determinations.

### Jev exploration — Provisional

Explore TypeSafe AI's Jev for bounded judgments about ambiguous, source-dated vendor or governance text supplied with the synthetic data (for example, whether a training-use claim is yes, no, conditional, or not stated). Compare its outputs with reviewed examples; retain the source reference and treat uncertain or unsupported judgments as unknown. This is an experiment, not a committed dependency or a source of verified vendor facts. Jev does not assign the final risk tier or generate its explanation: versioned deterministic rules produce the tier, reasons, and evidence references, which the assistant may explain. Exact fields, prompts, thresholds, and whether Jev adds value remain deferred.

## Evidence and citation-ready provenance — Confirmed

- Retain immutable uploaded/source artifacts and run-pinned Dataset B snapshots. For cited external vendor and governance material, retain the specific excerpt used, source identity and URL, publication/version when known, capture date, and precise available passage locator. Do not archive whole websites by default or invent missing source metadata. A source reference establishes origin and scope, not the truth or applicability of its claim.
- Each material derived result retains typed links to the actual source records, excerpts, and preceding decisions it used, with their explicit evidence roles and relevant model, registry, decision-policy, and risk-rule versions. Activity Events remain Batch-qualified; candidates, identity and classification results, Usage Contexts, and assessments are tied to the producing Analysis Run. Preserve source material once rather than copying it into every result or reconstructing historical lineage later. Exact IDs and storage shapes remain implementation decisions.
- Dashboard and assistant citations pin a specific Analysis Run and result, never a moving latest-result pointer. A later re-analysis may be offered separately without changing an older citation. Explanations trace claims through the recorded decisions to their inputs: observation does not prove content submission, model output does not prove ground truth, framework passages do not establish vendor or organizational facts, and synthetic Policy Status is not Cyera policy.
- Preserve conflicting vendor sources and their dates/applicability; do not automatically prefer the newest. If material applicability or verification is unresolved, the fact remains unknown rather than silently driving a rule. Retain relevant unknowns and source limitations in the explanation.
- Aggregate counts and trends come from deterministic queries. Cite the contributing Runs, event-time range, filter and count definition, with drill-down to included records; do not rely on LLM estimates, a Run ID alone, or hundreds of inline event citations. Exact query representation and presentation belong to persistence, API, dashboard, and assistant design.

## Application experience

### Dashboard — Confirmed

The Next.js dashboard is limited to the vision's investigation needs and retained team choices. Its analysis views are read-only; Batch upload and explicit re-analysis are the only user-initiated writes. Classifications, risk results, policy, and approval status cannot be edited in the application:

```text
Dashboard
├── Batch ingestion and validation result
├── Overview: adoption trends, departments, risk distribution
├── Tool inventory with required filters
├── Tool/Usage Context detail with confidence, risk factors, and evidence
└── Conversational governance assistant across the stored Batch history
```

Evaluation reports and model-development plots belong in notebooks or documentation rather than an additional application screen.

The application has no review workflow, approval chain, user management, notifications, enforcement integration, or automatic retraining.

### Dashboard interaction and information contract — Confirmed

- **Hierarchy and scope:** Present an all-Batch overview, then a dedicated Batch dashboard, then application/Usage Context detail. The broad overview leads with findings, followed by a Batch directory and a visible data-coverage/limitations area. Each Batch contributes its latest successful Analysis Run. Disclose overlapping activity, Batch-scoped observed identities, and material model/rule version differences; these disclosures supplement, rather than replace, precise metric labels. Cross-Batch activity remains counted as supplied, without automatic deduplication or identity merging beyond confirmed known Tools.
- **Headline and supporting findings:** Headline distinct confirmed known AI Tools observed, AI-positive Activity Events, Activity Events with unresolved AI status, and Usage Contexts needing investigation. Distinguish AI-positive activity associated with resolved Tools from activity associated with unresolved identity. Count additional resolved AI-positive observed Tools separately by Batch in the inventory summary, never as organization-wide unique Tools. Supporting panels show contextual-risk distribution and stage-specific identity, AI, and Category unresolved findings; overlapping stage counts are not summed into one unresolved total. Investigation counts use the stored flag, including unresolved assessments, rather than only High-tier contexts. Presentation and headline selection may be revisited after stakeholder feedback without weakening the counting or provenance contracts.
- **Time and shared filters:** Initially show all available event-time activity and its actual date range, with shared event-date, department, and Batch filters. Upload time is not activity time. Filters select matching activity and existing Usage Contexts with matching events; they never edit, recalculate, or republish assessments. Show each selected context's stored assessment with its original Batch-period scope, distinguishing filtered activity from the assessment's full scope.
- **Charts and aggregates:** Use simple event-count trends and department/Category bars for AI-positive Activity Events, with unresolved Category explicitly separated. Contextual-risk bars count Usage Contexts with High, Medium, Lower, or unresolved assessment outcomes. Use adaptive trend buckets appropriate to the displayed range, explicit counting definitions and available activity coverage; gaps are not interpreted as zero usage. Pair colors with accessible text labels; Lower does not mean safe. Aggregates retain contributing Runs, event-time range, filter/count definition, and drill-down to included records.
- **Batch dashboard and inventory:** Lead the Batch dashboard with Batch/Run context and summary findings, then discovery, trends, department/Category and contextual-risk breakdowns, with a prominent route to flagged contexts. Use one inventory labeled “Observed applications,” defaulting to AI-positive findings but retaining non-AI and unresolved results. Clearly distinguish resolved Tools from unresolved Tool Candidates and separate identity from AI/Category outcomes. Application rows summarize activity, departments, risk-outcome counts, and flagged contexts; no global Tool risk badge is assigned.
- **Investigation filters:** Provide application name/domain search, identity outcome, AI status, Category including unresolved/inapplicable, department, Policy Status including unknown, contextual-risk outcome, and investigation flag. Risk/flag filters select applications with matching contexts and explicitly identify those contexts. Model confidence and vendor attributes are inspectable in detail, not additional initial filters; raw scores are not presented as comparable calibrated confidence.
- **Detail and evidence:** Use one sectioned application detail page for identity and AI/Category determinations, observed activity, and individual Usage Contexts. Expand contexts to inspect their stored assessments, factors, reason codes, unknowns, and evidence. Unresolved candidates show applicable determinations and abstention reasons, not invented contexts or tiers. Link evidence beside the finding it supports, with expandable source records or retained excerpts, source identity, dates, applicability, role, and relevant versions. Distinguish observations, model outputs, synthetic policy, vendor claims, and governance guidance.
- **States and historical navigation:** No Batches prompts upload; invalid uploads show row-specific errors without creating a Batch; running shows waiting without partial findings. A failed Run without a prior success shows a safe failure summary and no findings; with a prior success, keep those results visible and disclose the newer failure. No filter matches explains the active filters and offers to clear them. Unresolved findings remain normal results with reasons, not execution-error screens. Display Batch identity, producing Run, activity period, and relevant versions. Provide Batch Run history/selection for older successful Runs with a clear historical label; failed attempts expose safe diagnostics rather than findings. Links preserve their selected/producing Run. The overview continues to select latest successes; no side-by-side Run comparison is required.

This contract specifies the read-only investigation experience without changing the confirmed upload/re-analysis lifecycle. API shapes and assistant retrieval/response behavior remain with their separate decisions; no new product workflow is introduced.

### Upload execution — Confirmed

A new valid upload automatically creates a Batch and synchronously executes one Analysis Run using the model artifacts and risk rules configured when FastAPI starts. An invalid upload displays validation errors and creates no analyzable Batch. A byte-identical upload reopens the existing Batch without starting another run; re-analysis is explicit. If analysis fails, preserve the Batch and record the Analysis Run as failed. Add background status polling only if representative runtime approaches request timeouts or produces an unacceptable waiting experience; no queue infrastructure is planned.

### Local data lifecycle — Confirmed

- Uploaded Batch files, SQLite records, and analysis results persist across application restarts.
- A byte-identical upload is detected by SHA-256 checksum and reuses the existing Batch rather than creating a duplicate or failing.
- A developer may explicitly create a new Analysis Run for an existing Batch when models or risk rules change.
- A documented developer reset command removes generated uploads and SQLite state while preserving source datasets, migrations, fixtures, and model artifacts.
- No end-user deletion UI is planned.

### RAG governance-assistant contract — Confirmed; implementation details deferred

The conversational assistant answers governance questions across the stored database of Batches, not only a selected Batch. It supports general questions about departments, unapproved or high-risk AI Tools, newly observed applications, specific risk explanations, and trends; selected-Batch chat is a stretch goal. Database-wide context means querying and retrieving relevant stored evidence, not placing the entire database in an LLM prompt. General answers use the latest successful Analysis Run for each Batch, citing that Run and disclosing material model/rule version differences; failed Runs do not replace earlier successful results. Cross-Batch Tool aggregation uses only confirmed known-Tool identities; unknown observed Tools remain Batch-scoped, with matching locators reported only as clues rather than asserted identity. Cross-Batch activity counts include each Batch's events as supplied, without automatic deduplication. For generated fixtures, matching `event_id` and identical event data across Batches produce an exact-overlap warning with both Batch/event references; matching IDs with differing event data produce a conflicting-ID warning, not a proven duplicate. These are non-blocking warnings, and database-wide counts disclose overlap rather than silently implying deduplicated activity. Event references remain Batch-qualified even though generated IDs are cross-file stable. It must:

- report detected AI-tool usage and previously unseen or unresolved tools;
- surface potentially high-risk or unapproved Usage Contexts;
- explain stored classifications, confidence, deterministic risk factors, reason codes, policy status, and missing evidence without implying that the LLM made those decisions;
- summarize adoption and risk patterns across Batches using explicit event-time ranges and traceable Analysis Runs;
- connect findings to retrieved project-policy and governance evidence;
- support follow-up questions using the relevant conversation context.

Structured counts, filters, and trends come from deterministic database queries rather than estimates over retrieved text. Semantic retrieval finds controlled local Tool, Usage Context, Analysis Run, risk, project-policy, and governance evidence. The LLM composes grounded answers and abstains when material evidence is insufficient.

Traceability is a primary response requirement. Answers identify the supporting records, rule reasons, and governance passages so users can inspect why a statement was made. Data-labeling, classification, risk-scoring, and governance contracts must preserve stable evidence references and provenance that the assistant can cite; concrete schemas remain deferred to implementation planning.

The assistant does not independently discover or classify tools, determine or override risk tiers, browse the live web, execute arbitrary SQL, modify state, approve tools, or enforce policy.

Corpus formatting and chunking, embedding model and vector index, retrieval depth, reranking, LLM provider and prompt, conversational-context implementation, and retrieval/response-quality evaluation details are deferred to the RAG phase.

## Batch and Analysis Run — Confirmed

A **Batch** is one immutable uploaded dataset. An **Analysis Run** is one execution of a particular pipeline and risk-rule version against a Batch.

```text
Batch A
├── Run 1 · models v1 · risk rules v1
├── Run 2 · models v2 · risk rules v1
└── Run 3 · models v2 · risk rules v2
```

### Batch metadata

- batch ID;
- original filename and raw artifact path;
- SHA-256 checksum;
- schema version;
- upload time;
- activity time range;
- event count;
- validation status.

The checksum detects identical uploads and verifies the raw bytes used for a run. It is not a digital signature or data-quality guarantee.

### Analysis Run metadata

- run ID and batch ID;
- start, completion, and status;
- AI-detector version;
- category-model version;
- risk-rule version;
- code commit.

Model and rule versions belong to the Analysis Run rather than the Batch so the same input can be reprocessed without mutation.

### Lifecycle decisions — Confirmed so far

- Only a complete, successful Analysis Run publishes results to dashboard and assistant queries. A failed Run retains its failure record and diagnostics, but its partial outputs are not analyst-facing results; the prior successful Run for the Batch remains usable.
- Every accepted explicit re-analysis creates a distinct Analysis Run, even if configured versions have not changed; it never mutates an earlier Run. No re-analysis idempotency key is needed: a repeated explicit request after completion creates another Run. Byte-identical uploads still reopen the existing Batch without starting a Run.
- The synchronous Run lifecycle is `running → succeeded | failed`, with the running record persisted before analysis starts. There are no queued, partial-success, or cancelled states in the initial flow.
- A failed Run persistently records a safe failure summary, failed phase, and failure time. Detailed traces remain in server logs; failure records do not expose raw uploaded input. On application startup, a Run left `running` by an interrupted process becomes `failed` with an interruption reason and an unknown phase when the phase was not durably recorded; it is not resumed automatically.
- Incomplete derived outputs from failed Runs are discarded; the immutable Batch and failure record remain. Only complete successful Runs are queryable as results.
- At most one Run may be `running` for a Batch. Another attempt for that Batch is rejected while it runs; there is no upload or Run queue. Other Batches are not blocked by this rule.
- Once started, a Run continues while the server is alive even if its HTTP client disconnects; its persisted outcome can be reopened from the Batch. A server interruption follows the startup failure rule rather than implying completion.
- No application-level size or execution-time cutoff is planned. Ordinary request/runtime limits still exist; revisit synchronous waiting or background status polling only if representative Runs encounter timeouts or an unacceptable wait. No queue is planned.
- The initial local server uses one FastAPI process. Different Batches may still execute concurrently within it; multi-process Run ownership and recovery are unsupported until a concrete need justifies coordination.

## Persistence and versioning — Confirmed

- Preserve each immutable uploaded file as the Batch's original artifact. A raw-byte SHA-256 identifies byte-identical uploads for Batch reuse; the Batch retains its own stable ID. Store validated, normalized Activity Events once in SQLite for queries and drill-down, uniquely referenced by Batch ID plus supplied `event_id`. Re-analysis reuses these records rather than duplicating events per Run.
- Retain known Tool identities through the authoritative versioned registry. Persist observed Tool identities within their Batch and reuse one across Runs only when its identity evidence remains unambiguous; changed or conflicting evidence must not silently redefine an old identity. Neither matching locators nor observed IDs establish identity across Batches. Tool Candidates and identity, AI, and Category decisions are tied to their producing Run; candidate and Usage Context grouping identities are unique within that Run, not global identities.
- Each accepted execution has its own Run ID even when Batch and versions repeat. Store queryable Run-scoped decisions, semantic-neighbor results, Usage Contexts, contextual assessments, unresolved outcomes, and typed links to the actual source records and preceding decisions used. Retain shared evidence once rather than copying it into every result. Only a complete successful Run exposes derived findings; failure retains its Run record but no published partial results, as specified by the lifecycle contract.
- Store bounded cited excerpts with their source identity, available version/date and passage locator in SQLite; retain substantial immutable uploads, Dataset B snapshots, model bundles, and other file-backed versioned inputs as local files. Each Run pins the metadata snapshot by path and SHA-256 and records the applicable registry/partition, model, decision-policy, retrieval, risk-rule, and code versions and references it used. Keep referenced historical versions available rather than overwriting them; this preserves inspectable inputs without promising bit-for-bit reproduction across environments. Do not archive whole external sites by default.
- General views derive each Batch's latest successful Run from persisted Run history; failed Runs cannot replace a prior success. Historical citations name the specific producing Run and result, never this moving selection. No mutable current-Run pointer or per-Run event copies are needed.

Exact tables, constraints beyond these logical identities, transactional publication, file layout, API shapes, and UI presentation remain implementation decisions.

## Technical architecture — Confirmed

### Local-first prototype baseline

```text
Next.js + TypeScript
        ↓ HTTP
FastAPI + Python
        ↓
SQLite + local uploaded files + local model artifacts
```

- Next.js owns dashboard and chat presentation.
- FastAPI owns validation, ingestion, inference, risk rules, retrieval, and database access.
- Next.js never accesses SQLite directly.
- The generated SQLite database is local state; developers share migrations, source data, and deterministic fixtures rather than committing database files.
- No Supabase, authentication, hosted persistence, multi-user isolation, or public deployment is required.
- Hosted deployment may be reconsidered only after the local prototype baseline is complete.

### Repository boundary — Confirmed

Use one monorepo containing the application, model-development work, data, artifacts, and documentation:

```text
/
├── frontend/          # Next.js and TypeScript dashboard
├── backend/           # FastAPI, inference, risk, and storage
├── notebooks/         # EDA and offline model experiments
├── data/              # source and synthetic datasets
├── artifacts/         # generated local model bundles
├── approaches.md      # model experiment ledger
├── PROJECT_PLAN.md    # confirmed planning decisions
└── README.md          # setup, results, and final documentation
```

Keep this layout shallow: no monorepo workspace framework or shared package layer unless a concrete need appears.

### `approaches.md` responsibility — Confirmed

Keep the existing comparison table. During model development, extend the file into an experiment and promotion ledger organized around binary AI detection, 14-category classification, and novel-tool retrieval. It does not replace this overall project plan, and detailed model choices remain deferred.

### Offline training and application inference — Confirmed

Models train offline. The application only loads versioned artifacts and runs inference. Replacing a model changes configuration/artifacts, not application code.

Separate artifacts own binary AI detection and 14-category classification.

A minimal model bundle contains:

- fitted preprocessing and model artifact;
- model ID and task;
- dataset version;
- label set;
- creation time;
- code commit;
- recorded evaluation metrics.

The stable inference result is label, confidence, and model ID. Exact serialization and algorithms are deferred to model development.

## Evaluation policy — Confirmed

Do not chase an arbitrary universal score.

- Every nontrivial model must beat relevant trivial and simple baselines on leakage-resistant evaluation.
- Freeze the final test set before final model selection.
- Use training/validation data for iteration and threshold selection.
- Report per-class behavior, support, uncertainty, and limitations.
- Evaluate known and unseen tools separately.
- Choose operational thresholds only after evidence or advisor guidance and before final test evaluation.
- A required capability must work end to end, not only in an isolated notebook.
- A timed manual-effort comparison is entirely optional. If performed, compare fixed governance tasks manually and with the prototype, including time, records inspected, and correctness or completeness; label the result as a limited project simulation, not proven real-world savings.

## Bias and fairness boundary — Confirmed

Evaluate bias where it is supported by the data:

- common versus rare categories;
- complete versus sparse descriptions;
- known versus unseen tools;
- active versus inactive tools;
- review/error burden across synthetic departments and scenarios;
- representation limitations in AIToolBuzz.

Do not invent demographic attributes or claim demographic fairness without appropriate data. Never rank individual employees by risk.

## Explicitly out of scope

- Real-time monitoring or automated enforcement
- Production enterprise connectors
- Live web crawling
- Authentication or multi-user authorization
- Hosted infrastructure before the baseline is complete
- End-user review and approval workflows or annotation platforms; offline human verification, gold-label adjudication, and evaluation review remain permitted
- Full-catalog manual labeling
- Automatic retraining from application activity
- Runtime model-selection UI
- Microservices, queues, streaming infrastructure, or Kubernetes
- Formal NIST, OWASP, ISO, or regulatory compliance claims
- Demographic fairness claims unsupported by available data
- Arbitrary model complexity not justified by evaluation

## Deferred decisions

### Challenge Advisor inputs — Confirmed

The Challenge Advisor accepted the synthetic activity approach without added scale or validation targets, confirmed fully fictional employee data and optional Dataset C, supplied no organization policy example, accepted a local-only demo and the full `VISION.md` end-to-end flow, and left cross-Batch chat scope to the team. External LLM/embedding services are permitted without additional Advisor restrictions; provider selection and prompts remain deferred to the RAG phase. Local-only presentation does not imply offline operation. These are answers relayed by a project member, not a verbatim Advisor transcript.

### Model-development phase (`approaches.md`)

- Binary negative-set construction and final size
- Train/validation/test ratios
- Class weighting and resampling
- Calibration and abstention thresholds
- Exact feature sets
- Algorithm comparison and promotion criteria
- Model serialization format

### RAG phase

- Corpus and chunking
- Embedding model
- Retrieval benchmark
- Whether reranking is justified
- LLM provider and prompting
- Citation and groundedness evaluation

### Implementation planning

- Final synthetic input schema
- Database schema and migrations
- FastAPI endpoints
- Next.js page/component structure
- Exact risk dimensions and rules
- Detailed module/file layout and development commands
