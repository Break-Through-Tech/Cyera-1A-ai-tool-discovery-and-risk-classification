from sqlalchemy import Column, ForeignKey, Index, Integer, MetaData, String, Table

metadata = MetaData()

# Timestamps are stored as UTC text in the uploaded `YYYY-MM-DDTHH:MM:SSZ` form so
# they sort lexicographically in SQLite.

batches = Table(
    "batches",
    metadata,
    Column("batch_id", String, primary_key=True),
    Column("original_filename", String, nullable=False),
    Column("raw_artifact_path", String, nullable=False),
    Column("sha256", String(64), nullable=False, unique=True),
    Column("schema_version", String, nullable=False),
    Column("uploaded_at", String, nullable=False),
    Column("activity_start", String, nullable=False),
    Column("activity_end", String, nullable=False),
    Column("event_count", Integer, nullable=False),
)

activity_events = Table(
    "activity_events",
    metadata,
    Column("batch_id", String, ForeignKey("batches.batch_id"), primary_key=True),
    Column("event_id", String, primary_key=True),
    Column("occurred_at", String, nullable=False),
    Column("employee_id", String, nullable=False),
    Column("department", String, nullable=False),
    Column("job_role", String),
    Column("application_name", String, nullable=False),
    Column("domain", String, nullable=False),
    Column("event_type", String),
    Column("usage_purpose", String),
    Column("data_sensitivity_tier", String),
    Index("ix_activity_events_batch_time", "batch_id", "occurred_at"),
)
