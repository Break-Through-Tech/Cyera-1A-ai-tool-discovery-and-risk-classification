import hashlib
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import Connection, Engine, insert, select

from app.config import Settings
from app.db.tables import activity_events, batches
from app.ingestion.activity import SCHEMA_VERSION, parse_activity


@dataclass(frozen=True)
class Batch:
    batch_id: str
    original_filename: str
    sha256: str
    schema_version: str
    uploaded_at: str
    activity_start: str
    activity_end: str
    event_count: int


def ingest_upload(
    engine: Engine, settings: Settings, filename: str, content: bytes
) -> tuple[Batch, bool]:
    """Create a Batch from an upload, or reopen the one with identical bytes.

    Returns the Batch and whether it was newly created.
    """
    sha256 = hashlib.sha256(content).hexdigest()
    with engine.begin() as connection:
        existing = _find_by_sha256(connection, sha256)
        if existing is not None:
            return existing, False

        events = parse_activity(content)
        timestamps = [event["occurred_at"] for event in events]
        batch_id = f"bat_{uuid.uuid4().hex}"
        raw_artifact_path = f"uploads/{sha256}.csv"

        settings.uploads_dir.mkdir(parents=True, exist_ok=True)
        (settings.data_dir / raw_artifact_path).write_bytes(content)

        connection.execute(
            insert(batches).values(
                batch_id=batch_id,
                original_filename=filename,
                raw_artifact_path=raw_artifact_path,
                sha256=sha256,
                schema_version=SCHEMA_VERSION,
                uploaded_at=datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
                activity_start=min(timestamps),
                activity_end=max(timestamps),
                event_count=len(events),
            )
        )
        connection.execute(
            insert(activity_events), [{"batch_id": batch_id, **e} for e in events]
        )
        return get_batch(connection, batch_id), True


def get_batch(connection: Connection, batch_id: str) -> Batch | None:
    row = connection.execute(
        select(batches).where(batches.c.batch_id == batch_id)
    ).one_or_none()
    return _to_batch(row) if row else None


def _find_by_sha256(connection: Connection, sha256: str) -> Batch | None:
    row = connection.execute(
        select(batches).where(batches.c.sha256 == sha256)
    ).one_or_none()
    return _to_batch(row) if row else None


def _to_batch(row) -> Batch:
    return Batch(
        batch_id=row.batch_id,
        original_filename=row.original_filename,
        sha256=row.sha256,
        schema_version=row.schema_version,
        uploaded_at=row.uploaded_at,
        activity_start=row.activity_start,
        activity_end=row.activity_end,
        event_count=row.event_count,
    )
