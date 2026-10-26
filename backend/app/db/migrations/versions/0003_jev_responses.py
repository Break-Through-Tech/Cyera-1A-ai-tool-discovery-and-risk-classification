"""Create jev_responses

Revision ID: 0003
Revises: 0002
"""

import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "jev_responses",
        sa.Column("request_hash", sa.String(64), primary_key=True),
        sa.Column("model", sa.String, nullable=False),
        sa.Column("response", sa.JSON, nullable=False),
        sa.Column("created_at", sa.String, nullable=False),
    )


def downgrade() -> None:
    op.drop_table("jev_responses")
