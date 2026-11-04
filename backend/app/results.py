"""Saved Usage Context assessments of a succeeded Analysis Run."""

from collections.abc import Mapping, Sequence
from dataclasses import asdict

from sqlalchemy import Connection, func, insert, select

from app.db.tables import usage_context_assessments
from app.pipeline.usage_contexts import ContextAssessment


def save_assessments(
    connection: Connection,
    run_id: str,
    assessed: Sequence[ContextAssessment],
    categories: Mapping[str, str | None],
) -> None:
    """Write one row per context; ``categories`` maps a Tool ID to its classified category."""
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
                "category": categories.get(item.context.tool_id),
                "metadata_id": item.metadata_id,
                "facts": asdict(item.facts),
                **asdict(item.assessment),
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
) -> tuple[list[dict], int]:
    """A Run's assessments in context order, optionally narrowed by tier or flag, and their total."""
    where = [usage_context_assessments.c.run_id == run_id]
    if tier is not None:
        where.append(usage_context_assessments.c.tier == tier)
    if flagged is not None:
        where.append(usage_context_assessments.c.investigation_flag == flagged)
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
