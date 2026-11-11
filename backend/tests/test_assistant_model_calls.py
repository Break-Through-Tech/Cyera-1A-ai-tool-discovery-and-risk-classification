import asyncio
import json

import httpx
import pytest
from alembic import command
from alembic.config import Config
from app.assistant.contracts import (
    LimitedResponse,
    RecordEvidence,
    ToolFailure,
    ToolSuccess,
)
from app.assistant.graph import Assistant
from app.assistant.integrations import ModelMetadata
from app.assistant.store import (
    fail_interrupted_turns,
    fail_turn,
    finish_model_call,
    finish_turn,
    get_turn,
    list_model_calls,
    list_steps,
    start_model_call,
)
from app.assistant.tools import ToolRegistry
from app.db.engine import MIGRATIONS_DIR, migrate, open_database
from app.db.tables import assistant_turns
from sqlalchemy import select
from tests.test_gemini_model import function_response, sdk_model


def begin(engine, turn, sequence=1):
    start_model_call(
        engine,
        turn.turn_id,
        sequence=sequence,
        provider="fixture",
        requested_model=turn.model_id,
        context_sha256="a" * 64,
        metadata=ModelMetadata(sdk_version="fixture-v1", retry_attempts=1),
    )


def test_model_call_lifecycle_is_persistent_sequential_and_immutable(stored, data_dir):
    engine, turn = stored
    begin(engine, turn)
    calls, total = list_model_calls(engine, turn.turn_id)
    assert total == 1 and calls[0].status == "running"
    assert calls[0].started_at.tzinfo is not None
    assert calls[0].metadata.sdk_version == "fixture-v1"
    with pytest.raises(ValueError, match="sequential"):
        begin(engine, turn, sequence=2)
    with pytest.raises(ValueError, match="unfinished model"):
        finish_turn(
            engine,
            turn.turn_id,
            LimitedResponse(
                scope=turn.scope,
                reason="insufficient_evidence",
                message="No evidence.",
            ),
        )
    metadata = ModelMetadata(
        sdk_version="fixture-v1",
        resolved_model="fixture-resolved",
        response_id="response_1",
    )
    finish_model_call(engine, turn.turn_id, 1, metadata=metadata)
    with pytest.raises(ValueError, match="finalized"):
        finish_model_call(engine, turn.turn_id, 1, metadata=metadata)
    reopened = open_database(data_dir / "app.sqlite3")
    try:
        calls, total = list_model_calls(reopened, turn.turn_id)
        assert total == 1 and calls[0].status == "succeeded"
        assert calls[0].metadata == metadata
        assert calls[0].completed_at >= calls[0].started_at
    finally:
        reopened.dispose()


def test_failed_or_interrupted_model_calls_prevent_a_successful_response(stored):
    engine, turn = stored
    begin(engine, turn)
    failure = ToolFailure(code="model_failed", message="The provider failed; retry.")
    finish_model_call(
        engine, turn.turn_id, 1, metadata=ModelMetadata(), failure=failure
    )
    with pytest.raises(ValueError, match="sequential"):
        begin(engine, turn, sequence=2)
    with pytest.raises(ValueError, match="failed or unfinished"):
        finish_turn(
            engine,
            turn.turn_id,
            LimitedResponse(
                scope=turn.scope,
                reason="insufficient_evidence",
                message="No evidence.",
            ),
        )
    fail_turn(engine, turn.turn_id, failure)
    assert list_model_calls(engine, turn.turn_id)[0][0].failure == failure


def test_aborting_a_turn_finalizes_its_inflight_model_call_atomically(stored):
    engine, turn = stored
    begin(engine, turn)
    failure = ToolFailure(code="turn_cancelled", message="Cancelled; retry.")
    fail_turn(engine, turn.turn_id, failure)
    call = list_model_calls(engine, turn.turn_id)[0][0]
    assert call.status == "failed" and call.failure == failure
    assert get_turn(engine, turn.turn_id).failure == failure
    with pytest.raises(ValueError, match="Finalized"):
        begin(engine, turn, sequence=2)


def test_startup_cleanup_marks_inflight_model_call_interrupted(stored):
    engine, turn = stored
    begin(engine, turn)
    assert fail_interrupted_turns(engine) == 1
    assert (
        list_model_calls(engine, turn.turn_id)[0][0].failure.code == "turn_interrupted"
    )
    assert fail_interrupted_turns(engine) == 0


def test_model_identity_sequence_hash_and_pagination_are_checked(stored):
    engine, turn = stored
    with pytest.raises(ValueError, match="requested model"):
        start_model_call(
            engine,
            turn.turn_id,
            sequence=1,
            provider="fixture",
            requested_model="other",
            context_sha256="a" * 64,
            metadata=ModelMetadata(),
        )
    with pytest.raises(ValueError):
        start_model_call(
            engine,
            turn.turn_id,
            sequence=1,
            provider="fixture",
            requested_model=turn.model_id,
            context_sha256="not-a-hash",
            metadata=ModelMetadata(),
        )
    begin(engine, turn)
    finish_model_call(engine, turn.turn_id, 1, metadata=ModelMetadata())
    begin(engine, turn, sequence=2)
    calls, total = list_model_calls(engine, turn.turn_id, offset=1, limit=1)
    assert total == 2 and calls[0].sequence == 2
    with pytest.raises(ValueError):
        list_model_calls(engine, turn.turn_id, limit=101)
    with pytest.raises(LookupError):
        list_model_calls(engine, "another_turn")


def test_real_sdk_graph_tool_and_metadata_storage_work_together(stored):
    engine, original = stored

    def respond(body, count):
        snapshot = json.loads(body["contents"][0]["parts"][0]["text"])
        if count == 1:
            assert snapshot["observations"] == []
            return function_response("get_evidence", {"references": ["evt_1"]})
        evidence_id = snapshot["observations"][0]["outcome"]["evidence"][0][
            "evidence_id"
        ]
        return function_response(
            "return_findings",
            {
                "findings": [
                    {
                        "facts": [
                            {
                                "text": "A fixture Activity Event was observed.",
                                "evidence_ids": [evidence_id],
                            }
                        ],
                        "interpretation": "Observed activity does not prove sensitive-data submission.",
                    }
                ]
            },
            responseId="provider_response_2",
        )

    async def handler(scope, arguments):
        assert arguments.references == ("evt_1",)
        return ToolSuccess(
            outcome="data",
            summary="One fixture event.",
            data={"event_count": 1},
            evidence=(
                RecordEvidence(
                    evidence_id="local_1",
                    run=scope.runs[0],
                    record_type="activity_event",
                    record_id="evt_1",
                ),
            ),
        )

    async def exercise():
        async with sdk_model(respond) as (model, requests):
            turn = await Assistant(
                engine, model, ToolRegistry({"get_evidence": handler})
            ).run_turn(
                question="What was observed?",
                scope=original.scope,
            )
            assert len(requests) == 2
            return turn

    turn = asyncio.run(exercise())
    assert turn.status == "succeeded" and turn.answer.kind == "grounded_answer"
    assert list_steps(engine, turn.turn_id)[1] == 1
    calls, total = list_model_calls(engine, turn.turn_id)
    assert total == 2
    assert [call.sequence for call in calls] == [1, 2]
    assert all(
        call.status == "succeeded" and call.provider == "gemini" for call in calls
    )
    assert all(
        turn.started_at <= call.started_at <= call.completed_at <= turn.completed_at
        for call in calls
    )
    assert all(call.requested_model == "gemini-fixture" for call in calls)
    assert all(call.metadata.resolved_model == "gemini-fixture-001" for call in calls)
    assert [call.metadata.response_id for call in calls] == [
        "provider_response_1",
        "provider_response_2",
    ]
    assert calls[0].context_sha256 != calls[1].context_sha256
    assert calls[0].metadata.usage.prompt == 120
    assert "fixture-key" not in "".join(call.model_dump_json() for call in calls)


def test_sdk_rejection_preserves_safe_provider_metadata_in_the_failed_turn(stored):
    engine, original = stored
    response = function_response()
    response["candidates"][0]["finishReason"] = "MAX_TOKENS"

    async def exercise():
        async with sdk_model(lambda body, count: response) as (model, _):
            return await Assistant(engine, model, ToolRegistry({})).run_turn(
                question="Question",
                scope=original.scope,
            )

    turn = asyncio.run(exercise())
    assert turn.status == "failed" and turn.answer is None
    call = list_model_calls(engine, turn.turn_id)[0][0]
    assert call.status == "failed" and call.failure.code == "invalid_model_response"
    assert call.metadata.finish_reason == "MAX_TOKENS"
    assert call.metadata.response_id == "provider_response_1"
    assert call.metadata.usage.total == 160


def test_sdk_api_failure_records_only_safe_status_metadata(stored):
    engine, original = stored

    async def exercise():
        async with sdk_model(
            lambda body, count: httpx.Response(
                503,
                json={
                    "error": {
                        "code": 503,
                        "message": "PRIVATE_PROVIDER_BODY",
                        "status": "UNAVAILABLE",
                    },
                },
            )
        ) as (model, requests):
            turn = await Assistant(engine, model, ToolRegistry({})).run_turn(
                question="Question",
                scope=original.scope,
            )
            assert len(requests) == 1
            return turn

    turn = asyncio.run(exercise())
    calls, total = list_model_calls(engine, turn.turn_id)
    assert turn.status == "failed" and turn.answer is None
    assert total == 1 and calls[0].metadata.http_status == 503
    assert calls[0].metadata.usage.total is None
    assert (
        "PRIVATE_PROVIDER_BODY"
        not in calls[0].model_dump_json() + turn.model_dump_json()
    )


def test_cancelled_model_request_closes_the_model_call_and_turn(stored):
    engine, original = stored
    entered = asyncio.Event()
    from tests.test_assistant_graph import ScriptedModel

    class CancelledModel(ScriptedModel):
        async def decide(self, context):
            entered.set()
            await asyncio.Event().wait()

    async def exercise():
        task = asyncio.create_task(
            Assistant(engine, CancelledModel(), ToolRegistry({})).run_turn(
                question="Question",
                scope=original.scope,
            )
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
    call = list_model_calls(engine, turn_id)[0][0]
    assert call.status == "failed" and call.failure.code == "turn_cancelled"
    assert get_turn(engine, turn_id).failure.code == "turn_cancelled"


def test_migration_preserves_existing_turns_when_upgrading_from_phase_three(stored):
    engine, turn = stored
    with engine.begin() as connection:
        config = Config()
        config.set_main_option("script_location", str(MIGRATIONS_DIR))
        config.attributes["connection"] = connection
        command.downgrade(config, "0005")
    assert get_turn(engine, turn.turn_id) == turn
    migrate(engine)
    assert get_turn(engine, turn.turn_id) == turn
    assert list_model_calls(engine, turn.turn_id) == ((), 0)
