from fastapi import APIRouter, Request
from pydantic import BaseModel

from app.errors import AppError
from app.runs import Run, get_run

router = APIRouter(prefix="/runs", tags=["runs"])


class RunFailure(BaseModel):
    summary: str
    phase: str | None


class RunOut(BaseModel):
    run_id: str
    batch_id: str
    attempt_number: int
    status: str
    started_at: str
    completed_at: str | None
    versions: dict[str, str]
    code_commit: str | None
    failure: RunFailure | None

    @classmethod
    def of(cls, run: Run) -> "RunOut":
        failure = None
        if run.status == "failed":
            failure = RunFailure(summary=run.failure_summary, phase=run.failure_phase)
        return cls(
            run_id=run.run_id,
            batch_id=run.batch_id,
            attempt_number=run.attempt_number,
            status=run.status,
            started_at=run.started_at,
            completed_at=run.completed_at,
            versions=run.versions,
            code_commit=run.code_commit,
            failure=failure,
        )


@router.get("/{run_id}")
def read_run(request: Request, run_id: str) -> RunOut:
    with request.app.state.engine.connect() as connection:
        run = get_run(connection, run_id)
    if run is None:
        raise AppError(404, "run_not_found", "Analysis Run not found.")
    return RunOut.of(run)
