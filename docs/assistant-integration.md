# Governance-agent integration

## Phase 1: shared contracts

Implemented in `backend/app/assistant/contracts.py`. These are internal integration
contracts, not published HTTP endpoints. Phases 2 and 3 add persistence and a
LangGraph workflow with injected model and tool interfaces. There is no Gemini
integration, production query adapter, or retrieval implementation yet.

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
`tools.py` defines proposed typed arguments for these operations. Teammate-owned
adapters must implement these contracts or agree on an explicit revision. Result
data remains a bounded JSON object with typed evidence and qualifications. JSON
fields do not authorize arbitrary queries or execution.

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
The workflow enforces that distinction.

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
models cover evidence-backed findings. `LimitedResponse` represents clarification,
unsupported requests, insufficient evidence, or a budget stop without findings.
A completed limited response has turn status `succeeded` and answer kind
`limited_response`, not an execution failure. Public HTTP envelopes remain
undefined. Limited-response wording is not a verified factual finding.

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
| `fail_interrupted_turns` | Fail abandoned running turns before a single server process accepts work. `create_app` invokes this function at startup. |

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

Only completed tool attempts are stored. Graceful cancellation records a failed
tool receipt when a tool was in progress. A hard process crash can still leave a
running turn without a receipt for that call. Startup marks the turn interrupted,
but does not reconstruct or resume the missing operation. Per-call in-flight
records remain future work. Startup cleanup assumes one server process and must
not run while another process is executing turns.

## Phase 3: tool dispatch and LangGraph

`Assistant` in `graph.py` exposes one async entry point:

```python
assistant = Assistant(engine, model, ToolRegistry(handlers), ExecutionLimits())
turn = await assistant.run_turn(question=question, scope=pinned_scope, briefing=True)
```

The caller supplies an already resolved, authorized `PinnedScope`. The workflow
checks Run existence and success through the store, but does not select latest
Runs, resolve conversational references, or authorize the caller. Those operations
remain integration work. A briefing requires exactly one Batch and Run.

The graph has four nodes:

```text
briefing -> decide -> execute -> decide ... -> finalize
```

The `briefing` node runs `describe_dataset`, department-grouped `summarize_usage`,
and `get_risk_assessments` before the model's first decision. Question turns skip
those standard calls. Missing briefing capabilities return an explicit limitation,
not a synthetic briefing. Actual summary completeness needs evaluation with the
real backend implementations.

`integrations.py` defines the async `AgentModel` interface. Its model returns one
structured `ToolCall`, `AnswerDecision`, or `StopDecision`. It cannot supply a new
scope or execution receipt. `prompts.py` supplies the instructions and recorded
prompt version. Tests use scripted model responses. No production fake model or
fake retrieval implementation is registered.

`ToolRegistry` supplies model-visible argument schemas only for connected tools.
It rejects unknown arguments and validates comparison periods against the pinned
time interval. Handlers receive the backend's scope separately from parsed tool
arguments. They must enforce every filter, reference, and continuation token
against that scope. The registry validates results, rejects out-of-scope Run
references, and prefixes local evidence IDs with the producing step ID. Source
record, document, and passage identities remain unchanged. JSON payloads that
contain evidence IDs must use the typed evidence list for citations, rather than
rely on embedded local IDs.

Tool arguments and results have byte limits. Results and model outputs are not
silently truncated. Oversized or invalid results fail the turn. The model receives
bounded observations and a deep copy so it cannot mutate the workflow's evidence.
Scope warnings, tool qualifications, and unavailable-operation messages are
carried into final response limitations. These are structural checks, not proof
that an interpretation follows from the evidence.

`ExecutionLimits` bounds model attempts, tool attempts, elapsed execution time,
argument bytes, tool-result bytes, model-output bytes, and context bytes. Defaults
are configurable implementation choices, not evaluated quality targets. The
budget covers standard summaries and follow-up investigations together. Exhaustion
between calls returns `LimitedResponse(reason="budget_reached")` with an explicit
`unfinished_work` list. A blocked follow-up identifies the tool that did not run. A final supported answer is allowed after the last permitted tool
call. Timeouts during a model or tool request fail the turn. Adapters must use
cancellable async I/O. Deadlines reject late results but do not isolate CPU work,
kill threads, or impose hard memory limits.

Completed tool attempts are persisted before their results reach the model.
Invalid tool requests fail before execution and do not create a completed tool
receipt. Provider failures, invalid decisions, tool failures, and broken citations
produce safe failed turns without substantive partial answers. Unexpected workflow
or storage errors propagate to the caller after failure recording when possible.
There is no fallback to model memory. Model-decision bodies, provider usage, and
per-call model timestamps are not persisted yet.

The store accepts older Phase 2 answer JSON without a `kind` field. No new database
migration is needed for the limited-response variant.

## Next phases, each with a review stop

1. Connect Gemini through `google-genai` and record provider execution metadata.
2. Connect the team's query and RAG implementations and expose inspection APIs.
3. Verify real analyst journeys, trace drilldown, source resolution, and claim support.

Generated Python remains disabled until the ADR's complete dataset, isolation,
artifact, provenance, and bounded-repair path exists. No Python worker is part of
this initial implementation.

## Verify the implemented phases

From the repository root:

```sh
backend/.venv/bin/python -m pytest backend/tests/test_assistant_*.py -q
```

These tests exercise the real LangGraph runtime and migrated SQLite store with
scripted model responses and fixture tool results. They do not establish real
model quality, retrieval quality, source existence, claim support, worker
isolation, or end-to-end analyst behavior.
