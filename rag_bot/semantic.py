"""CPU embeddings and in-memory cosine search over the approved corpus."""

from dataclasses import dataclass
from hashlib import sha256
from math import isfinite
from pathlib import Path
from time import perf_counter

import numpy as np

from . import chunking
from .chunking import Chunk, chunk_passage, token_count
from .corpus import Passage
from .presets import SEMANTIC_STABLE
from .profiles import CorpusSnapshot, require_profile
from .vector_store import CACHE_DIR, FORMAT_VERSION, NORMALIZATION, VectorStore


MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"
MODEL_REVISION = "1110a243fdf4706b3f48f1d95db1a4f5529b4d41"
EMBEDDING_DIMENSION = 384
MODEL_INPUT_LIMIT = 256
BATCH_SIZE = 16
PROVISIONAL_MIN_SCORE = SEMANTIC_STABLE.cutoff


@dataclass(frozen=True)
class SemanticResult:
    chunk: Chunk
    score: float


def load_model():
    """Load the pinned model from the local cache and verify its configuration."""
    from sentence_transformers import SentenceTransformer

    model = SentenceTransformer(
        MODEL_NAME, revision=MODEL_REVISION, device="cpu", local_files_only=True
    )
    if (model.get_embedding_dimension() != EMBEDDING_DIMENSION
            or model.max_seq_length != MODEL_INPUT_LIMIT):
        raise ValueError("Unexpected embedding model dimensions or token limit.")
    return model


def normalize_rows(vectors: np.ndarray) -> np.ndarray:
    """Scale each vector to length one, leaving zero vectors at zero."""
    norms = np.linalg.norm(vectors, axis=1, keepdims=True)
    return np.divide(vectors, norms, out=np.zeros_like(vectors), where=norms != 0)


def chunking_config(overlap_tokens: int | None = None) -> dict:
    return {
        "overlap_tokens": chunking.DEFAULT_OVERLAP_TOKENS if overlap_tokens is None else overlap_tokens,
        "implementation_sha256": sha256(Path(chunking.__file__).read_bytes()).hexdigest(),
    }


@dataclass(frozen=True)
class IndexReport:
    status: str
    initialization_seconds: float
    embedding_seconds: float | None
    storage_notice: str | None = None

    def summary(self) -> str:
        result = f"Index: {self.status} | Initialization: {self.initialization_seconds:.3f} s"
        if self.embedding_seconds is None:
            result += " | Document embeddings: reused"
        else:
            result += f" | Document embedding time: {self.embedding_seconds:.3f} s"
        if self.storage_notice:
            result += f" | {self.storage_notice}"
        return result


class SemanticRetriever:
    """Build once per session and reuse the normalized document embeddings."""

    @classmethod
    def from_snapshot(cls, snapshot: CorpusSnapshot, model, **options):
        """Use authorized corpus metadata for a compatible persistent index."""
        return cls(list(snapshot.passages), model, snapshot=snapshot, **options)

    def __init__(self, passages: list[Passage], model, min_score=PROVISIONAL_MIN_SCORE, *,
                 snapshot: CorpusSnapshot | None = None, cache_dir: Path | None = CACHE_DIR,
                 rebuild: bool = False, overlap_tokens: int | None = None):
        started = perf_counter()
        if snapshot is not None:
            require_profile(snapshot.profile)
            if tuple(passages) != snapshot.passages:
                raise ValueError("Passages do not match the authorized corpus snapshot.")
        if not isfinite(min_score) or not -1 <= min_score <= 1:
            raise ValueError("Minimum similarity must be between -1 and 1.")
        self.model = model
        self.min_score = min_score
        configuration = chunking_config(overlap_tokens)
        self.chunks = [
            chunk
            for passage in passages
            for chunk in chunk_passage(
                passage, model.tokenizer, model.max_seq_length, configuration["overlap_tokens"]
            )
        ]
        self.dimension = model.get_embedding_dimension()
        self.store = None
        if snapshot is not None and cache_dir is not None:
            self.store = VectorStore({
                "format_version": FORMAT_VERSION,
                "corpus_profile": snapshot.profile,
                "corpus_version": snapshot.corpus_version,
                "chunk_ids": [chunk.chunk_id for chunk in self.chunks],
                "model_name": MODEL_NAME,
                "model_revision": MODEL_REVISION,
                "embedding_dimension": self.dimension,
                "embedding": {
                    "dtype": "float32", "device": "cpu", "batch_size": BATCH_SIZE,
                    "input_format": "heading-newline-excerpt-v1", "max_tokens": model.max_seq_length,
                },
                "normalization": NORMALIZATION,
                "chunking": configuration,
            }, cache_dir)

        vectors = self.store.load() if self.store and not rebuild else None
        if vectors is not None:
            self.embeddings = vectors
            self.index_report = IndexReport("loaded from disk", perf_counter() - started, None)
            return

        embedding_started = perf_counter()
        self.embeddings = self._embed([chunk.embedding_text for chunk in self.chunks])
        embedding_seconds = perf_counter() - embedding_started
        notice = None
        status = "memory-only"
        if self.store is not None:
            try:
                self.store.save(self.embeddings)
                status = "newly built"
            except OSError:
                notice = "Local cache write failed."
        self.index_report = IndexReport(status, perf_counter() - started, embedding_seconds, notice)

    def _embed(self, texts: list[str]) -> np.ndarray:
        """Check input lengths, encode a batch, and normalize embedding rows."""
        if not texts:
            return np.empty((0, self.dimension), dtype=np.float32)
        for text in texts:
            if token_count(self.model.tokenizer, text) > self.model.max_seq_length:
                raise ValueError(
                    f"Embedding input exceeds {self.model.max_seq_length} tokens. "
                    "Shorten the question and try again."
                )
        vectors = np.asarray(
            self.model.encode(texts, batch_size=BATCH_SIZE, convert_to_numpy=True,
                              show_progress_bar=False),
            dtype=np.float32,
        )
        if vectors.shape != (len(texts), self.dimension) or not np.isfinite(vectors).all():
            raise ValueError("Embedding model returned invalid vectors.")
        return normalize_rows(vectors)

    def search(self, question: str, *, min_score: float | None = None, limit: int = SEMANTIC_STABLE.limit) -> list[SemanticResult]:
        """Return ranked cosine matches, breaking exact ties by chunk ID."""
        if limit < 1:
            raise ValueError("Result limit must be positive.")
        cutoff = self.min_score if min_score is None else min_score
        if not isfinite(cutoff) or not -1 <= cutoff <= 1:
            raise ValueError("Minimum similarity must be between -1 and 1.")
        if not question.strip() or not self.chunks:
            return []
        query = self._embed([question.strip()])[0]
        scores = np.clip(self.embeddings @ query, -1.0, 1.0)
        matches = [
            SemanticResult(chunk, float(score))
            for chunk, score in zip(self.chunks, scores)
            if score >= cutoff
        ]
        return sorted(matches, key=lambda result: (-result.score, result.chunk.chunk_id))[:limit]
