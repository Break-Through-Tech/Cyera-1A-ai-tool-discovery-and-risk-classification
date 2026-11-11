# Governance-agent integration

## Phase 1: shared contracts

Implemented in `backend/app/assistant/contracts.py`. These are internal integration
contracts, not published HTTP endpoints. Phases 2 through 4 add persistence,
LangGraph orchestration, and a Gemini adapter. There is no production query
adapter or retrieval implementation yet.

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
yet. The caller supplies the model ID and prompt version. Phase 4 adds retained
Gemini execution metadata.

Only completed tool attempts are stored. Graceful cancellation records a failed
tool receipt when a tool was in progress. A hard process crash can still leave a
running turn without a receipt for that call. Startup marks the turn interrupted,
but does not reconstruct or resume the missing operation. In-flight tool records
remain future work. Model requests have in-flight records from Phase 4 onward.
Startup cleanup assumes one server process and must
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

`integrations.py` defines the async `AgentModel` interface. Its `ModelResult`
contains one structured `ToolCall`, `AnswerDecision`, or `StopDecision`, plus safe
provider metadata. It cannot supply a new scope or execution receipt. `prompts.py` supplies the instructions and recorded
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
`unfinished_work` list. A blocked follow-up identifies the tool that did not run.
A final supported answer is allowed after the last permitted tool call. Timeouts during a model or tool request fail the turn. Adapters must use
cancellable async I/O. Deadlines reject late results but do not isolate CPU work,
kill threads, or impose hard memory limits.

Completed tool attempts are persisted before their results reach the model.
Invalid tool requests fail before execution and do not create a completed tool
receipt. Provider failures, invalid decisions, tool failures, and broken citations
produce safe failed turns without substantive partial answers. Unexpected workflow
or storage errors propagate to the caller after failure recording when possible.
There is no fallback to model memory. Model-decision bodies are not persisted.
Phase 4 retains provider usage and model-call timestamps.

The store accepts older Phase 2 answer JSON without a `kind` field. No new database
migration is needed for the limited-response variant.

## Phase 4: Gemini and model-call metadata

`model.py` implements `AgentModel` with the `google-genai` SDK and the Gemini
Developer API. It does not enable Vertex AI, enterprise routing, browsing, code
execution, or SDK-managed application function execution.

### Configuration

Environment variables override values in the repository-root `.env` file.
An explicitly empty `GEMINI_MODEL` disables the provider, even if `.env` selects one.
The application does not choose a default model.

| Variable | Default | Meaning |
|---|---|---|
| `GEMINI_API_KEY` | Unset | Developer API credential, excluded from settings representations |
| `GEMINI_MODEL` | Unset | Explicit `gemini-...` or `models/gemini-...` model ID |
| `GEMINI_TIMEOUT_SECONDS` | `30` | SDK request timeout, also bounded by the workflow deadline |
| `GEMINI_MAX_OUTPUT_TOKENS` | `4096` | Generation output-token limit |

A key without a model leaves the provider disabled. A selected model without a
key fails startup. Other Google authentication environment variables do not
substitute for this configuration. Normal production requests use the fixed
`https://generativelanguage.googleapis.com` endpoint with API version `v1beta`.

FastAPI lifespan creates `app.state.assistant_model` when configured and closes
the SDK clients at shutdown. This does not register query handlers or expose an
assistant HTTP endpoint. Internal callers can construct
`Assistant(engine, app.state.assistant_model, ToolRegistry(handlers))` after startup.
The model must be present before constructing the workflow. The adapter owns its
SDK client. Tests that inject an SDK client with an externally owned HTTP client
also close that HTTP client explicitly.

### Native function calling

Each request supplies connected backend tool declarations and two response-only
functions, `return_findings` and `stop_investigation`. The SDK receives declarations,
not Python handlers. Native function-calling mode is `ANY`, with automatic function
execution disabled and one candidate requested. Tool declarations are omitted
when the workflow's tool budget is exhausted. The two response-only functions
remain available.

The adapter accepts exactly one visible function call. It rejects parallel calls,
unknown names, free-text answers, blocked responses, incomplete generations, and
malformed terminal arguments. LangGraph still validates operation arguments,
executes requested backend tools, and validates final citation references. No SDK
response can mark a backend tool as executed or replace the pinned scope.

Every request is a fresh decision over the bounded scope and observations. There
is no provider-managed conversation, implicit replay of earlier tool calls, or
stored thought-signature history. Thought parts are omitted from decisions and
metadata. The request uses temperature `0`, but that does not prove determinism
or groundedness. SDK HTTP retries are disabled with one total attempt, so provider
retries do not silently exceed the workflow's model-attempt budget.

### Durable model-call records

Migration `0006` adds `assistant_model_calls`. The workflow records a running call
before awaiting the provider. `start_model_call`, `finish_model_call`, and
`list_model_calls` in `store.py` maintain an ordered, turn-qualified trace.

The records retain:

- Provider and requested model, backend start and completion timestamps, and status.
- SHA-256 of the validated provider-independent `DecisionContext`. This is not a
  hash of the SDK's final HTTP request bytes.
- SDK version, adapter version, API version, temperature, configured token limit,
  timeout, and retry-attempt limit.
- Provider-reported model version, response ID, finish reason, prompt block reason,
  and HTTP error status when available.
- Reported prompt, output, thought, cached, and total token counts. Missing counts
  remain unknown rather than becoming zero. These categories can overlap and must
  not be summed to estimate total usage.
- A safe failure code and message when the request fails.

Raw SDK exceptions, provider response bodies, credentials, and thought text are
not stored. The turn still retains its question, and completed tool receipts retain
their bounded arguments and results as in earlier phases. Model-call records do
not retain raw proposed decision bodies, so they are not full response replays.
Base prompt version is stored on the turn; `gemini-native-functions-v1` identifies
the adapter's additional instructions and function-declaration format.

Model calls must have successful predecessors and cannot be rewritten after
completion. A failed or unfinished call prevents a successful final response.
Cancellation or startup cleanup marks an in-flight model call failed together
with its turn. Cleanup does not imply that a cancelled request was unbilled or
that the provider performed no computation.

The trace records execution and reported usage. It does not prove citation
relevance, correct computation, or supported interpretation.

### Verification boundary

Tests use the real SDK's request serialization and response parsing with an HTTP
mock transport. A complete test path covers SDK function request, LangGraph tool
execution, SDK answer generation, and persisted citation and model-call records.
Configuration tests also exercise actual SDK client creation and shutdown without
sending requests. This verifies integration behavior, not live Gemini behavior.

Live acceptance requires an explicitly selected, accessible `GEMINI_MODEL` and a
real request. Mocked responses cannot establish model availability, server-side
schema acceptance, response quality, or resistance to prompt injection. Live
validation remains pending; `.env` credentials are not changed by these tests.

References: [Google Gen AI Python SDK](https://googleapis.github.io/python-genai/)
and [Gemini function calling](https://ai.google.dev/gemini-api/docs/function-calling).

## Next phases, each with a review stop

1. Connect the team's query and RAG implementations and expose inspection APIs.
2. Verify real analyst journeys, trace drilldown, source resolution, and claim support.

Generated Python remains disabled until the ADR's complete dataset, isolation,
artifact, provenance, and bounded-repair path exists. No Python worker is part of
this initial implementation.

## Verify the implemented phases

From the repository root:

```sh
backend/.venv/bin/python -m pytest backend/tests/test_assistant_*.py backend/tests/test_gemini_*.py -q
```

These tests exercise LangGraph, migrated SQLite storage, and the Gemini SDK using
scripted responses and fixture tools. They do not establish live model quality,
retrieval quality, source existence, claim support, worker isolation, or end-to-end
analyst behavior.
