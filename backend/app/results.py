"""Saved results of a succeeded Analysis Run: stage outcomes and Usage Context assessments."""

from collections.abc import Mapping, Sequence
from dataclasses import asdict

from sqlalchemy import Connection, func, insert, select

from app.ai_determination.cascade import AiDetermination
from app.category.classify import CategoryClassification
from app.db.tables import (
    ai_determinations,
    category_classifications,
    tool_candidates,
    usage_context_assessments,
    website_captures,
)
from app.enrichment.fetch import Capture
from app.pipeline.identity import CandidateIdentity
from app.pipeline.usage_contexts import RESOLVED_OUTCOMES, ContextAssessment


def save_stage_results(
    connection: Connection,
    run_id: str,
    identities: Sequence[CandidateIdentity],
    ai: Sequence[AiDetermination],
    categories: Sequence[CategoryClassification],
    captures_by_domain: Mapping[str, Capture],
) -> None:
    """Write every Tool Candidate with its AI and category outcomes, and every capture.

    ``identities``, ``ai`` and ``categories`` are parallel, as the pipeline produces them.
    Non-AI and unresolved candidates are kept, so a Run explains every observed application.
    """
    if not len(identities) == len(ai) == len(categories):
        raise ValueError("identity, AI and category results must be parallel")
    numbered = list(enumerate(zip(identities, ai, categories, strict=True), start=1))
    if numbered:
        connection.execute(
            insert(tool_candidates),
            [
                {
                    "run_id": run_id,
                    "candidate_number": number,
                    "domain": candidate.domain,
                    "application_names": list(candidate.application_names),
                    "event_ids": list(candidate.event_ids),
                    "event_count": len(candidate.event_ids),
                    "outcome": candidate.outcome,
                    "tool_id": candidate.tool_id,
                    "basis": candidate.basis,
                    "reason": candidate.reason,
                    "catalog_tool_ids": list(candidate.catalog_tool_ids),
                    "metadata_id": candidate.metadata_id,
                }
                for number, (candidate, _, _) in numbered
            ],
        )
        connection.execute(
            insert(ai_determinations),
            [
                {
                    "run_id": run_id,
                    "candidate_number": number,
                    "determination": result.determination,
                    "stage": result.stage,
                    "reason": result.reason,
                    "model": result.model,
                    "probabilities": (
                        dict(result.probabilities) if result.probabilities is not None else None
                    ),
                    "evidence": [asdict(sentence) for sentence in result.evidence],
                    "needs_review": result.needs_review,
                    "source": asdict(result.source) if result.source else None,
                    "text_supplied": result.text.supplied if result.text else None,
                }
                for number, (_, result, _) in numbered
            ],
        )
        connection.execute(
            insert(category_classifications),
            [
                {
                    "run_id": run_id,
                    "candidate_number": number,
                    "outcome": result.outcome,
                    "method": result.method,
                    "category": result.category,
                    "reason": result.reason,
                    "share": result.share,
                    "neighbors": [asdict(neighbor) for neighbor in result.neighbors],
                    "source": asdict(result.source) if result.source else None,
                }
                for number, (_, _, result) in numbered
            ],
        )
    if captures_by_domain:
        connection.execute(
            insert(website_captures),
            [
                {
                    "run_id": run_id,
                    "domain": domain,
                    "requested_url": capture.requested_url,
                    "captured_at": capture.captured_at,
                    "outcome": capture.outcome,
                    "detail": capture.detail,
                    "final_url": capture.final_url,
                    "title": capture.title,
                    "page_metadata": dict(capture.metadata),
                    "headings": list(capture.headings),
                    "main_text": capture.main_text,
                }
                for domain, capture in sorted(captures_by_domain.items())
            ],
        )


def no_risk_tier_reasons(candidate: Mapping) -> tuple[str, ...]:
    """Why a saved Tool Candidate got no Usage Context assessment; empty if it got one.

    Mirrors ``assess_usage_contexts``: only a resolved Tool that AI Determination called AI
    is assessed. ``candidate`` is a ``list_candidates`` item.
    """
    reasons = []
    if candidate["outcome"] not in RESOLVED_OUTCOMES:
        reasons.append("identity_unresolved")
    determination = candidate["ai"]["determination"]
    if determination == "non_ai":
        reasons.append("not_ai")
    elif determination != "ai":
        reasons.append("ai_unresolved")
    return tuple(reasons)


def list_candidates(connection: Connection, run_id: str) -> list[dict]:
    """A Run's Tool Candidates in order, each with its ``ai`` and ``category`` outcomes
    and its ``no_risk_tier_reasons``."""
    candidates = connection.execute(
        select(tool_candidates)
        .where(tool_candidates.c.run_id == run_id)
        .order_by(tool_candidates.c.candidate_number)
    ).mappings().all()
    ai = _by_candidate(connection, ai_determinations, run_id)
    category = _by_candidate(connection, category_classifications, run_id)
    saved = [
        {
            **dict(row),
            "ai": ai.get(row["candidate_number"]),
            "category": category.get(row["candidate_number"]),
        }
        for row in candidates
    ]
    for candidate in saved:
        candidate["no_risk_tier_reasons"] = list(no_risk_tier_reasons(candidate))
    return saved


def get_capture(connection: Connection, run_id: str, domain: str) -> dict | None:
    """The homepage capture a Run made for ``domain``, if any."""
    row = connection.execute(
        select(website_captures).where(
            website_captures.c.run_id == run_id, website_captures.c.domain == domain
        )
    ).mappings().one_or_none()
    return dict(row) if row else None


def _by_candidate(connection: Connection, table, run_id: str) -> dict[int, dict]:
    rows = connection.execute(select(table).where(table.c.run_id == run_id)).mappings().all()
    return {
        row["candidate_number"]: {
            key: value
            for key, value in row.items()
            if key not in ("run_id", "candidate_number")
        }
        for row in rows
    }


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
