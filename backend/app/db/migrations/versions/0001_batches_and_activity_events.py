"""Create batches and activity_events

Revision ID: 0001
Revises:
"""

import sqlalchemy as sa
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "batches",
        sa.Column("batch_id", sa.String, primary_key=True),
        sa.Column("original_filename", sa.String, nullable=False),
        sa.Column("raw_artifact_path", sa.String, nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False, unique=True),
        sa.Column("schema_version", sa.String, nullable=False),
        sa.Column("uploaded_at", sa.String, nullable=False),
        sa.Column("activity_start", sa.String, nullable=False),
        sa.Column("activity_end", sa.String, nullable=False),
        sa.Column("event_count", sa.Integer, nullable=False),
    )
    op.create_table(
        "activity_events",
        sa.Column(
            "batch_id",
            sa.String,
            sa.ForeignKey("batches.batch_id"),
            primary_key=True,
        ),
        sa.Column("event_id", sa.String, primary_key=True),
        sa.Column("occurred_at", sa.String, nullable=False),
        sa.Column("employee_id", sa.String, nullable=False),
        sa.Column("department", sa.String, nullable=False),
        sa.Column("job_role", sa.String),
        sa.Column("application_name", sa.String, nullable=False),
        sa.Column("domain", sa.String, nullable=False),
        sa.Column("event_type", sa.String),
        sa.Column("usage_purpose", sa.String),
        sa.Column("data_sensitivity_tier", sa.String),
    )
    op.create_index(
        "ix_activity_events_batch_time", "activity_events", ["batch_id", "occurred_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_activity_events_batch_time", table_name="activity_events")
    op.drop_table("activity_events")
    op.drop_table("batches")
