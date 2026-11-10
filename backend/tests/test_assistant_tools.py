import asyncio

import pytest
from app.assistant.contracts import RecordEvidence, RunReference, ToolSuccess
from app.assistant.integrations import ToolCall
from app.assistant.tools import InvalidToolResult, RetrieveContextArgs, ToolRegistry
from pydantic import ValidationError
from tests.test_assistant_contracts import scope


def invoke(registry, call, *, maximum_bytes=32768):
    selected = scope()
    arguments = registry.prepare(call, selected, 4096)
    return asyncio.run(
        registry.invoke(
            call.tool,
            selected,
            arguments,
            reference_namespace="step_1",
            maximum_bytes=maximum_bytes,
        )
    )


def test_only_allowlisted_tools_can_be_registered_or_requested():
    with pytest.raises(ValidationError):
        ToolRegistry({"execute_sql": None})
    with pytest.raises(ValidationError):
        ToolCall(tool="run_python_analysis", arguments={"code": "print('no')"})


def test_unconnected_tools_are_unavailable_not_empty_success():
    result = invoke(
        ToolRegistry({}),
        ToolCall(tool="retrieve_context", arguments={"query": "policy"}),
    )
    assert result.status == "limited" and result.reason == "unavailable"
    assert ToolRegistry({}).descriptions() == ()


@pytest.mark.parametrize(
    "arguments",
    [
        {"query": "policy", "scope": {"run_id": "another_run"}},
        {"query": "policy", "sql": "SELECT * FROM activity_events"},
        {"query": "policy", "limit": 1000},
        {"query": "policy", "limit": True},
        {"query": "policy", "limit": "5"},
        {"query": " "},
    ],
)
def test_invalid_arguments_are_rejected_before_handler_execution(arguments):
    calls = []

    async def handler(selected, parsed):
        calls.append(parsed)
        raise AssertionError("Must not execute")

    with pytest.raises(ValueError):
        invoke(
            ToolRegistry({"retrieve_context": handler}),
            ToolCall(
                tool="retrieve_context",
                arguments=arguments,
            ),
        )
    assert calls == []


def test_comparison_periods_cannot_expand_the_backend_selected_scope():
    registry = ToolRegistry({})
    call = ToolCall(
        tool="compare_usage",
        arguments={
            "baseline": {
                "start": "2026-09-01T00:00:00Z",
                "end": "2026-10-01T00:00:00Z",
            },
            "current": {"start": "2026-10-01T00:00:00Z", "end": "2026-11-01T00:00:00Z"},
        },
    )
    with pytest.raises(ValueError, match="expand"):
        registry.prepare(call, scope(), 4096)


def test_handlers_receive_typed_arguments_and_backend_owned_scope():
    async def handler(selected, parsed):
        assert selected == scope()
        assert isinstance(parsed, RetrieveContextArgs)
        assert parsed.query == "policy"
        return ToolSuccess(
            outcome="no_matches", summary="No retained passages match.", data={}
        )

    registry = ToolRegistry({"retrieve_context": handler})
    result = invoke(
        registry, ToolCall(tool="retrieve_context", arguments={"query": "policy"})
    )
    assert result.outcome == "no_matches"
    schema = registry.descriptions()[0].arguments_schema
    assert schema["additionalProperties"] is False
    assert schema["properties"]["limit"]["maximum"] == 10


def test_result_references_are_namespaced_without_changing_source_identity():
    async def handler(selected, parsed):
        return ToolSuccess(
            outcome="data",
            summary="One event.",
            data={"event_count": 1},
            evidence=(
                RecordEvidence(
                    evidence_id="local_1",
                    run=selected.runs[0],
                    record_type="activity_event",
                    record_id="event_1",
                ),
            ),
        )

    result = invoke(
        ToolRegistry({"get_evidence": handler}),
        ToolCall(
            tool="get_evidence",
            arguments={"references": ["event_1"]},
        ),
    )
    assert result.evidence[0].evidence_id == "step_1:local_1"
    assert result.evidence[0].record_id == "event_1"
    assert result.evidence[0].run == scope().runs[0]


@pytest.mark.parametrize("invalid", ["scope", "duplicates", "oversized", "schema"])
def test_invalid_tool_results_are_rejected(invalid):
    async def handler(selected, parsed):
        source = RecordEvidence(
            evidence_id="local_1",
            run=selected.runs[0],
            record_type="activity_event",
            record_id="event_1",
        )
        if invalid == "scope":
            source = source.model_copy(
                update={"run": RunReference(batch_id="other", run_id="other")}
            )
        if invalid == "schema":
            return {"status": "succeeded", "invented": True}
        return ToolSuccess(
            outcome="data",
            summary="One event.",
            data={"text": "x" * 40000} if invalid == "oversized" else {},
            evidence=(source, source) if invalid == "duplicates" else (source,),
        )

    with pytest.raises(InvalidToolResult):
        invoke(
            ToolRegistry({"get_evidence": handler}),
            ToolCall(
                tool="get_evidence",
                arguments={"references": ["event_1"]},
            ),
        )


def test_argument_byte_limit_is_checked_before_execution():
    with pytest.raises(ValueError, match="byte limit"):
        ToolRegistry({}).prepare(
            ToolCall(tool="retrieve_context", arguments={"query": "x" * 100}),
            scope(),
            10,
        )
