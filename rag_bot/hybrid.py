"""Reciprocal rank fusion over keyword and semantic rankings of the same chunks."""

from collections import Counter
from dataclasses import dataclass
from typing import Protocol, Sequence

from .chunking import Chunk
from .presets import HYBRID_BASELINE
from .retrieval import ChunkKeywordIndex, ChunkKeywordResult
from .semantic import PROVISIONAL_MIN_SCORE, SemanticResult, SemanticRetriever


@dataclass(frozen=True)
class HybridConfig:
    smoothing: int = HYBRID_BASELINE.smoothing
    candidate_depth: int = HYBRID_BASELINE.depth
    limit: int = HYBRID_BASELINE.limit
    max_per_passage: int | None = HYBRID_BASELINE.cap

    def __post_init__(self):
        if (self.smoothing < 0 or min(self.candidate_depth, self.limit) < 1
                or (self.max_per_passage is not None and self.max_per_passage < 1)):
            raise ValueError("RRF smoothing must be nonnegative; depth and limits must be positive.")

    def summary(self) -> str:
        return (f"RRF k={self.smoothing}, depth={self.candidate_depth} per method, "
                f"limit={self.limit}, per-passage cap={self.max_per_passage or 'none'}")


@dataclass(frozen=True)
class HybridResult:
    chunk: Chunk
    score: float
    keyword_rank: int | None
    keyword_score: float | None
    semantic_rank: int | None
    semantic_score: float | None

    def diagnostics(self) -> str:
        details = []
        if self.keyword_rank is not None:
            details.append(f"Keyword rank {self.keyword_rank}, score {self.keyword_score:.3f}")
        if self.semantic_rank is not None:
            details.append(f"Semantic rank {self.semantic_rank}, cosine {self.semantic_score:.3f}")
        return " | ".join(details)


class ChunkRetriever(Protocol):
    def search(self, question: str) -> Sequence[SemanticResult | HybridResult]:
        ...


def _ranked_by_id(results):
    ranked = {}
    for rank, result in enumerate(results, 1):
        ranked.setdefault(result.chunk.chunk_id, (rank, result))
    return ranked


def fuse(
    keyword: Sequence[ChunkKeywordResult],
    semantic: Sequence[SemanticResult],
    keyword_only_ids: set[str],
    config: HybridConfig,
) -> list[HybridResult]:
    """Fuse one-based ranks, then cap the selected chunks per original passage."""
    lexical = _ranked_by_id(keyword[:config.candidate_depth])
    vector = _ranked_by_id(semantic[:config.candidate_depth])
    candidates = []
    for chunk_id in vector.keys() | (lexical.keys() & keyword_only_ids):
        keyword_rank, keyword_hit = lexical.get(chunk_id, (None, None))
        semantic_rank, semantic_hit = vector.get(chunk_id, (None, None))
        score = sum(1 / (config.smoothing + rank)
                    for rank in (keyword_rank, semantic_rank) if rank is not None)
        candidates.append(HybridResult(
            (semantic_hit or keyword_hit).chunk, score,
            keyword_rank, keyword_hit.score if keyword_hit is not None else None,
            semantic_rank, semantic_hit.score if semantic_hit is not None else None,
        ))

    selected = []
    counts = Counter()
    for result in sorted(candidates, key=lambda item: (-item.score, item.chunk.chunk_id)):
        passage_id = result.chunk.passage.passage_id
        if config.max_per_passage is None or counts[passage_id] < config.max_per_passage:
            selected.append(result)
            counts[passage_id] += 1
            if len(selected) == config.limit:
                break
    return selected


class HybridRetriever:
    def __init__(self, semantic: SemanticRetriever, keyword: ChunkKeywordIndex,
                 config: HybridConfig = HybridConfig(), min_score: float = PROVISIONAL_MIN_SCORE):
        self.semantic = semantic
        self.keyword = keyword
        self.config = config
        self.min_score = min_score

    def search(self, question: str) -> list[HybridResult]:
        keyword = self.keyword.search(question, limit=self.config.candidate_depth)
        semantic = self.semantic.search(question, min_score=self.min_score,
                                        limit=self.config.candidate_depth)
        exact = self.keyword.exact_references(question, {hit.chunk.chunk_id for hit in keyword})
        return fuse(keyword, semantic, exact, self.config)
