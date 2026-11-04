"""Create usage_context_assessments

Revision ID: 0004
Revises: 0003
"""

import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "usage_context_assessments",
        sa.Column(
            "run_id", sa.String, sa.ForeignKey("analysis_runs.run_id"), primary_key=True
        ),
        sa.Column("context_number", sa.Integer, primary_key=True),
        sa.Column("tool_id", sa.String, nullable=False),
        sa.Column("application_name", sa.String, nullable=False),
        sa.Column("domain", sa.String, nullable=False),
        sa.Column("category", sa.String),
        sa.Column("department", sa.String, nullable=False),
        sa.Column("usage_purpose", sa.String, nullable=False),
        sa.Column("data_sensitivity_tier", sa.String, nullable=False),
        sa.Column("event_ids", sa.JSON, nullable=False),
        sa.Column("event_count", sa.Integer, nullable=False),
        sa.Column("first_observed_at", sa.String, nullable=False),
        sa.Column("last_observed_at", sa.String, nullable=False),
        sa.Column("metadata_id", sa.String),
        sa.Column("facts", sa.JSON, nullable=False),
        sa.Column("tier", sa.String, nullable=False),
        sa.Column("reason_codes", sa.JSON, nullable=False),
        sa.Column("unknown_facts", sa.JSON, nullable=False),
        sa.Column("investigation_flag", sa.Boolean, nullable=False),
        sa.Column("flag_reasons", sa.JSON, nullable=False),
        sa.Column("rule_version", sa.String, nullable=False),
        sa.CheckConstraint(
            "tier IN ('High', 'Medium', 'Lower', 'unresolved')",
            name="ck_usage_context_assessments_tier",
        ),
    )
    op.create_index(
        "ix_usage_context_assessments_run_tier",
        "usage_context_assessments",
        ["run_id", "tier"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_usage_context_assessments_run_tier", table_name="usage_context_assessments"
    )
    op.drop_table("usage_context_assessments")
