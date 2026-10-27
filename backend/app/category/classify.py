"""Category Classification for one Tool Candidate (ADR 0003).

Known AI Tools keep their catalog Category. Other AI Tools take the Category their nearest
catalog Tools vote for, read from the text AI Determination judged.
"""

from dataclasses import dataclass
from importlib.metadata import version

from app.ai_determination.cascade import AiDetermination, EvidenceSource, source_policy
from app.category.embedder import Embed
from app.category.neighbors import Neighbor, NeighborIndex
from app.pipeline.identity import CandidateIdentity, KnownToolRegistry

NEIGHBOR_COUNT = 15
VOTE_CUTOFF = 0.468914118995349


def configuration_version(index: NeighborIndex, prefer_supplied: bool = False) -> str:
    """A readable label of what decides the outcome: index, embedding runtime, k, cutoff and source preference."""
    return (
        f"neighbor-vote-v1;index={index.version};"
        f"fastembed={version('fastembed')};onnxruntime={version('onnxruntime')};"
        f"k={NEIGHBOR_COUNT};cutoff={VOTE_CUTOFF:.3f};source={source_policy(prefer_supplied)}"
    )


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
    registry: KnownToolRegistry,
    index: NeighborIndex,
    embed: Embed,
) -> CategoryClassification:
    if ai_determination.determination != "ai":
        return CategoryClassification(
            "inapplicable", reason=f"ai_determination_{ai_determination.determination}"
        )
    if candidate.outcome == "known_tool":
        listing = registry.listing(candidate.catalog_tool_ids[0])
        source = EvidenceSource("catalog", listing.tool_id, version=registry.version)
        return CategoryClassification("assigned", "catalog", listing.category, source=source)
    if ai_determination.text is None:
        return CategoryClassification("unresolved", reason="no_evidence_text")

    vote = index.vote(embed([ai_determination.text.full_text])[0], NEIGHBOR_COUNT)
    assigned = vote.share >= VOTE_CUTOFF
    return CategoryClassification(
        "assigned" if assigned else "unresolved",
        "semantic_neighbor_vote",
        vote.category if assigned else None,
        None if assigned else "neighbor_vote_below_cutoff",
        vote.share,
        vote.neighbors,
        ai_determination.source,
    )
