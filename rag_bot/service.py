"""Synchronous docs_only retrieval for callers outside the prototype UI."""

from dataclasses import dataclass, replace
from pathlib import Path
from threading import Lock
from typing import Literal

from .chunking import token_count
from .evidence import EvidenceIndex, EvidenceResolution, PassageEvidence
from .hybrid import HybridResult, HybridRetriever
from .presets import PRESETS, SEMANTIC_STABLE
from .profiles import DOCS_ONLY, load_snapshot
from .retrieval import ChunkKeywordIndex
from .semantic import SemanticRetriever, load_model
from .vector_store import CACHE_DIR


@dataclass(frozen=True)
class RetrievalRequest:
    query: str
    limit: int = 5
    preset: str = SEMANTIC_STABLE.key


@dataclass(frozen=True)
class Ranking:
    rank: int
    cosine_similarity: float | None
    rrf_score: float | None = None
    keyword_rank: int | None = None
    keyword_score: float | None = None
    semantic_rank: int | None = None


@dataclass(frozen=True)
class RetrievedExcerpt:
    evidence: PassageEvidence
    ranking: Ranking


@dataclass(frozen=True)
class RetrievalResult:
    status: Literal["data", "no_matches", "unavailable", "invalid_input", "unsupported_input",
                    "execution_failure"]
    matches: tuple[RetrievedExcerpt, ...] = ()
    message: str | None = None


class RetrievalService:
    """Load once per instance. Create a new instance to retry initialization or refresh."""

    def __init__(self, *, cache_dir: Path | None = CACHE_DIR):
        self._index = self._keywords = self._evidence = None
        self._lock = Lock()
        self._dispatch_capacity = Lock()
        try:
            snapshot = load_snapshot(DOCS_ONLY)
            if (snapshot.profile != DOCS_ONLY or not snapshot.passages
                    or any(p.catalog is not None or p.source_role != "project_policy"
                           for p in snapshot.passages)):
                return
            index = SemanticRetriever.from_snapshot(snapshot, load_model(), cache_dir=cache_dir)
            evidence = EvidenceIndex(snapshot, index.chunks)
            keywords = ChunkKeywordIndex(index.chunks)
        except Exception:
            # Resource failures can include optional runtime imports and model files.
            return
        self._index, self._keywords, self._evidence = index, keywords, evidence

    def retrieve(self, request: RetrievalRequest) -> RetrievalResult:
        if not isinstance(request, RetrievalRequest):
            return RetrievalResult("invalid_input", message="Expected a retrieval request.")
        if not isinstance(request.query, str) or not 1 <= len(request.query.strip()) <= 2000:
            return RetrievalResult("invalid_input", message="Query must contain 1 to 2,000 characters after stripping.")
        if type(request.limit) is not int or not 1 <= request.limit <= 10:
            return RetrievalResult("invalid_input", message="Limit must be an integer from 1 to 10.")
        if not isinstance(request.preset, str) or request.preset not in PRESETS:
            return RetrievalResult("invalid_input", message="Select an approved retrieval preset.")
        if self._index is None:
            return RetrievalResult("unavailable", message="Documentation retrieval resources are unavailable.")

        query = request.query.strip()
        preset = PRESETS[request.preset]
        try:
            with self._lock:
                model = self._index.model
                if token_count(model.tokenizer, query) > model.max_seq_length:
                    return RetrievalResult("unsupported_input", message="Query exceeds the embedding token limit.")
                if preset.strategy == "hybrid":
                    config = replace(preset.hybrid_config(), limit=request.limit)
                    results = HybridRetriever(self._index, self._keywords, config, preset.cutoff).search(query)
                else:
                    results = self._index.search(query, min_score=preset.cutoff, limit=request.limit)
            matches = tuple(
                RetrievedExcerpt(self._evidence.for_chunk(hit.chunk.chunk_id), _ranking(rank, hit))
                for rank, hit in enumerate(results, 1)
            )
        except Exception:
            return RetrievalResult("execution_failure", message="Documentation retrieval failed.")
        return RetrievalResult("data", matches) if matches else RetrievalResult("no_matches")

    def resolve(self, reference: str) -> EvidenceResolution:
        if self._evidence is None:
            return EvidenceResolution("unavailable")
        return self._evidence.resolve(reference)


def _ranking(rank, hit):
    if isinstance(hit, HybridResult):
        return Ranking(rank, hit.semantic_score, hit.score, hit.keyword_rank, hit.keyword_score,
                       hit.semantic_rank)
    return Ranking(rank, hit.score, semantic_rank=rank)
