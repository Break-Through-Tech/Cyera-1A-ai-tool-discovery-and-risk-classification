"""Retain safe provider metadata and model-call lifecycle records.

Revision ID: 0006
Revises: 0005
"""

import sqlalchemy as sa
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "assistant_model_calls",
        sa.Column(
            "turn_id",
            sa.String,
            sa.ForeignKey("assistant_turns.turn_id"),
            primary_key=True,
        ),
        sa.Column("sequence", sa.Integer, primary_key=True),
        sa.Column("provider", sa.String, nullable=False),
        sa.Column("requested_model", sa.String, nullable=False),
        sa.Column("context_sha256", sa.String(64), nullable=False),
        sa.Column("started_at", sa.String, nullable=False),
        sa.Column("completed_at", sa.String),
        sa.Column("status", sa.String, nullable=False),
        sa.Column("metadata", sa.JSON, nullable=False),
        sa.Column("failure", sa.JSON(none_as_null=True)),
        sa.CheckConstraint("sequence >= 1", name="ck_assistant_model_calls_sequence"),
        sa.CheckConstraint(
            "length(context_sha256) = 64", name="ck_assistant_model_calls_hash"
        ),
        sa.CheckConstraint(
            "(status = 'running' AND completed_at IS NULL AND failure IS NULL) OR "
            "(status = 'succeeded' AND completed_at IS NOT NULL AND failure IS NULL) OR "
            "(status = 'failed' AND completed_at IS NOT NULL AND failure IS NOT NULL)",
            name="ck_assistant_model_calls_state",
        ),
    )


def downgrade() -> None:
    op.drop_table("assistant_model_calls")
