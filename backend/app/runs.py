import logging
import uuid
from dataclasses import dataclass

from sqlalchemy import Connection, Engine, func, insert, select, update
from sqlalchemy.exc import IntegrityError

from app.clock import utc_now
from app.db.tables import analysis_runs
from app.pipeline import Pipeline, RunContext

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Run:
    run_id: str
    batch_id: str
    attempt_number: int
    status: str
    started_at: str
    completed_at: str | None
    versions: dict[str, str]
    code_commit: str | None
    failure_summary: str | None
    failure_phase: str | None


class RunInProgress(Exception):
    """The Batch already has a running Analysis Run; nothing is queued."""


def analyze_batch(
    engine: Engine, pipeline: Pipeline, code_commit: str | None, batch_id: str
) -> str:
    """Record a running Analysis Run for the Batch, execute it, and return its ID."""
    run_id = f"run_{uuid.uuid4().hex}"
    try:
        with engine.begin() as connection:
            attempt_number = connection.execute(
                select(
                    func.coalesce(func.max(analysis_runs.c.attempt_number), 0) + 1
                ).where(analysis_runs.c.batch_id == batch_id)
            ).scalar_one()
            connection.execute(
                insert(analysis_runs).values(
                    run_id=run_id,
                    batch_id=batch_id,
                    attempt_number=attempt_number,
                    status="running",
                    started_at=utc_now(),
                    versions=dict(pipeline.versions),
                    code_commit=code_commit,
                )
            )
    except IntegrityError as error:
        raise RunInProgress(batch_id) from error

    context = RunContext(run_id=run_id, batch_id=batch_id, engine=engine)
    for phase in pipeline.phases:
        try:
            phase.run(context)
        except Exception:
            logger.exception("Analysis Run %s failed in phase %s", run_id, phase.name)
            _finish(
                engine,
                run_id,
                "failed",
                failure_summary=f"Analysis failed during the {phase.name} phase.",
                failure_phase=phase.name,
            )
            return run_id
    _finish(engine, run_id, "succeeded")
    return run_id


def fail_interrupted_runs(engine: Engine) -> None:
    """Fail Runs left running by a previous process; they are never resumed.

    Only safe with one server process, which is the supported deployment.
    """
    with engine.begin() as connection:
        connection.execute(
            update(analysis_runs)
            .where(analysis_runs.c.status == "running")
            .values(
                status="failed",
                completed_at=utc_now(),
                failure_summary="Analysis was interrupted before completion.",
                failure_phase=None,
            )
        )


def get_run(connection: Connection, run_id: str) -> Run | None:
    row = connection.execute(
        select(analysis_runs).where(analysis_runs.c.run_id == run_id)
    ).one_or_none()
    return Run(**row._mapping) if row else None


def list_runs(
    connection: Connection, batch_id: str, limit: int, offset: int
) -> tuple[list[Run], int]:
    """A Batch's Run history, newest attempt first, and its total size."""
    where = analysis_runs.c.batch_id == batch_id
    rows = connection.execute(
        select(analysis_runs)
        .where(where)
        .order_by(analysis_runs.c.attempt_number.desc())
        .limit(limit)
        .offset(offset)
    ).all()
    total = connection.execute(
        select(func.count()).select_from(analysis_runs).where(where)
    ).scalar_one()
    return [Run(**row._mapping) for row in rows], total


def latest_run(connection: Connection, batch_id: str, status: str | None = None) -> Run | None:
    query = select(analysis_runs).where(analysis_runs.c.batch_id == batch_id)
    if status is not None:
        query = query.where(analysis_runs.c.status == status)
    row = connection.execute(
        query.order_by(analysis_runs.c.attempt_number.desc()).limit(1)
    ).one_or_none()
    return Run(**row._mapping) if row else None


def _finish(engine: Engine, run_id: str, status: str, **failure: str) -> None:
    with engine.begin() as connection:
        connection.execute(
            update(analysis_runs)
            .where(analysis_runs.c.run_id == run_id, analysis_runs.c.status == "running")
            .values(status=status, completed_at=utc_now(), **failure)
        )
