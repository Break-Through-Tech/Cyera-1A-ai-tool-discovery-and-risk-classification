"""Rank project passages by matching question words."""

import math
import re
from collections import Counter
from dataclasses import dataclass

from .chunking import Chunk
from .corpus import Passage


COMMON_WORDS = frozenset(
    "a an and are as at be by can do does for from how i in is it of on or "
    "should that the this to was what when where which who why will with you".split()
)


@dataclass(frozen=True)
class SearchResult:
    passage: Passage
    score: float


def words(text: str) -> list[str]:
    return re.findall(r"[^\W_]+", text.casefold())


def tokenize(text: str) -> set[str]:
    """Return distinct lowercase words after removing common question words."""
    return set(words(text)) - COMMON_WORDS


def search(question: str, passages: list[Passage]) -> list[SearchResult]:
    """Return up to five positive matches, giving rarer matching words more weight."""
    query_terms = tokenize(question)
    if not query_terms or not passages:
        return []

    passage_terms = [tokenize(f"{passage.heading}\n{passage.text}") for passage in passages]
    frequencies = Counter(term for terms in passage_terms for term in terms & query_terms)
    weights = {
        term: 1 + math.log((len(passages) + 1) / (count + 1))
        for term, count in frequencies.items()
    }

    matches = []
    for passage, terms in zip(passages, passage_terms):
        shared_terms = sorted(query_terms & terms)
        if shared_terms:
            matches.append(SearchResult(passage, sum(weights[term] for term in shared_terms)))

    return sorted(matches, key=lambda result: (-result.score, result.passage.passage_id))[:5]


@dataclass(frozen=True)
class ChunkKeywordResult:
    chunk: Chunk
    score: float


class ChunkKeywordIndex:
    """Precompute chunk terms and weighted overlap statistics once."""

    def __init__(self, chunks: list[Chunk]):
        unique = {chunk.chunk_id: chunk for chunk in chunks}
        self.entries = []
        for chunk in unique.values():
            identifiers = {chunk.chunk_id.casefold(), chunk.passage.passage_id.casefold()}
            if chunk.passage.catalog is not None:
                identifiers.add(chunk.passage.catalog.tool_id.casefold())
            name = tuple(words(chunk.passage.heading)) if chunk.passage.catalog else ()
            terms = tokenize(chunk.embedding_text) | identifiers | set(name)
            self.entries.append((chunk, terms, identifiers, name))
        frequencies = Counter(term for _, terms, _, _ in self.entries for term in terms)
        self.weights = {
            term: 1 + math.log((len(self.entries) + 1) / (frequency + 1))
            for term, frequency in frequencies.items()
        }

    def search(self, question: str, *, limit: int = 20) -> list[ChunkKeywordResult]:
        """Rank token overlap, including exact identifiers as searchable terms."""
        if limit < 1:
            raise ValueError("Candidate depth must be positive.")
        query_words = tuple(words(question))
        query_terms = set(query_words) - COMMON_WORDS
        matches = []
        for chunk, terms, _, name in self.entries:
            shared = sorted(terms & query_terms)
            if name and name == query_words:
                shared = sorted(set(shared) | set(name))
            if shared:
                matches.append(ChunkKeywordResult(chunk, sum(self.weights[term] for term in shared)))
        return sorted(matches, key=lambda hit: (-hit.score, hit.chunk.chunk_id))[:limit]

    def exact_references(self, question: str, candidate_ids: set[str]) -> set[str]:
        """Allow an exact identifier, or a query consisting solely of a catalog name."""
        question_words = tuple(words(question))
        query_terms = set(question_words)
        return {
            chunk.chunk_id
            for chunk, _, identifiers, name in self.entries
            if chunk.chunk_id in candidate_ids
            and (bool(identifiers & query_terms) or (name and question_words == name))
        }
