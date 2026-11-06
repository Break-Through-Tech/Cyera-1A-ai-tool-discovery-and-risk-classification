# Governance-agent integration

## Phase 1: shared contracts

Implemented in `backend/app/assistant/contracts.py`. These are internal integration
contracts, not published HTTP endpoints. Phase 2 adds persistence below. There is
no running agent, Gemini call, LangGraph workflow, or retrieval implementation.

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

## Phase 2: durable trace storage

`backend/app/assistant/store.py` stores turns, completed execution receipts, and
evidence snapshots in SQLite. Migration `0005` adds `assistant_turns`,
`assistant_steps`, and `assistant_evidence` without changing analysis data.

| Function | Behavior |
|---|---|
| `start_turn` | Check that pinned Runs exist, succeeded, and belong to the named Batches. Store the question, scope, model ID, and prompt version. |
| `append_step` | Atomically append a completed receipt and its evidence snapshots. Require the exact turn scope and contiguous sequence numbers. |
| `finish_turn` | Validate answer references against persisted evidence. Reject changed scope or any failed tool execution, then finalize the turn. |
| `fail_turn` | Finalize with a safe failure and no substantive answer. Preserve earlier receipts and evidence. |
| `get_turn` | Read a turn and its final answer or failure. |
| `list_steps` | Read ordered receipts with pagination and a total count. |
| `get_evidence` | Resolve a turn-qualified evidence ID to its stored source and producing step. |
| `fail_interrupted_turns` | Fail abandoned running turns before a single server process accepts work. No startup hook invokes this function yet. |

Database transactions make each write atomic. A no-op write obtains SQLite's
writer lock before an append or finalization reads the current state. This
prevents an append from racing past finalization. Exact receipt retries are
no-ops, including after finalization. Changed receipts and new writes to terminal
turns fail. These rules apply through the store API, not to arbitrary SQL access.

Evidence IDs are unique within a turn. Different steps must issue different IDs,
even when they refer to the same underlying source. A composite foreign key links
each retained source to its producing step in the same turn. Reusing an evidence
ID rolls back the entire new step without replacing the original evidence.

The store serializes JSON snapshots, so subsequent changes to in-memory objects
do not change retained data. Reads work after reopening the database, independently
of chat history. New Analysis Runs do not replace a stored turn's scope.

These functions accept trusted backend calls. They do not enforce user access,
resolve record or passage existence, verify claim support, redact arbitrary input,
or enforce tool result-size budgets. Those checks belong at the service and
integration boundaries before persistence. No public inspection endpoints exist
yet. The caller supplies the model ID and prompt version. Gemini response metadata
is not available until the provider integration exists.

Only completed tool attempts are recorded in this phase. A crash during a tool
call leaves a running turn without a completed receipt for that call. Recording
in-flight operations and wiring interrupted-turn cleanup belong to orchestration.
Clarification and complete abstention response types also remain deferred.

## Next phases, each with a review stop

1. Add tool dispatch and LangGraph orchestration with test-only integrations.
2. Connect Gemini through `google-genai`; record model and prompt versions.
3. Connect the team's query and RAG implementations and expose inspection APIs.
4. Verify real analyst journeys, trace drilldown, source resolution, and claim support.

Generated Python remains disabled until the ADR's complete dataset, isolation,
artifact, provenance, and bounded-repair path exists. No Python worker is part of
this initial implementation.

## Verify the implemented phases

From the repository root:

```sh
backend/.venv/bin/python -m pytest backend/tests/test_assistant_contracts.py backend/tests/test_assistant_store.py -q
```

These tests verify contracts, database persistence, transactions, and migration
behavior. They do not establish real model, retrieval, worker isolation, or
end-to-end analyst behavior.
