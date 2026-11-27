"""Exercise hash-checked upstream components without installing the backend runtime."""

import argparse
import asyncio
import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

from .backend_adapter import AUDITED_REVISION, BackendRetrievalAdapter
from .service import RetrievalService
from .verify_backend_contract import ADAPTER_BLOB, BLOBS, verified_modules


async def verify(sources):
    backend, model_types, limits, adapters = verified_modules(sources, passage_path=True)
    c, tools, e = backend.contracts, backend.tools, backend.evidence
    start = datetime(2026, 10, 14, tzinfo=UTC)
    scope = c.PinnedScope(
        runs=(c.RunReference(batch_id="isolated-test-batch", run_id="isolated-test-run"),),
        event_time=c.EventTimeRange(start=start, end=start + timedelta(days=1)),
    )
    connection = object()  # Identity sentinel. The passage branch performs no database reads.
    service = RetrievalService(cache_dir=None)
    adapter = BackendRetrievalAdapter(
        service, backend, authorize_scope=lambda supplied: supplied is scope,
        authorize_passage=lambda supplied, _: supplied is connection,
        max_argument_bytes=limits.max_argument_bytes, max_result_bytes=limits.max_tool_result_bytes,
    )
    registry = tools.ToolRegistry({"retrieve_context": adapter})
    empty_registry = tools.ToolRegistry({})
    denied_registry = tools.ToolRegistry({"retrieve_context": BackendRetrievalAdapter(service, backend)})

    async def dispatch(question, registry=registry):
        # Scripted decision driving the actual registry, independently of LangGraph.
        call = model_types.ToolCall(tool="retrieve_context", arguments={"query": question, "limit": 3})
        arguments = registry.prepare(call, scope, limits.max_argument_bytes)
        return await registry.invoke(call.tool, scope, arguments, reference_namespace="step_" + "1" * 32,
                                     maximum_bytes=limits.max_tool_result_bytes)

    question = "What is a Tool Candidate?"
    outcome = await dispatch(question)
    assert isinstance(outcome, c.ToolSuccess) and outcome.outcome == "data", outcome
    first = outcome.evidence[0]
    assert isinstance(first, c.PassageEvidence) and first.source_role == "project_policy"
    assert "grouping of identity clues" in first.excerpt
    step = c.ExecutionStep(step_id="step_" + "1" * 32, sequence=1, tool="retrieve_context",
                           scope=scope, arguments={"query": question, "limit": 3},
                           started_at=start, completed_at=start, outcome=outcome)
    context = model_types.DecisionContext(instructions="Cite approved project documentation.",
                                          question=question, scope=scope, observations=(step,),
                                          tools=registry.descriptions(), remaining_tool_calls=1,
                                          remaining_model_calls=1)
    # The scripted decision constructs a claim from the retrieved definition.
    selection = context.observations[0].outcome.evidence[0]
    decision = model_types.AnswerDecision(findings=(c.Finding(
        facts=(c.FactualClaim(text="A Tool Candidate groups unresolved identity clues.",
                              evidence_ids=(selection.evidence_id,)),),
        interpretation="Project terminology.",
    ),))
    answer = c.GroundedAnswer(scope=scope, findings=decision.findings, stop_reason="sufficient_evidence")
    c.validate_answer_references(answer, outcome.evidence)

    reference = e.PassageReference(corpus_version=first.corpus_version, document_id=first.document_id,
                                   document_version=first.document_version, passage_id=first.passage_id)
    evidence_sources = e.EvidenceSources(passages=adapter.resolve_passage)
    resolved = e.resolve_evidence(connection, reference, evidence_sources)
    assert isinstance(resolved, e.ResolvedEvidence)
    assert resolved.record["excerpt"] == first.excerpt and resolved.reference == reference
    assert resolved.source.batch_id is None and resolved.source.run_id is None
    assert resolved.role == "governance_guidance"

    # Exercise the real query method with a test-only verified-read boundary.
    query_tools = adapters.QueryTools(None, evidence_sources, limits.max_tool_result_bytes)
    read = SimpleNamespace(pinned=scope, warnings=())
    reopened = query_tools.get_evidence(connection, read, tools.GetEvidenceArgs(
        references=(first.evidence_id,),
    ))
    assert reopened.outcome == "data" and reopened.data["resolved"][0]["record"]["excerpt"] == first.excerpt
    assert reopened.evidence == (), "Audited omission changed. Reinspect upstream."
    try:
        c.validate_answer_references(answer, reopened.evidence)
    except ValueError:
        pass
    else:
        raise AssertionError("The resolved data unexpectedly supplied typed evidence.")

    for updated, error_code in (
        (reference.model_copy(update={"document_version": "0" * 64}), "source_version_unavailable"),
        (reference.model_copy(update={"passage_id": "0" * 20}), "passage_not_found"),
    ):
        try:
            e.resolve_evidence(connection, updated, evidence_sources)
        except e.EvidenceError as error:
            assert error.status_code == 404 and error.code == error_code
        else:
            raise AssertionError("Stale or unknown evidence unexpectedly resolved.")
    try:
        e.resolve_evidence(connection, reference)
    except e.EvidenceError as error:
        assert error.status_code == 501 and error.code == "passage_corpus_unavailable"
    else:
        raise AssertionError("An unconfigured passage resolver unexpectedly responded.")

    for missing in (empty_registry, denied_registry):
        result = await dispatch(question, missing)
        assert isinstance(result, c.ToolLimitation) and result.reason == "unavailable"
    assert (await dispatch("How do I bake a chocolate cake?")).outcome == "no_matches"
    assert (await dispatch("word " * 256)).reason == "unsupported"

    employee = await dispatch("What is the risk tier of a specific employee's ChatGPT usage?")
    assert isinstance(employee, c.ToolSuccess) and employee.evidence
    assert all(isinstance(item, c.PassageEvidence) for item in employee.evidence)
    assert all(item.source_role == "project_policy" for item in employee.evidence)
    assert any("No Batch or Run findings" in note for note in employee.qualifications)
    stop = model_types.StopDecision(
        reason="insufficient_evidence", message="No employee-specific activity or assessment is available."
    )
    limitation = c.LimitedResponse(scope=scope, reason=stop.reason, message=stop.message)
    assert limitation.reason == "insufficient_evidence"

    print(f"Verified actual registry, scripted citation, and resolver passage branch at {AUDITED_REVISION}.")
    print("Reproduced upstream get_evidence omission: resolved excerpt present, typed evidence empty.")
    print("Verified disabled/missing retrieval, empty and over-token results, stale/unknown references, "
          "and documentary-only evidence for an employee-risk question.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--checkout", type=Path, help="Root containing exact audited source blobs")
    args = parser.parse_args()
    sources = ({path: (args.checkout / path).read_bytes().decode("utf-8") for path in BLOBS | ADAPTER_BLOB}
               if args.checkout is not None else json.load(sys.stdin))
    asyncio.run(verify(sources))


if __name__ == "__main__":
    main()
