"""Category Classification for one Tool Candidate (ADR 0003).

Known AI Tools keep their catalog Category. Other AI Tools take the Category their nearest
catalog Tools vote for, read from the same text AI Determination judged.
"""

from collections.abc import Mapping
from dataclasses import dataclass

from app.ai_determination.cascade import AiDetermination, EvidenceSource, evidence_text
from app.category.embedder import Embed
from app.category.neighbors import Neighbor, NeighborIndex
from app.enrichment.fetch import Capture
from app.pipeline.identity import CandidateIdentity, ToolMetadataSnapshot

K = 15
VOTE_CUTOFF = 0.468914118995349


@dataclass(frozen=True)
class CategoryClassification:
    outcome: str
    method: str | None = None
    category: str | None = None
    reason: str | None = None
    share: float | None = None
    neighbors: tuple[Neighbor, ...] = ()
    source: EvidenceSource | None = None


def classify_category(
    candidate: CandidateIdentity,
    ai_determination: AiDetermination,
    captures_by_domain: Mapping[str, Capture],
    metadata: ToolMetadataSnapshot,
    catalog_categories: Mapping[str, str],
    index: NeighborIndex,
    embed: Embed,
    prefer_supplied: bool = False,
) -> CategoryClassification:
    if ai_determination.determination != "ai":
        return CategoryClassification(
            "inapplicable", reason=f"ai_determination_{ai_determination.determination}"
        )
    if candidate.outcome == "known_tool":
        category = catalog_categories[candidate.catalog_tool_ids[0]]
        return CategoryClassification("assigned", "catalog", category)

    found = evidence_text(candidate, captures_by_domain, metadata, prefer_supplied)
    if isinstance(found, str):
        return CategoryClassification("unresolved", reason=found)
    source, text = found
    vote = index.vote(embed([text.gated_text])[0], K)
    if vote.share < VOTE_CUTOFF:
        return CategoryClassification(
            "unresolved",
            "semantic_neighbor_vote",
            reason="neighbor_vote_below_cutoff",
            share=vote.share,
            neighbors=vote.neighbors,
            source=source,
        )
    return CategoryClassification(
        "assigned",
        "semantic_neighbor_vote",
        vote.category,
        share=vote.share,
        neighbors=vote.neighbors,
        source=source,
    )
