import asyncio

import pytest
from app.assistant.contracts import (
    AggregateEvidence,
    FactualClaim,
    Finding,
    GroundedAnswer,
    LimitedResponse,
    RecordEvidence,
    ToolLimitation,
    ToolSuccess,
)
from app.assistant.graph import Assistant, ExecutionLimits
from app.assistant.integrations import AnswerDecision, StopDecision, ToolCall
from app.assistant.store import get_evidence, get_turn, list_steps
from app.assistant.tools import ToolRegistry
from app.db.tables import assistant_turns
from sqlalchemy import select


class ScriptedModel:
    model_id = "fixture-model-not-gemini"

    def __init__(self, *decisions):
        self.decisions = iter(decisions)
        self.contexts = []

    async def decide(self, context):
        self.contexts.append(context)
        decision = next(self.decisions)
        if isinstance(decision, Exception):
            raise decision
        if callable(decision):
            decision = decision(context)
        return (
            decision.model_dump(mode="json")
            if hasattr(decision, "model_dump")
            else decision
        )


def evidence_call():
    return ToolCall(tool="get_evidence", arguments={"references": ["event_1"]})


async def fixture_handler(scope, arguments):
    return ToolSuccess(
        outcome="data",
        summary="One fixture event.",
        data={"event_count": 1},
        evidence=(
            RecordEvidence(
                evidence_id="local_1",
                run=scope.runs[0],
                record_type="activity_event",
                record_id="event_1",
            ),
        ),
        qualifications=("Fixture evidence only.",),
    )


def cited_answer(context):
    sources = context.observations[-1].outcome.evidence
    return AnswerDecision(
        findings=(
            Finding(
                facts=(
                    FactualClaim(
                        text="One fixture event.",
                        evidence_ids=(sources[0].evidence_id,),
                    ),
                ),
                interpretation="Review the supplied context before drawing conclusions.",
            ),
        )
    )


def run(stored, model, handlers=None, limits=None, briefing=False):
    engine, original = stored
    assistant = Assistant(engine, model, ToolRegistry(handlers or {}), limits)
    return asyncio.run(
        assistant.run_turn(
            question="What needs attention?",
            scope=original.scope,
            briefing=briefing,
        )
    )


def test_question_runs_a_real_langgraph_loop_and_persists_the_answer_and_receipts(
    stored,
):
    engine, original = stored
    model = ScriptedModel(evidence_call(), cited_answer)
    turn = run(stored, model, {"get_evidence": fixture_handler})

    assert turn.status == "succeeded"
    assert isinstance(turn.answer, GroundedAnswer)
    assert turn.scope == original.scope
    assert turn.model_id == model.model_id
    steps, total = list_steps(engine, turn.turn_id)
    assert total == 1 and steps[0].tool == "get_evidence"
    cited = turn.answer.findings[0].facts[0].evidence_ids[0]
    assert get_evidence(engine, turn.turn_id, cited).step_id == steps[0].step_id
    assert model.contexts[0].observations == ()
    assert model.contexts[1].observations == steps
    assert turn.answer.limitations == ("Fixture evidence only.",)


def test_briefing_runs_standard_summaries_before_the_model_and_then_investigates(
    stored,
):
    engine, _ = stored
    model = ScriptedModel(evidence_call(), cited_answer)
    turn = run(
        stored,
        model,
        {
            name: fixture_handler
            for name in (
                "describe_dataset",
                "summarize_usage",
                "get_risk_assessments",
                "get_evidence",
            )
        },
        briefing=True,
    )
    assert turn.status == "succeeded"
    steps, total = list_steps(engine, turn.turn_id)
    assert total == 4
    assert [step.tool for step in steps] == [
        "describe_dataset",
        "summarize_usage",
        "get_risk_assessments",
        "get_evidence",
    ]
    assert steps[1].arguments["group_by"] == ["department"]
    assert steps[2].arguments["focus"] == "all"
    assert len(model.contexts[0].observations) == 3
    assert model.contexts[0].remaining_tool_calls == 5
    assert len({step.outcome.evidence[0].evidence_id for step in steps}) == 4


def test_missing_briefing_capability_is_a_limitation_without_model_fallback(stored):
    engine, _ = stored
    model = ScriptedModel()
    turn = run(stored, model, briefing=True)
    assert turn.status == "succeeded" and isinstance(turn.answer, LimitedResponse)
    assert turn.answer.reason == "unsupported"
    assert "describe_dataset is not connected." in turn.answer.limitations
    assert model.contexts == []
    assert list_steps(engine, turn.turn_id)[0][0].outcome.reason == "unavailable"


@pytest.mark.parametrize(
    "reason", ["clarification_required", "unsupported", "insufficient_evidence"]
)
def test_nonanswers_do_not_require_invented_findings_or_become_service_failures(
    stored, reason
):
    model = ScriptedModel(
        StopDecision(reason=reason, message="Additional scope or evidence is needed.")
    )
    turn = run(stored, model)
    assert turn.status == "succeeded" and turn.failure is None
    assert isinstance(turn.answer, LimitedResponse) and turn.answer.reason == reason
    assert list_steps(stored[0], turn.turn_id)[1] == 0


def test_briefing_preserves_a_tool_request_for_clarification(stored):
    async def clarify(scope, arguments):
        return ToolLimitation(
            reason="clarification_required", message="Which policy snapshot?"
        )

    turn = run(stored, ScriptedModel(), {"describe_dataset": clarify}, briefing=True)
    assert turn.answer.reason == "clarification_required"
    assert turn.answer.message == "Which policy snapshot?"


def test_invented_citations_fail_the_turn_without_publishing_partial_findings(stored):
    model = ScriptedModel(
        evidence_call(),
        AnswerDecision(
            findings=(
                Finding(
                    facts=(
                        FactualClaim(
                            text="Unsupported claim.", evidence_ids=("invented",)
                        ),
                    ),
                    interpretation="Not supported.",
                ),
            )
        ),
    )
    turn = run(stored, model, {"get_evidence": fixture_handler})
    assert turn.status == "failed" and turn.answer is None
    assert turn.failure.code == "invalid_answer"
    assert list_steps(stored[0], turn.turn_id)[1] == 1


def test_tool_budget_prevents_extra_execution_and_discloses_unfinished_work(stored):
    model = ScriptedModel(evidence_call(), evidence_call())
    turn = run(
        stored,
        model,
        {"get_evidence": fixture_handler},
        ExecutionLimits(max_tool_calls=1),
    )
    assert turn.answer.reason == "budget_reached"
    assert "unfinished" in turn.answer.message
    assert turn.answer.unfinished_work == (
        "Requested get_evidence follow-up was not executed.",
    )
    assert list_steps(stored[0], turn.turn_id)[1] == 1
    assert model.contexts[-1].remaining_tool_calls == 0


def test_a_final_supported_answer_is_allowed_when_tool_budget_is_exhausted(stored):
    model = ScriptedModel(evidence_call(), cited_answer)
    turn = run(
        stored,
        model,
        {"get_evidence": fixture_handler},
        ExecutionLimits(max_tool_calls=1),
    )
    assert isinstance(turn.answer, GroundedAnswer)
    assert turn.answer.stop_reason == "sufficient_evidence"


def test_model_budget_cannot_reset_when_tool_results_return(stored):
    model = ScriptedModel(evidence_call())
    turn = run(
        stored,
        model,
        {"get_evidence": fixture_handler},
        ExecutionLimits(max_model_calls=1),
    )
    assert turn.answer.reason == "budget_reached"
    assert len(model.contexts) == 1
    assert list_steps(stored[0], turn.turn_id)[1] == 1


def test_insufficient_briefing_budget_executes_nothing(stored):
    turn = run(
        stored, ScriptedModel(), limits=ExecutionLimits(max_tool_calls=2), briefing=True
    )
    assert turn.answer.reason == "budget_reached"
    assert list_steps(stored[0], turn.turn_id)[1] == 0


@pytest.mark.parametrize("kind", ["exception", "invalid", "oversized"])
def test_bad_tool_executions_fail_without_partial_answers_or_raw_exception_text(
    stored, kind
):
    async def handler(scope, arguments):
        if kind == "exception":
            raise RuntimeError("credential=do-not-expose")
        if kind == "invalid":
            return {"invalid": True}
        return ToolSuccess(
            outcome="data", summary="Too large.", data={"text": "x" * 40000}
        )

    model = ScriptedModel(evidence_call())
    turn = run(stored, model, {"get_evidence": handler})
    assert turn.status == "failed" and turn.answer is None
    step = list_steps(stored[0], turn.turn_id)[0][0]
    assert step.outcome.status == "failed"
    assert "credential" not in step.model_dump_json() + turn.model_dump_json()
    assert len(model.contexts) == 1


@pytest.mark.parametrize(
    "decision",
    [
        {"kind": "tool_call", "tool": "execute_sql", "arguments": {}},
        {
            "kind": "tool_call",
            "tool": "get_evidence",
            "arguments": {"scope": "another_run"},
        },
        {
            "kind": "stop",
            "reason": "unsupported",
            "message": "No.",
            "scope": "another_run",
        },
    ],
)
def test_untrusted_decisions_cannot_expand_permissions_or_scope(stored, decision):
    calls = []

    async def handler(scope, arguments):
        calls.append(arguments)
        return await fixture_handler(scope, arguments)

    turn = run(stored, ScriptedModel(decision), {"get_evidence": handler})
    assert turn.status == "failed" and turn.answer is None
    assert calls == []
    assert list_steps(stored[0], turn.turn_id)[1] == 0


def test_model_service_failures_do_not_fall_back_to_previous_tool_results(stored):
    model = ScriptedModel(evidence_call(), RuntimeError("private provider diagnostic"))
    turn = run(stored, model, {"get_evidence": fixture_handler})
    assert turn.status == "failed" and turn.failure.code == "model_failed"
    assert turn.answer is None and "private" not in turn.model_dump_json()
    assert list_steps(stored[0], turn.turn_id)[1] == 1


def test_model_cannot_mutate_persisted_or_in_memory_observations(stored):
    def tamper(context):
        context.observations[-1].outcome.data["event_count"] = 999
        return evidence_call()

    def inspect_and_answer(context):
        assert context.observations[0].outcome.data["event_count"] == 1
        return cited_answer(context)

    turn = run(
        stored,
        ScriptedModel(evidence_call(), tamper, inspect_and_answer),
        {"get_evidence": fixture_handler},
    )
    assert turn.status == "succeeded"
    assert list_steps(stored[0], turn.turn_id)[0][0].outcome.data["event_count"] == 1


def test_no_matching_records_is_a_valid_cited_result_not_an_execution_failure(stored):
    async def no_matches(scope, arguments):
        return ToolSuccess(
            outcome="no_matches",
            summary="No matching events.",
            data={"event_count": 0},
            evidence=(
                AggregateEvidence(
                    evidence_id="zero",
                    scope=scope,
                    operation="summarize_usage",
                    query={"metric": "event_count"},
                    metric_definitions=("Count supplied events.",),
                    drilldown_reference="fixture_query_1",
                ),
            ),
        )

    def zero_answer(context):
        source = context.observations[-1].outcome.evidence[0]
        return AnswerDecision(
            findings=(
                Finding(
                    facts=(
                        FactualClaim(
                            text="No matching events in the selected scope.",
                            evidence_ids=(source.evidence_id,),
                        ),
                    ),
                    interpretation="This does not establish absence outside the stored scope.",
                ),
            )
        )

    turn = run(
        stored,
        ScriptedModel(
            ToolCall(tool="summarize_usage", arguments={}),
            zero_answer,
        ),
        {"summarize_usage": no_matches},
    )
    assert isinstance(turn.answer, GroundedAnswer)
    assert list_steps(stored[0], turn.turn_id)[0][0].outcome.outcome == "no_matches"


@pytest.mark.parametrize("late_component", ["model", "tool"])
def test_late_results_are_rejected_even_when_the_adapter_returns_normally(
    stored, monkeypatch, late_component
):
    clock = [0.0]
    monkeypatch.setattr("app.assistant.graph.monotonic", lambda: clock[0])

    def late_model(context):
        clock[0] = 100.0
        return StopDecision(reason="unsupported", message="Late response.")

    async def late_tool(scope, arguments):
        clock[0] = 100.0
        return await fixture_handler(scope, arguments)

    model = ScriptedModel(late_model if late_component == "model" else evidence_call())
    turn = run(stored, model, {"get_evidence": late_tool})
    assert turn.status == "failed" and turn.answer is None
    assert turn.failure.code == f"{late_component}_timeout"


def test_tool_timeout_records_a_failed_receipt_and_stops_the_turn(stored):
    async def hangs(scope, arguments):
        await asyncio.Event().wait()

    model = ScriptedModel(evidence_call())
    turn = run(
        stored, model, {"get_evidence": hangs}, ExecutionLimits(max_turn_seconds=0.5)
    )
    assert turn.status == "failed"
    assert turn.failure.code == "tool_timeout"
    assert list_steps(stored[0], turn.turn_id)[0][0].outcome.code == "tool_timeout"


def test_model_timeout_is_a_failure_not_an_insufficient_evidence_answer(stored):
    class HangingModel:
        model_id = "hanging-fixture"

        async def decide(self, context):
            await asyncio.Event().wait()

    turn = run(stored, HangingModel(), limits=ExecutionLimits(max_turn_seconds=0.5))
    assert turn.status == "failed" and turn.failure.code == "model_timeout"
    assert turn.answer is None


def test_context_and_model_output_limits_are_enforced(stored):
    model = ScriptedModel(StopDecision(reason="unsupported", message="x" * 1000))
    turn = run(stored, model, limits=ExecutionLimits(max_model_output_bytes=100))
    assert turn.status == "failed" and turn.failure.code == "invalid_model_response"
    unused = ScriptedModel()
    turn = run(stored, unused, limits=ExecutionLimits(max_context_bytes=10))
    assert turn.failure.code == "context_limit" and unused.contexts == []


def test_unavailable_optional_tool_is_visible_and_can_lead_to_an_explicit_abstention(
    stored,
):
    model = ScriptedModel(
        ToolCall(tool="retrieve_context", arguments={"query": "policy"}),
        StopDecision(
            reason="insufficient_evidence", message="No retained guidance is available."
        ),
    )
    turn = run(stored, model)
    assert turn.answer.reason == "insufficient_evidence"
    assert "retrieve_context is not connected." in turn.answer.limitations


def test_graceful_cancellation_preserves_the_attempt_and_fails_the_turn(stored):
    engine, original = stored
    entered = asyncio.Event()

    async def handler(scope, arguments):
        entered.set()
        await asyncio.Event().wait()

    async def exercise():
        assistant = Assistant(
            engine,
            ScriptedModel(evidence_call()),
            ToolRegistry({"get_evidence": handler}),
        )
        task = asyncio.create_task(
            assistant.run_turn(question="Question", scope=original.scope)
        )
        await asyncio.wait_for(entered.wait(), timeout=2)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(exercise())
    with engine.connect() as connection:
        turn_id = connection.execute(
            select(assistant_turns.c.turn_id).where(
                assistant_turns.c.turn_id != original.turn_id
            )
        ).scalar_one()
    assert get_turn(engine, turn_id).failure.code == "turn_cancelled"
    assert list_steps(engine, turn_id)[0][0].outcome.code == "tool_cancelled"


def test_concurrent_turns_do_not_share_observations_or_citation_ids(stored):
    engine, original = stored

    class PerQuestionModel:
        model_id = "concurrent-fixture"

        async def decide(self, context):
            decision = (
                cited_answer(context) if context.observations else evidence_call()
            )
            return decision.model_dump(mode="json")

    async def exercise():
        assistant = Assistant(
            engine, PerQuestionModel(), ToolRegistry({"get_evidence": fixture_handler})
        )
        return await asyncio.gather(
            assistant.run_turn(question="First question", scope=original.scope),
            assistant.run_turn(question="Second question", scope=original.scope),
        )

    first, second = asyncio.run(exercise())
    assert first.turn_id != second.turn_id
    first_id = first.answer.findings[0].facts[0].evidence_ids[0]
    second_id = second.answer.findings[0].facts[0].evidence_ids[0]
    assert first_id != second_id
    assert (
        list_steps(engine, first.turn_id)[1]
        == list_steps(engine, second.turn_id)[1]
        == 1
    )
    with pytest.raises(LookupError):
        get_evidence(engine, first.turn_id, second_id)


def test_startup_marks_abandoned_turns_failed_without_erasing_the_trace(
    stored, make_client
):
    engine, original = stored
    make_client()
    assert get_turn(engine, original.turn_id).failure.code == "turn_interrupted"
