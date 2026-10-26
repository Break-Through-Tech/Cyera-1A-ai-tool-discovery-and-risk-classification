from sqlalchemy import (
    JSON,
    CheckConstraint,
    Column,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    String,
    Table,
    UniqueConstraint,
    text,
)

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

analysis_runs = Table(
    "analysis_runs",
    metadata,
    Column("run_id", String, primary_key=True),
    Column("batch_id", String, ForeignKey("batches.batch_id"), nullable=False),
    Column("attempt_number", Integer, nullable=False),
    Column("status", String, nullable=False),
    Column("started_at", String, nullable=False),
    Column("completed_at", String),
    Column("versions", JSON, nullable=False),
    Column("code_commit", String),
    Column("failure_summary", String),
    Column("failure_phase", String),
    CheckConstraint(
        "status IN ('running', 'succeeded', 'failed')", name="ck_analysis_runs_status"
    ),
    UniqueConstraint("batch_id", "attempt_number"),
    # At most one running Run per Batch; a second start fails on insert.
    Index(
        "ux_analysis_runs_one_running_per_batch",
        "batch_id",
        unique=True,
        sqlite_where=text("status = 'running'"),
    ),
)
