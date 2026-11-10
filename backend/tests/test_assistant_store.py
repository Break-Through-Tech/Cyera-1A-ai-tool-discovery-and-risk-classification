from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from threading import Barrier

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.assistant.contracts import (
    EventTimeRange,
    ExecutionStep,
    FactualClaim,
    Finding,
    GroundedAnswer,
    LimitedResponse,
    PinnedScope,
    RecordEvidence,
    RunReference,
    ScopeFilters,
    ToolFailure,
    ToolSuccess,
)
from app.assistant.store import (
    append_step,
    fail_interrupted_turns,
    fail_turn,
    finish_turn,
    get_evidence,
    get_turn,
    list_steps,
    start_turn,
)
from app.db.engine import migrate, open_database
from app.db.tables import assistant_evidence, assistant_turns
from tests.test_batches import upload


def receipt(turn, *, number=1, evidence_id="ev_1", outcome=None):
    now = datetime.now(timezone.utc)
    return ExecutionStep(
        step_id=f"step_{number}", sequence=number, tool="get_evidence", scope=turn.scope,
        arguments={"record_id": "event_1"}, started_at=now, completed_at=now,
        outcome=outcome or ToolSuccess(
            outcome="data", summary="One retained event.", data={"event_count": 1},
            evidence=(RecordEvidence(
                evidence_id=evidence_id, run=turn.scope.runs[0],
                record_type="activity_event", record_id="event_1",
            ),),
        ),
    )


def answer(turn, evidence_id="ev_1"):
    return GroundedAnswer(
        scope=turn.scope, stop_reason="sufficient_evidence",
        findings=(Finding(
            facts=(FactualClaim(text="One observed event.", evidence_ids=(evidence_id,)),),
            interpretation="Activity alone does not establish sensitive-data submission.",
        ),),
    )


def test_turn_steps_evidence_and_answer_survive_a_new_database_connection(stored, data_dir):
    engine, turn = stored
    step = receipt(turn)
    append_step(engine, turn.turn_id, step)
    finish_turn(engine, turn.turn_id, answer(turn))
    engine.dispose()

    reopened = open_database(data_dir / "app.sqlite3")
    try:
        migrate(reopened)
        saved = get_turn(reopened, turn.turn_id)
        assert saved.status == "succeeded"
        assert saved.scope == turn.scope
        assert saved.model_id == "gemini-test-only"
        assert saved.prompt_version == "test-v1"
        assert saved.answer == answer(turn)
        assert saved.completed_at is not None
        assert list_steps(reopened, turn.turn_id) == ((step,), 1)
        evidence = get_evidence(reopened, turn.turn_id, "ev_1")
        assert evidence.step_id == step.step_id
        assert evidence.source == step.outcome.evidence[0]
    finally:
        reopened.dispose()


def test_nonanswer_is_a_successful_limited_response_not_a_failed_execution(stored):
    engine, turn = stored
    response = LimitedResponse(
        scope=turn.scope, reason="clarification_required", message="Which department?",
    )
    finish_turn(engine, turn.turn_id, response)
    saved = get_turn(engine, turn.turn_id)
    assert saved.status == "succeeded" and saved.failure is None
    assert saved.answer == response


def test_phase_two_answers_without_a_kind_field_remain_readable(stored):
    engine, turn = stored
    append_step(engine, turn.turn_id, receipt(turn))
    finish_turn(engine, turn.turn_id, answer(turn))
    old_payload = answer(turn).model_dump(mode="json", exclude={"kind"})
    with engine.begin() as connection:
        connection.execute(assistant_turns.update().where(
            assistant_turns.c.turn_id == turn.turn_id
        ).values(answer=old_payload))
    assert get_turn(engine, turn.turn_id).answer == answer(turn)


def test_reanalysis_does_not_replace_trace_scope(stored, client):
    engine, turn = stored
    append_step(engine, turn.turn_id, receipt(turn))
    finish_turn(engine, turn.turn_id, answer(turn))
    new = client.post(f"/batches/{turn.scope.runs[0].batch_id}/runs").json()
    assert new["run_id"] != turn.scope.runs[0].run_id
    assert get_turn(engine, turn.turn_id).scope == turn.scope
    assert get_evidence(engine, turn.turn_id, "ev_1").source.run == turn.scope.runs[0]


def test_scope_must_reference_a_real_successful_run_in_the_correct_batch(stored):
    engine, turn = stored
    invalid_scopes = [
        PinnedScope(runs=(RunReference(batch_id=turn.scope.runs[0].batch_id, run_id="missing"),),
                    event_time=turn.scope.event_time),
        PinnedScope(runs=(RunReference(batch_id="wrong_batch", run_id=turn.scope.runs[0].run_id),),
                    event_time=turn.scope.event_time),
    ]
    for scope in invalid_scopes:
        with pytest.raises(ValueError, match="succeeded Runs"):
            start_turn(engine, question="Question", scope=scope, model_id="test", prompt_version="v1")
    with engine.connect() as connection:
        assert len(connection.execute(select(assistant_turns)).all()) == 1


def test_failed_runs_cannot_be_selected(make_client):
    from app.pipeline import Phase

    def fail(_context):
        raise RuntimeError("test failure")

    client = make_client(Phase("test", fail))
    batch = upload(client).json()
    assert batch["latest_run"]["status"] == "failed"
    scope = PinnedScope(
        runs=(RunReference(batch_id=batch["batch_id"], run_id=batch["latest_run"]["run_id"]),),
        event_time=EventTimeRange(start="2026-01-01T00:00:00Z", end="2027-01-01T00:00:00Z"),
    )
    with pytest.raises(ValueError, match="succeeded Runs"):
        start_turn(client.app.state.engine, question="Question", scope=scope,
                   model_id="test", prompt_version="v1")


def test_step_retry_is_idempotent_but_changed_receipts_are_rejected(stored):
    engine, turn = stored
    step = receipt(turn)
    append_step(engine, turn.turn_id, step)
    append_step(engine, turn.turn_id, step)
    assert list_steps(engine, turn.turn_id) == ((step,), 1)
    changed = ExecutionStep.model_validate({**step.model_dump(), "arguments": {"different": True}})
    with pytest.raises(ValueError, match="different receipt"):
        append_step(engine, turn.turn_id, changed)
    assert list_steps(engine, turn.turn_id) == ((step,), 1)


def test_evidence_insert_failure_rolls_back_the_step_and_all_its_sources(stored):
    engine, turn = stored
    step = receipt(turn)
    duplicated = ExecutionStep.model_validate({
        **step.model_dump(),
        "outcome": {**step.outcome.model_dump(), "evidence": step.outcome.evidence * 2},
    })
    with pytest.raises(IntegrityError):
        append_step(engine, turn.turn_id, duplicated)
    assert list_steps(engine, turn.turn_id) == ((), 0)
    with pytest.raises(LookupError):
        get_evidence(engine, turn.turn_id, "ev_1")
    append_step(engine, turn.turn_id, step)
    assert list_steps(engine, turn.turn_id)[1] == 1


def test_sequence_gaps_and_scope_changes_are_rejected(stored):
    engine, turn = stored
    with pytest.raises(ValueError, match="contiguous"):
        append_step(engine, turn.turn_id, receipt(turn, number=2))
    step = receipt(turn)
    altered_scope = PinnedScope(
        runs=turn.scope.runs, event_time=turn.scope.event_time,
        filters=ScopeFilters(departments=("Finance",)),
    )
    changed = ExecutionStep.model_validate({**step.model_dump(), "scope": altered_scope})
    with pytest.raises(ValueError, match="scope"):
        append_step(engine, turn.turn_id, changed)
    with pytest.raises(ValueError, match="scope"):
        finish_turn(engine, turn.turn_id, answer(turn).model_copy(update={"scope": altered_scope}))
    assert list_steps(engine, turn.turn_id) == ((), 0)


def test_out_of_scope_evidence_is_not_retained(stored):
    engine, turn = stored
    step = receipt(turn)
    source = step.outcome.evidence[0].model_copy(update={
        "run": RunReference(batch_id="another_batch", run_id="another_run")
    })
    invalid = ExecutionStep.model_validate({
        **step.model_dump(), "outcome": {**step.outcome.model_dump(), "evidence": (source,)}
    })
    with pytest.raises(ValueError, match="outside"):
        append_step(engine, turn.turn_id, invalid)
    assert list_steps(engine, turn.turn_id) == ((), 0)


def test_unknown_citation_does_not_finalize_or_publish_an_answer(stored):
    engine, turn = stored
    append_step(engine, turn.turn_id, receipt(turn))
    with pytest.raises(ValueError, match="Unknown evidence"):
        finish_turn(engine, turn.turn_id, answer(turn, "missing"))
    saved = get_turn(engine, turn.turn_id)
    assert saved.status == "running" and saved.answer is None


def test_failed_tools_prevent_success_but_remain_inspectable(stored):
    engine, turn = stored
    append_step(engine, turn.turn_id, receipt(turn))
    failure = ToolFailure(code="retrieval_failed", message="Retrieval failed; retry.")
    append_step(engine, turn.turn_id, receipt(turn, number=2, outcome=failure))
    with pytest.raises(ValueError, match="failed tool"):
        finish_turn(engine, turn.turn_id, answer(turn))
    fail_turn(engine, turn.turn_id, failure)
    saved = get_turn(engine, turn.turn_id)
    assert saved.status == "failed" and saved.answer is None and saved.failure == failure
    assert list_steps(engine, turn.turn_id)[1] == 2
    assert get_evidence(engine, turn.turn_id, "ev_1").step_id == "step_1"


@pytest.mark.parametrize("terminal", ["succeeded", "failed"])
def test_terminal_turns_cannot_be_rewritten_or_extended(stored, terminal):
    engine, turn = stored
    step = receipt(turn)
    append_step(engine, turn.turn_id, step)
    failure = ToolFailure(code="failed", message="Retry.")
    if terminal == "succeeded":
        finish_turn(engine, turn.turn_id, answer(turn))
    else:
        fail_turn(engine, turn.turn_id, failure)
    original = get_turn(engine, turn.turn_id)
    append_step(engine, turn.turn_id, step)  # An exact retry changes nothing.
    for operation in (
        lambda: append_step(engine, turn.turn_id, receipt(turn, number=2, evidence_id="ev_2")),
        lambda: finish_turn(engine, turn.turn_id, answer(turn)),
        lambda: fail_turn(engine, turn.turn_id, failure),
    ):
        with pytest.raises(ValueError, match="Finalized"):
            operation()
    assert get_turn(engine, turn.turn_id) == original


def test_evidence_lookup_is_turn_qualified(stored):
    engine, turn = stored
    append_step(engine, turn.turn_id, receipt(turn))
    another = start_turn(engine, question="Another question", scope=turn.scope,
                         model_id="test", prompt_version="v1")
    with pytest.raises(LookupError):
        get_evidence(engine, another.turn_id, "ev_1")
    append_step(engine, another.turn_id, receipt(another))
    assert get_evidence(engine, another.turn_id, "ev_1").turn_id == another.turn_id


def test_stored_json_is_a_snapshot_not_a_mutable_alias(stored):
    engine, turn = stored
    step = receipt(turn)
    append_step(engine, turn.turn_id, step)
    step.arguments["record_id"] = "changed"
    step.outcome.data["event_count"] = 999
    saved = list_steps(engine, turn.turn_id)[0][0]
    assert saved.arguments["record_id"] == "event_1"
    assert saved.outcome.data["event_count"] == 1
    saved.arguments["record_id"] = "changed_again"
    assert list_steps(engine, turn.turn_id)[0][0].arguments["record_id"] == "event_1"


def test_concurrent_exact_step_retries_record_one_receipt(stored):
    engine, turn = stored
    step = receipt(turn)
    ready = Barrier(2)

    def append():
        ready.wait(timeout=5)
        append_step(engine, turn.turn_id, step)

    with ThreadPoolExecutor(max_workers=2) as workers:
        futures = [workers.submit(append) for _ in range(2)]
        for future in futures:
            future.result(timeout=10)
    assert list_steps(engine, turn.turn_id) == ((step,), 1)


def test_append_and_finalization_are_serialized(stored):
    engine, turn = stored
    append_step(engine, turn.turn_id, receipt(turn))
    ready = Barrier(2)

    def append():
        ready.wait(timeout=5)
        try:
            append_step(engine, turn.turn_id, receipt(turn, number=2, evidence_id="ev_2"))
            return True
        except ValueError as error:
            assert "Finalized" in str(error)
            return False

    def finish():
        ready.wait(timeout=5)
        finish_turn(engine, turn.turn_id, answer(turn))

    with ThreadPoolExecutor(max_workers=2) as workers:
        appended = workers.submit(append)
        finished = workers.submit(finish)
        did_append = appended.result(timeout=10)
        finished.result(timeout=10)
    assert get_turn(engine, turn.turn_id).status == "succeeded"
    assert list_steps(engine, turn.turn_id)[1] == (2 if did_append else 1)


def test_reusing_evidence_id_rolls_back_only_the_new_step(stored):
    engine, turn = stored
    first = receipt(turn)
    append_step(engine, turn.turn_id, first)
    with pytest.raises(IntegrityError):
        append_step(engine, turn.turn_id, receipt(turn, number=2))
    assert list_steps(engine, turn.turn_id) == ((first,), 1)
    assert get_evidence(engine, turn.turn_id, "ev_1").step_id == "step_1"


def test_interrupted_turn_cleanup_preserves_receipts_and_terminal_turns(stored):
    engine, turn = stored
    append_step(engine, turn.turn_id, receipt(turn))
    completed = start_turn(engine, question="Completed question", scope=turn.scope,
                           model_id="test", prompt_version="v1")
    fail_turn(engine, completed.turn_id, ToolFailure(code="test", message="Original failure."))
    before = get_turn(engine, completed.turn_id)
    assert fail_interrupted_turns(engine) == 1
    assert fail_interrupted_turns(engine) == 0
    saved = get_turn(engine, turn.turn_id)
    assert saved.status == "failed" and saved.answer is None
    assert saved.failure.code == "turn_interrupted"
    assert list_steps(engine, turn.turn_id)[1] == 1
    assert get_evidence(engine, turn.turn_id, "ev_1").step_id == "step_1"
    assert get_turn(engine, completed.turn_id) == before


def test_database_rejects_evidence_without_a_producing_step(stored):
    engine, turn = stored
    with pytest.raises(IntegrityError):
        with engine.begin() as connection:
            connection.execute(assistant_evidence.insert().values(
                turn_id=turn.turn_id, evidence_id="invented", step_id="missing", source={},
            ))


def test_migration_upgrades_existing_analysis_data_without_replacing_it(client):
    from alembic import command
    from alembic.config import Config
    from app.db.engine import MIGRATIONS_DIR

    batch = upload(client).json()
    engine = client.app.state.engine
    with engine.begin() as connection:
        config = Config()
        config.set_main_option("script_location", str(MIGRATIONS_DIR))
        config.attributes["connection"] = connection
        command.downgrade(config, "0004")
    migrate(engine)
    assert client.get(f"/runs/{batch['latest_run']['run_id']}").json() == batch["latest_run"]
    # The migrated tables also enforce state consistency, not just the Python API.
    with pytest.raises(IntegrityError):
        with engine.begin() as connection:
            connection.execute(assistant_turns.insert().values(
                turn_id="invalid", question="Question", scope={}, model_id="test",
                prompt_version="v1", status="succeeded", started_at="2026-11-05T00:00:00Z",
            ))


def test_step_pagination_is_ordered_bounded_and_reports_total(stored):
    engine, turn = stored
    steps = [receipt(turn, number=i, evidence_id=f"ev_{i}") for i in range(1, 4)]
    for step in steps:
        append_step(engine, turn.turn_id, step)
    assert list_steps(engine, turn.turn_id, limit=1, offset=1) == ((steps[1],), 3)
    assert list_steps(engine, turn.turn_id, offset=9) == ((), 3)
    for params in ({"limit": 0}, {"limit": 101}, {"offset": -1}):
        with pytest.raises(ValueError):
            list_steps(engine, turn.turn_id, **params)
    with pytest.raises(LookupError):
        list_steps(engine, "missing")
