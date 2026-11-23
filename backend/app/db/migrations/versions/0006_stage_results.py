"""Persist per-Run stage results: Tool Candidates, AI determinations, categories, captures.

Revision ID: 0006
Revises: 0005
"""

import sqlalchemy as sa
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None

_CANDIDATE_FK = (
    ["run_id", "candidate_number"],
    ["tool_candidates.run_id", "tool_candidates.candidate_number"],
)


def upgrade() -> None:
    op.create_table(
        "tool_candidates",
        sa.Column(
            "run_id", sa.String, sa.ForeignKey("analysis_runs.run_id"), primary_key=True
        ),
        sa.Column("candidate_number", sa.Integer, primary_key=True),
        sa.Column("domain", sa.String, nullable=False),
        sa.Column("application_names", sa.JSON, nullable=False),
        sa.Column("event_ids", sa.JSON, nullable=False),
        sa.Column("event_count", sa.Integer, nullable=False),
        sa.Column("outcome", sa.String, nullable=False),
        sa.Column("tool_id", sa.String),
        sa.Column("basis", sa.String),
        sa.Column("reason", sa.String),
        sa.Column("catalog_tool_ids", sa.JSON, nullable=False),
        sa.Column("metadata_id", sa.String),
    )
    op.create_index("ix_tool_candidates_run_tool", "tool_candidates", ["run_id", "tool_id"])
    op.create_table(
        "ai_determinations",
        sa.Column("run_id", sa.String, primary_key=True),
        sa.Column("candidate_number", sa.Integer, primary_key=True),
        sa.Column("determination", sa.String, nullable=False),
        sa.Column("stage", sa.String, nullable=False),
        sa.Column("reason", sa.String),
        sa.Column("model", sa.String),
        sa.Column("probabilities", sa.JSON(none_as_null=True)),
        sa.Column("evidence", sa.JSON, nullable=False),
        sa.Column("needs_review", sa.Boolean, nullable=False),
        sa.Column("source", sa.JSON(none_as_null=True)),
        sa.Column("text_supplied", sa.Boolean),
        sa.ForeignKeyConstraint(*_CANDIDATE_FK),
    )
    op.create_table(
        "category_classifications",
        sa.Column("run_id", sa.String, primary_key=True),
        sa.Column("candidate_number", sa.Integer, primary_key=True),
        sa.Column("outcome", sa.String, nullable=False),
        sa.Column("method", sa.String),
        sa.Column("category", sa.String),
        sa.Column("reason", sa.String),
        sa.Column("share", sa.Float),
        sa.Column("neighbors", sa.JSON, nullable=False),
        sa.Column("source", sa.JSON(none_as_null=True)),
        sa.ForeignKeyConstraint(*_CANDIDATE_FK),
    )
    op.create_table(
        "website_captures",
        sa.Column(
            "run_id", sa.String, sa.ForeignKey("analysis_runs.run_id"), primary_key=True
        ),
        sa.Column("domain", sa.String, primary_key=True),
        sa.Column("requested_url", sa.String, nullable=False),
        sa.Column("captured_at", sa.String, nullable=False),
        sa.Column("outcome", sa.String, nullable=False),
        sa.Column("detail", sa.String),
        sa.Column("final_url", sa.String),
        sa.Column("title", sa.String),
        sa.Column("page_metadata", sa.JSON, nullable=False),
        sa.Column("headings", sa.JSON, nullable=False),
        sa.Column("main_text", sa.String, nullable=False),
    )


def downgrade() -> None:
    op.drop_table("website_captures")
    op.drop_table("category_classifications")
    op.drop_table("ai_determinations")
    op.drop_index("ix_tool_candidates_run_tool", table_name="tool_candidates")
    op.drop_table("tool_candidates")
