# Governance-agent integration

## Phase 1: shared contracts

Implemented in `backend/app/assistant/contracts.py`. These are internal integration
contracts, not published HTTP endpoints. There is no running agent, Gemini call,
LangGraph workflow, persistence, or retrieval implementation in this phase.

The agent consumes backend query operations and the team's RAG service. It does
not own document ingestion, embeddings, indexing, retrieval, or risk calculations.

### Scope

`PinnedScope` carries one explicit Run per contributing Batch, an inclusive-start /
exclusive-end UTC event-time interval, filters, and qualifications. The backend
must resolve the scope before execution and verify that the Runs belong to the
Batches, succeeded, and are authorized. Constructing a scope does not perform any
of those checks. Qualifications carry material overlap, conflict, and version
warnings supplied by the backend.

New general questions will select current successful Runs; historical follow-ups
will retain their original references. That selection behavior is not implemented
yet. Filters use assistant-facing names; integration adapters must map them to
backend operations and reject unsupported combinations rather than drop them.

### Tools and execution records

The initial allowed names are `describe_dataset`, `summarize_usage`,
`compare_usage`, `get_risk_assessments`, `get_evidence`, and `retrieve_context`.
Operation-specific argument and result schemas will be added when the actual
integration interfaces are available. JSON fields are transport containers, not
permission to execute arbitrary arguments or queries.

Each completed `ExecutionStep` records the tool, explicit scope, sequence number,
safe validated arguments, timestamps, and one discriminated outcome:

| Status | Meaning |
|---|---|
| `succeeded`, outcome `data` | Completed operation with bounded structured data |
| `succeeded`, outcome `no_matches` | Valid query with no matching records |
| `limited` | Unavailable capability, unsupported request, or clarification needed |
| `failed` | Execution failure, with safe code and message; no partial result payload |

An unconfigured RAG capability is unavailable. A configured RAG service failing
mid-turn is an execution failure, not an empty search result or successful answer.
The later orchestration phase must enforce that distinction.

Results include evidence and qualifications. Truncated responses must explicitly
qualify the preview; continuation references are optional until the underlying
operation supplies drilldown or pagination. Integrations remain responsible for
size limits and for never presenting previews as the complete population.

Execution receipts must be created by backend code. Never accept model-generated
receipts as proof that a tool ran. Before recording, exclude credentials and raw
internal exceptions from analyst-visible arguments and diagnostics. The models
are frozen at the field level, but embedded JSON dictionaries are not deeply
immutable; persistence must serialize snapshots rather than retain mutable aliases.

### Evidence and findings

Three evidence types retain different authority:

- `RecordEvidence`: Batch-qualified producing Run plus record type and ID.
- `AggregateEvidence`: full scope, reproducible backend query specification,
  metric definitions, and a drilldown reference. The query is not executable SQL.
- `PassageEvidence`: corpus/document versions, passage ID, exact excerpt, and
  source role (`project_policy`, `general_guidance`, or `tool_evidence`).

`GroundedAnswer` separates cited factual claims, interpretation, limitations, and
advisory next steps. A budget-limited answer must disclose unfinished work. These
models cover evidence-backed findings; clarification, unsupported requests,
complete abstention, failed turns, and public response envelopes belong to the
orchestration/API phase. Do not invent findings just to fit this model.

`validate_answer_references` checks unique supplied evidence IDs, cited-ID
membership, record Run membership, and exact aggregate scope matching. It does
not check live source existence, record membership in filters/time ranges,
authorization, or semantic claim support. The service must obtain evidence from
trusted resolvers and perform those separate checks. Aggregate scope matching is
intentionally conservative for now: narrower comparisons need an explicit scope
relationship before they can be cited as part of a broader answer.

The validator is not a hallucination detector. An existing activity record does
not prove sensitive-data submission, and successful schema validation does not
prove an interpretation. Model-authored interpretations and recommendations also
need support review.

### Next phases, each with a review stop

1. Persist execution records and evidence links, independently of chat lifetime.
2. Add tool dispatch and LangGraph orchestration with test-only integrations.
3. Connect Gemini through `google-genai`; record model and prompt versions.
4. Connect the team's query and RAG implementations and expose inspection APIs.
5. Verify real analyst journeys, trace drilldown, source resolution, and claim support.

Generated Python remains disabled until the ADR's complete dataset, isolation,
artifact, provenance, and bounded-repair path exists. No Python worker is part of
this initial implementation.

## Verify this phase

From the repository root:

```sh
backend/.venv/bin/python -m pytest backend/tests/test_assistant_contracts.py -q
```

These tests verify contract behavior and serialization only. They do not establish
real model, retrieval, isolation, or end-to-end analyst behavior.
