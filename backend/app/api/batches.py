from fastapi import APIRouter, Request, Response, UploadFile, status
from pydantic import BaseModel

from app.batches import Batch, get_batch, ingest_upload
from app.errors import AppError
from app.ingestion.activity import UploadRejected

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

    @classmethod
    def of(cls, batch: Batch) -> "BatchOut":
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
        )


@router.post("", status_code=status.HTTP_201_CREATED)
async def upload_batch(
    request: Request, response: Response, file: UploadFile
) -> BatchOut:
    content = await file.read()
    try:
        batch, created = ingest_upload(
            request.app.state.engine,
            request.app.state.settings,
            file.filename or "upload.csv",
            content,
        )
    except UploadRejected as rejected:
        raise AppError(
            422,
            "invalid_upload",
            "The upload is invalid; no Batch was created.",
            {"errors": rejected.errors},
        ) from rejected
    if not created:
        response.status_code = status.HTTP_200_OK
    return BatchOut.of(batch)


@router.get("/{batch_id}")
def read_batch(request: Request, batch_id: str) -> BatchOut:
    with request.app.state.engine.connect() as connection:
        batch = get_batch(connection, batch_id)
    if batch is None:
        raise AppError(404, "batch_not_found", "Batch not found.")
    return BatchOut.of(batch)
