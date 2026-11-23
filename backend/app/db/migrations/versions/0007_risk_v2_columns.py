"""Add owasp-usage-risk-v2 columns to usage_context_assessments; rename tier Lower to Low.

Revision ID: 0007
Revises: 0006

Rows saved by v1 keep rule_version = synthetic-demo-risk-v1 and null v2 columns; only their
tier label changes from Lower to Low.
"""

import sqlalchemy as sa
from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None

_TABLE = "usage_context_assessments"
_CHECK = "ck_usage_context_assessments_tier"
_COLUMNS = (
    ("category_method", sa.String),
    ("interaction_class", sa.String),
    ("event_types", sa.JSON),
    ("distinct_employee_count", sa.Integer),
    ("governance_level", sa.String),
    ("exposure_level", sa.String),
    ("sensitivity_assumed", sa.Boolean),
    ("base_tier", sa.String),
    ("escalation", sa.String),
    ("escalation_reason", sa.String),
    ("tier_raised", sa.Boolean),
    ("escalation_event_ids", sa.JSON),
    ("purpose_class", sa.String),
    ("concern_tags", sa.JSON),
    ("fact_scope", sa.String),
    ("framework_refs", sa.JSON),
    ("explanation", sa.Text),
    ("explanation_parts", sa.JSON),
)


def upgrade() -> None:
    with op.batch_alter_table(_TABLE) as batch:
        batch.drop_constraint(_CHECK, type_="check")
        for name, type_ in _COLUMNS:
            batch.add_column(sa.Column(name, type_, nullable=True))
    op.execute(f"UPDATE {_TABLE} SET tier = 'Low' WHERE tier = 'Lower'")
    with op.batch_alter_table(_TABLE) as batch:
        batch.create_check_constraint(_CHECK, "tier IN ('High', 'Medium', 'Low', 'unresolved')")


def downgrade() -> None:
    with op.batch_alter_table(_TABLE) as batch:
        batch.drop_constraint(_CHECK, type_="check")
    op.execute(f"UPDATE {_TABLE} SET tier = 'Lower' WHERE tier = 'Low'")
    with op.batch_alter_table(_TABLE) as batch:
        for name, _ in reversed(_COLUMNS):
            batch.drop_column(name)
        batch.create_check_constraint(
            _CHECK, "tier IN ('High', 'Medium', 'Lower', 'unresolved')"
        )
