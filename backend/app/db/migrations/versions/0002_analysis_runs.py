"""Create analysis_runs

Revision ID: 0002
Revises: 0001
"""

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "analysis_runs",
        sa.Column("run_id", sa.String, primary_key=True),
        sa.Column(
            "batch_id", sa.String, sa.ForeignKey("batches.batch_id"), nullable=False
        ),
        sa.Column("attempt_number", sa.Integer, nullable=False),
        sa.Column("status", sa.String, nullable=False),
        sa.Column("started_at", sa.String, nullable=False),
        sa.Column("completed_at", sa.String),
        sa.Column("versions", sa.JSON, nullable=False),
        sa.Column("code_commit", sa.String),
        sa.Column("failure_summary", sa.String),
        sa.Column("failure_phase", sa.String),
        sa.CheckConstraint(
            "status IN ('running', 'succeeded', 'failed')",
            name="ck_analysis_runs_status",
        ),
        sa.UniqueConstraint("batch_id", "attempt_number"),
    )
    op.create_index(
        "ux_analysis_runs_one_running_per_batch",
        "analysis_runs",
        ["batch_id"],
        unique=True,
        sqlite_where=sa.text("status = 'running'"),
    )


def downgrade() -> None:
    op.drop_index("ux_analysis_runs_one_running_per_batch", table_name="analysis_runs")
    op.drop_table("analysis_runs")
