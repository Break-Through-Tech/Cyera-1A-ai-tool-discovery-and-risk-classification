"""Saved Usage Context assessments of a succeeded Analysis Run."""

from collections.abc import Sequence
from dataclasses import asdict

from sqlalchemy import Connection, func, insert, select

from app.db.tables import usage_context_assessments
from app.pipeline.usage_contexts import ContextAssessment


def save_assessments(
    connection: Connection, run_id: str, assessed: Sequence[ContextAssessment]
) -> None:
    """Write one row per assessed Usage Context, with its explanation and references."""
    if not assessed:
        return
    connection.execute(
        insert(usage_context_assessments),
        [
            {
                "run_id": run_id,
                "context_number": number,
                **asdict(item.context),
                "event_count": len(item.context.event_ids),
                "category": item.category,
                "category_method": item.category_method,
                "metadata_id": item.metadata_id,
                "facts": asdict(item.facts),
                **asdict(item.assessment),
                "purpose_class": item.purpose_class,
                "concern_tags": list(item.concern_tags),
                "fact_scope": item.fact_scope,
                "framework_refs": item.framework_refs,
                "explanation": item.explanation,
                "explanation_parts": item.explanation_parts,
                "rule_version": item.rule_version,
            }
            for number, item in enumerate(assessed, start=1)
        ],
    )


def list_assessments(
    connection: Connection,
    run_id: str,
    limit: int,
    offset: int,
    tier: str | None = None,
    flagged: bool | None = None,
    interaction_class: str | None = None,
    tool_id: str | None = None,
    department: str | None = None,
) -> tuple[list[dict], int]:
    """A Run's assessments in context order, optionally narrowed, and their total."""
    table = usage_context_assessments
    where = [table.c.run_id == run_id]
    if tier is not None:
        where.append(table.c.tier == tier)
    if flagged is not None:
        where.append(table.c.investigation_flag == flagged)
    if interaction_class is not None:
        where.append(table.c.interaction_class == interaction_class)
    if tool_id is not None:
        where.append(table.c.tool_id == tool_id)
    if department is not None:
        where.append(table.c.department == department)
    rows = connection.execute(
        select(usage_context_assessments)
        .where(*where)
        .order_by(usage_context_assessments.c.context_number)
        .limit(limit)
        .offset(offset)
    ).mappings().all()
    total = connection.execute(
        select(func.count()).select_from(usage_context_assessments).where(*where)
    ).scalar_one()
    return [dict(row) for row in rows], total
