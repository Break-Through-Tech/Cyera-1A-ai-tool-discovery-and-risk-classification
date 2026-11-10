"""Transactional trace storage for trusted backend callers, not a public access API."""

from typing import Literal
from uuid import uuid4

from pydantic import AwareDatetime, TypeAdapter
from sqlalchemy import Connection, Engine, func, insert, select, update

from app.assistant.contracts import (
    AggregateEvidence,
    AssistantResponse,
    Contract,
    Evidence,
    ExecutionStep,
    GroundedAnswer,
    PinnedScope,
    RecordEvidence,
    Text,
    ToolFailure,
    ToolSuccess,
    validate_answer_references,
)
from app.clock import utc_now
from app.db.tables import (
    analysis_runs,
    assistant_evidence,
    assistant_steps,
    assistant_turns,
)

_evidence_adapter = TypeAdapter(Evidence)
_text_adapter = TypeAdapter(Text)


class StoredTurn(Contract):
    turn_id: Text
    question: Text
    scope: PinnedScope
    model_id: Text
    prompt_version: Text
    status: Literal["running", "succeeded", "failed"]
    started_at: AwareDatetime
    completed_at: AwareDatetime | None
    answer: AssistantResponse | None
    failure: ToolFailure | None


class StoredEvidence(Contract):
    turn_id: Text
    step_id: Text
    source: Evidence


def start_turn(
    engine: Engine,
    *,
    question: str,
    scope: PinnedScope,
    model_id: str,
    prompt_version: str,
) -> StoredTurn:
    turn_id = f"turn_{uuid4().hex}"
    values = {
        "turn_id": turn_id,
        "question": _text_adapter.validate_python(question),
        "scope": scope.model_dump(mode="json"),
        "model_id": _text_adapter.validate_python(model_id),
        "prompt_version": _text_adapter.validate_python(prompt_version),
        "status": "running",
        "started_at": utc_now(),
    }
    with engine.begin() as connection:
        for reference in scope.runs:
            exists = connection.execute(
                select(analysis_runs.c.run_id).where(
                    analysis_runs.c.run_id == reference.run_id,
                    analysis_runs.c.batch_id == reference.batch_id,
                    analysis_runs.c.status == "succeeded",
                )
            ).first()
            if exists is None:
                raise ValueError("Scope requires existing succeeded Runs in their named Batches")
        connection.execute(insert(assistant_turns).values(**values))
        return _turn(connection, turn_id)


def get_turn(engine: Engine, turn_id: str) -> StoredTurn:
    with engine.connect() as connection:
        return _turn(connection, turn_id)


def append_step(engine: Engine, turn_id: str, step: ExecutionStep) -> None:
    """Append a completed receipt and its evidence atomically.

    Exact retries are no-ops, even after finalization. Reusing a step ID with a
    different receipt, sequence gaps, or reused evidence IDs are conflicts.
    """
    receipt = step.model_dump(mode="json")
    with engine.begin() as connection:
        turn = _locked_turn(connection, turn_id)
        existing = connection.execute(
            select(assistant_steps.c.receipt).where(
                assistant_steps.c.turn_id == turn_id,
                assistant_steps.c.step_id == step.step_id,
            )
        ).scalar_one_or_none()
        if existing is not None:
            if existing != receipt:
                raise ValueError("Step ID already has a different receipt")
            return
        _require_running(turn)
        if step.scope != turn.scope:
            raise ValueError("Step scope must match the pinned turn scope")
        count = connection.execute(
            select(func.count()).select_from(assistant_steps).where(
                assistant_steps.c.turn_id == turn_id
            )
        ).scalar_one()
        if step.sequence != count + 1:
            raise ValueError("Step sequence must be contiguous and append-only")
        connection.execute(insert(assistant_steps).values(
            turn_id=turn_id, step_id=step.step_id, sequence=step.sequence, receipt=receipt,
        ))
        if isinstance(step.outcome, ToolSuccess):
            for source in step.outcome.evidence:
                _check_source_scope(source, turn.scope)
                connection.execute(insert(assistant_evidence).values(
                    turn_id=turn_id, step_id=step.step_id, evidence_id=source.evidence_id,
                    source=source.model_dump(mode="json"),
                ))


def list_steps(
    engine: Engine, turn_id: str, *, limit: int = 50, offset: int = 0
) -> tuple[tuple[ExecutionStep, ...], int]:
    if not 1 <= limit <= 100 or offset < 0:
        raise ValueError("Use a limit from 1 to 100 and a nonnegative offset")
    with engine.connect() as connection:
        _turn(connection, turn_id)
        where = assistant_steps.c.turn_id == turn_id
        rows = connection.execute(
            select(assistant_steps.c.receipt).where(where)
            .order_by(assistant_steps.c.sequence).limit(limit).offset(offset)
        ).scalars()
        steps = tuple(ExecutionStep.model_validate(row) for row in rows)
        total = connection.execute(
            select(func.count()).select_from(assistant_steps).where(where)
        ).scalar_one()
        return steps, total


def get_evidence(engine: Engine, turn_id: str, evidence_id: str) -> StoredEvidence:
    with engine.connect() as connection:
        row = connection.execute(select(assistant_evidence).where(
            assistant_evidence.c.turn_id == turn_id,
            assistant_evidence.c.evidence_id == evidence_id,
        )).mappings().one_or_none()
        if row is None:
            raise LookupError("Evidence not found in this turn")
        return StoredEvidence(
            turn_id=turn_id, step_id=row["step_id"], source=row["source"]
        )


def finish_turn(engine: Engine, turn_id: str, answer: AssistantResponse) -> None:
    with engine.begin() as connection:
        turn = _locked_turn(connection, turn_id)
        _require_running(turn)
        if answer.scope != turn.scope:
            raise ValueError("Answer scope must match the pinned turn scope")
        receipts = connection.execute(select(assistant_steps.c.receipt).where(
            assistant_steps.c.turn_id == turn_id
        )).scalars()
        for receipt in receipts:
            if receipt["outcome"]["status"] == "failed":
                raise ValueError("A failed tool execution prevents a substantive answer")
        sources = tuple(
            _evidence_adapter.validate_python(source)
            for source in connection.execute(select(assistant_evidence.c.source).where(
                assistant_evidence.c.turn_id == turn_id
            )).scalars()
        )
        if isinstance(answer, GroundedAnswer):
            validate_answer_references(answer, sources)
        _finalize(connection, turn_id, "succeeded", answer=answer.model_dump(mode="json"))


def fail_turn(engine: Engine, turn_id: str, failure: ToolFailure) -> None:
    with engine.begin() as connection:
        _require_running(_locked_turn(connection, turn_id))
        _finalize(connection, turn_id, "failed", failure=failure.model_dump(mode="json"))


def fail_interrupted_turns(engine: Engine) -> int:
    """Fail abandoned turns before a single server process accepts new work.

    Not safe to call while another process is executing turns. Startup wiring
    belongs to the orchestration phase; this function does not resume work.
    """
    failure = ToolFailure(
        code="turn_interrupted", message="Investigation was interrupted; retry."
    )
    with engine.begin() as connection:
        return connection.execute(
            update(assistant_turns).where(assistant_turns.c.status == "running")
            .values(status="failed", completed_at=utc_now(), failure=failure.model_dump(mode="json"))
        ).rowcount


def _turn(connection: Connection, turn_id: str) -> StoredTurn:
    row = connection.execute(select(assistant_turns).where(
        assistant_turns.c.turn_id == turn_id
    )).mappings().one_or_none()
    if row is None:
        raise LookupError("Assistant turn not found")
    return StoredTurn.model_validate(dict(row))


def _require_running(turn: StoredTurn) -> None:
    if turn.status != "running":
        raise ValueError("Finalized turns cannot be changed")


def _locked_turn(connection: Connection, turn_id: str) -> StoredTurn:
    # SQLite's legacy driver does not start a transaction for SELECT alone.
    # A no-op write serializes appends/finalization before reading the turn.
    changed = connection.execute(
        update(assistant_turns)
        .where(assistant_turns.c.turn_id == turn_id)
        .values(status=assistant_turns.c.status)
    ).rowcount
    if changed != 1:
        raise LookupError("Assistant turn not found")
    return _turn(connection, turn_id)


def _check_source_scope(source: Evidence, scope: PinnedScope) -> None:
    if isinstance(source, RecordEvidence) and source.run not in scope.runs:
        raise ValueError("Record evidence is outside the pinned Runs")
    if isinstance(source, AggregateEvidence) and source.scope != scope:
        raise ValueError("Aggregate evidence must match the pinned scope")


def _finalize(connection: Connection, turn_id: str, status: str, **result) -> None:
    changed = connection.execute(
        update(assistant_turns)
        .where(assistant_turns.c.turn_id == turn_id, assistant_turns.c.status == "running")
        .values(status=status, completed_at=utc_now(), **result)
    ).rowcount
    if changed != 1:
        raise ValueError("Finalized turns cannot be changed")
