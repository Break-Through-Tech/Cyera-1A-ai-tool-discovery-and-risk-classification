"""Persist assistant turns, completed steps, and producing-step evidence links.

Revision ID: 0005
Revises: 0004
"""

import sqlalchemy as sa
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "assistant_turns",
        sa.Column("turn_id", sa.String, primary_key=True),
        sa.Column("question", sa.String, nullable=False),
        sa.Column("scope", sa.JSON, nullable=False),
        sa.Column("model_id", sa.String, nullable=False),
        sa.Column("prompt_version", sa.String, nullable=False),
        sa.Column("status", sa.String, nullable=False),
        sa.Column("started_at", sa.String, nullable=False),
        sa.Column("completed_at", sa.String),
        sa.Column("answer", sa.JSON(none_as_null=True)),
        sa.Column("failure", sa.JSON(none_as_null=True)),
        sa.CheckConstraint(
            "(status = 'running' AND completed_at IS NULL AND answer IS NULL AND failure IS NULL) OR "
            "(status = 'succeeded' AND completed_at IS NOT NULL AND answer IS NOT NULL AND failure IS NULL) OR "
            "(status = 'failed' AND completed_at IS NOT NULL AND answer IS NULL AND failure IS NOT NULL)",
            name="ck_assistant_turns_state",
        ),
    )
    op.create_table(
        "assistant_steps",
        sa.Column("turn_id", sa.String, sa.ForeignKey("assistant_turns.turn_id"), primary_key=True),
        sa.Column("step_id", sa.String, primary_key=True),
        sa.Column("sequence", sa.Integer, nullable=False),
        sa.Column("receipt", sa.JSON, nullable=False),
        sa.UniqueConstraint("turn_id", "sequence"),
        sa.CheckConstraint("sequence >= 1", name="ck_assistant_steps_sequence"),
    )
    op.create_table(
        "assistant_evidence",
        sa.Column("turn_id", sa.String, primary_key=True),
        sa.Column("evidence_id", sa.String, primary_key=True),
        sa.Column("step_id", sa.String, nullable=False),
        sa.Column("source", sa.JSON, nullable=False),
        sa.ForeignKeyConstraint(
            ["turn_id", "step_id"],
            ["assistant_steps.turn_id", "assistant_steps.step_id"],
        ),
    )


def downgrade() -> None:
    op.drop_table("assistant_evidence")
    op.drop_table("assistant_steps")
    op.drop_table("assistant_turns")
