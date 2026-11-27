# Proposed docs-only backend integration

This guide targets upstream revision
`d271c83de9b9bf222546612f9bb66fd108ce247c`. The prototype is
unregistered. The integration below requires team approval and a backend
checkout with the approved dependencies.

## Registration and lifecycle

1. Initialize one `RetrievalService` per approved backend process or
   retrieval worker, using a pinned, locally available MiniLM model and an
   approved cache directory. Keep the SentenceTransformers/PyTorch runtime
   separate from the team lock until compatibility and deployment are
   approved. The team Category neighbor index uses a different model and
   cannot provide MiniLM vectors. Recreate the service when the authorized
   snapshot changes. The current resolver cannot serve older snapshots.
2. Inject the actual upstream contracts, tools, and evidence modules into
   `BackendModules`. Pass matching argument and result limits to
   `BackendRetrievalAdapter` and `Assistant`. Extend
   `build_tool_registry` to optionally register the adapter as
   `retrieve_context`. Unconfigured retrieval remains unavailable.
3. Approve the scope and inspection checks before wiring either callback.
   The host authenticates callers, resolves the pinned Batch/Run scope,
   and authorizes documentation retrieval and any external disclosure.
   The callbacks must be fast local checks. Shared project documentation
   cannot establish employee activity, policy approval, or a stored risk
   assessment. Both adapter paths deny by default.
4. Configure the same retained snapshot as
   `EvidenceSources(passages=adapter.resolve_passage)` for internal
   `get_evidence` and, if separately approved, `/evidence/resolve`.
   Keep the team's existing Tool metadata and query handlers. The resolver
   checks the corpus, document version, and exact chunk ID. A change in
   authorization or retention policy must apply to inspection as well as
   retrieval.

CPU work runs in a thread with one active dispatch per service. A timeout
or cancelled await does not interrupt running CPU work. Capacity stays
occupied until the worker exits, so callers may receive `retrieval_busy`.
The upstream turn deadline remains in force. The adapter fits serialized
UTF-8 bytes against the configured limit, including evidence namespace
headroom. It drops complete lower-ranked passages and discloses
truncation. It preserves canonical excerpts and references.

## Known upstream gap

At the audited revision, `QueryTools.get_evidence` parses a step-prefixed
passage reference and calls `resolve_evidence`. The passage branch forwards
the reference to the configured resolver. A successful `get_evidence`
response includes the excerpt in `data.resolved` and excludes it from
`evidence` because the citation tuple explicitly filters out
`PassageReference` items. The isolated verifier reproduced this and showed
that `validate_answer_references` cannot cite that lookup from its empty
typed evidence tuple alone.

**Proposed minimal backend fix:** In the existing bounded page builder
in `QueryTools.get_evidence`, emit `PassageEvidence` for each shown
passage from the trusted resolver's reference, source role, and canonical
excerpt. Use the existing unprefixed passage reference key as the local
evidence ID so the registry can add the current step prefix. Preserve the
record-citation path and budget fitting. Add a backend test that reopens a
passage in a second step and cites the new typed ID. No backend fix is
installed by the independent prototype.

## Verification and remaining deployment work

| Check | Status |
| --- | --- |
| Independent unit tests | Passed, including denied access, overload, timeout/cancellation, worker failure, and byte-budget truncation |
| Actual upstream contract conformance | Passed using exact Git blob hashes and installed Pydantic |
| Scripted model contract and actual registry | Passed with a scripted tool request and answer decision, the real CPU `docs_only` retriever, and actual citation validation |
| Actual passage resolution branch and `get_evidence` | Passed at the component boundary with an isolated resolver and injected verified-read fixture. Reproduced the typed-passage omission. |
| Actual LangGraph workflow and persistence | Blocked. The available Python environments lack LangGraph, SQLAlchemy, and Alembic. No backend virtual environment is available. |
| Evidence HTTP endpoint | Blocked. FastAPI and the backend runtime are unavailable. Only the underlying passage resolver path was exercised. |
| Live generation | Not performed |

The scripted harness constructs upstream decision and receipt objects
directly. It exercises the unchanged registry, validator, passage branch,
and query method from hash-checked source. No workflow scheduling, database
scope verification, receipts persistence, or HTTP behavior is implied.
It demonstrates a scripted insufficient-evidence decision on an
employee-specific question, rather than model answer quality.

Before production, run the complete assistant flow in the approved backend
environment. Verify startup and readiness, authorized Runs and scope
filters, cancellation under CPU load, persistence and reload of citations,
the evidence endpoint, and historical version behavior. Confirm outbound
evidence permissions before enabling model access. Keep the real catalog and
unseen evaluation profile gated.

From the repository root:

```sh
.venv-rag/bin/python -B -m unittest discover -s rag_bot -v
HF_HUB_OFFLINE=1 .venv-rag/bin/python -B -m rag_bot.smoke_service
.venv-rag/bin/python -B -m rag_bot.verify_backend_contract --checkout /path/to/existing/audited-checkout
HF_HUB_OFFLINE=1 .venv-rag/bin/python -B -m rag_bot.verify_backend_passage_path --checkout /path/to/existing/audited-checkout
```

Use the semantic dependencies and the existing Pydantic 2.14.4 runtime for
these isolated checks. The passage-path command also requires the pinned
MiniLM model in the local cache.

Both verifiers also accept a JSON map of repository-relative paths to exact
source text on stdin. Their hash checks reject the older local backend files.
