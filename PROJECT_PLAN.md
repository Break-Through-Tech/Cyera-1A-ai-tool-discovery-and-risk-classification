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

## Risk assessment

### Assessment unit — Confirmed

Risk belongs to a **Usage Context**, not globally to a Tool and not independently to every raw event:

```text
Tool + department + purpose + data sensitivity + time window
    → contextual assessment
```

The same Tool may have different assessments in different contexts.

## Application experience

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
