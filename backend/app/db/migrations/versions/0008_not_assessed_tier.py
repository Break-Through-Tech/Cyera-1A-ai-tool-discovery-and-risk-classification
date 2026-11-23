"""Allow the not_assessed tier on usage_context_assessments (rubric owasp-usage-risk-v2.1).

Revision ID: 0008
Revises: 0007

Usage of a Tool whose identity or AI status is unresolved is now saved as a not_assessed row
instead of being dropped, so the dashboard can show it as used but not assessed.
"""

from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None

_TABLE = "usage_context_assessments"
_CHECK = "ck_usage_context_assessments_tier"


def upgrade() -> None:
    with op.batch_alter_table(_TABLE) as batch:
        batch.drop_constraint(_CHECK, type_="check")
        batch.create_check_constraint(
            _CHECK, "tier IN ('High', 'Medium', 'Low', 'unresolved', 'not_assessed')"
        )


def downgrade() -> None:
    op.execute(f"DELETE FROM {_TABLE} WHERE tier = 'not_assessed'")
    with op.batch_alter_table(_TABLE) as batch:
        batch.drop_constraint(_CHECK, type_="check")
        batch.create_check_constraint(_CHECK, "tier IN ('High', 'Medium', 'Low', 'unresolved')")
