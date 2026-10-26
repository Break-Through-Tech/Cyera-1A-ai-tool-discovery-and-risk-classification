from fastapi import APIRouter, Request, Response, UploadFile, status
from pydantic import BaseModel
from sqlalchemy import Connection

from app.api.runs import RunOut
from app.batches import Batch, get_batch, ingest_upload
from app.errors import AppError
from app.ingestion.activity import UploadRejected
from app.runs import RunInProgress, analyze_batch, get_run, latest_run

router = APIRouter(prefix="/batches", tags=["batches"])


class ActivityPeriod(BaseModel):
    start: str
    end: str


class BatchOut(BaseModel):
    batch_id: str
    original_filename: str
    sha256: str
    schema_version: str
    uploaded_at: str
    activity_period: ActivityPeriod
    event_count: int
    latest_run: RunOut | None
    latest_successful_run_id: str | None

    @classmethod
    def load(cls, connection: Connection, batch: Batch) -> "BatchOut":
        attempted = latest_run(connection, batch.batch_id)
        succeeded = latest_run(connection, batch.batch_id, status="succeeded")
        return cls(
            batch_id=batch.batch_id,
            original_filename=batch.original_filename,
            sha256=batch.sha256,
            schema_version=batch.schema_version,
            uploaded_at=batch.uploaded_at,
            activity_period=ActivityPeriod(
                start=batch.activity_start, end=batch.activity_end
            ),
            event_count=batch.event_count,
            latest_run=RunOut.of(attempted) if attempted else None,
            latest_successful_run_id=succeeded.run_id if succeeded else None,
        )


@router.post("", status_code=status.HTTP_201_CREATED)
def upload_batch(request: Request, response: Response, file: UploadFile) -> BatchOut:
    state = request.app.state
    try:
        batch, created = ingest_upload(
            state.engine,
            state.settings,
            file.filename or "upload.csv",
            file.file.read(),
        )
    except UploadRejected as rejected:
        raise AppError(
            422,
            "invalid_upload",
            "The upload is invalid; no Batch was created.",
            {"errors": rejected.errors},
        ) from rejected

    if created:
        analyze_batch(state.engine, state.pipeline, state.code_commit, batch.batch_id)
    else:
        response.status_code = status.HTTP_200_OK
    with state.engine.connect() as connection:
        return BatchOut.load(connection, batch)


@router.get("/{batch_id}")
def read_batch(request: Request, batch_id: str) -> BatchOut:
    with request.app.state.engine.connect() as connection:
        return BatchOut.load(connection, _require_batch(connection, batch_id))


@router.post("/{batch_id}/runs", status_code=status.HTTP_201_CREATED)
def reanalyze_batch(request: Request, batch_id: str) -> RunOut:
    state = request.app.state
    with state.engine.connect() as connection:
        _require_batch(connection, batch_id)
    try:
        run_id = analyze_batch(
            state.engine, state.pipeline, state.code_commit, batch_id
        )
    except RunInProgress as conflict:
        raise AppError(
            409, "run_in_progress", "This Batch already has a running Analysis Run."
        ) from conflict
    with state.engine.connect() as connection:
        return RunOut.of(get_run(connection, run_id))


def _require_batch(connection: Connection, batch_id: str) -> Batch:
    batch = get_batch(connection, batch_id)
    if batch is None:
        raise AppError(404, "batch_not_found", "Batch not found.")
    return batch
