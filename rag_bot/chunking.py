"""Split passages into exact source excerpts sized for the embedding model."""

import re
from bisect import bisect_right
from dataclasses import dataclass
from hashlib import sha256

from .corpus import Passage


PARAGRAPH_END = re.compile(r"\n[ \t]*\n+")
LINE_END = re.compile(r"\n")
SENTENCE_END = re.compile(r"[.!?](?=\s)")
DEFAULT_OVERLAP_TOKENS = 24
WORD_END = re.compile(r"\s+")


@dataclass(frozen=True)
class Chunk:
    passage: Passage
    start: int
    end: int
    chunk_id: str

    @property
    def text(self) -> str:
        return self.passage.text[self.start:self.end]

    @property
    def embedding_text(self) -> str:
        return f"{self.passage.heading}\n{self.text}"


def token_count(tokenizer, text: str) -> int:
    """Count tokens with the same special tokens used for embedding."""
    return len(tokenizer.encode(text, add_special_tokens=True, truncation=False, verbose=False))


def _largest_fitting_end(ends, start, fits):
    """Find a fitting endpoint by testing complete heading-plus-excerpt inputs."""
    first = bisect_right(ends, start)
    low, high = first, len(ends)
    while low < high:
        middle = (low + high) // 2
        if fits(ends[middle]):
            low = middle + 1
        else:
            high = middle
    return ends[low - 1] if low > first else start


def chunk_passage(passage: Passage, tokenizer, limit: int, overlap_tokens: int = DEFAULT_OVERLAP_TOKENS) -> list[Chunk]:
    """Prefer paragraph, line, and sentence breaks while keeping every character."""
    if not 0 <= overlap_tokens < limit:
        raise ValueError("Overlap must be nonnegative and smaller than the token limit.")

    text = passage.text
    boundaries = [
        [match.end() for match in pattern.finditer(text)]
        for pattern in (PARAGRAPH_END, LINE_END, SENTENCE_END, WORD_END)
    ]
    word_ends = boundaries[-1] + [len(text)]
    chunks = []
    start = 0
    while start < len(text):

        def fits(end):
            return token_count(tokenizer, f"{passage.heading}\n{text[start:end]}") <= limit

        if fits(len(text)):
            end = len(text)
        else:
            end = _largest_fitting_end(word_ends, start, fits)
            if end == start:
                # A single unbroken string can itself exceed the token budget.
                end = _largest_fitting_end(range(start + 1, len(text) + 1), start, fits)
                if end == start:
                    raise ValueError(f"Cannot fit text under heading {passage.heading!r}.")
            minimum = start + (end - start) // 2
            for candidates in boundaries[:-1]:
                index = bisect_right(candidates, end) - 1
                if index >= 0 and candidates[index] > minimum and fits(candidates[index]):
                    end = candidates[index]
                    break

        identity = f"{passage.passage_id}:{passage.content_version}:{start}:{end}"
        chunks.append(Chunk(passage, start, end, sha256(identity.encode()).hexdigest()[:20]))
        if end == len(text):
            break

        # Start the next excerpt at a word boundary within the tail budget.
        next_start = end
        index = bisect_right(word_ends, end - 1) - 1
        while overlap_tokens and index >= 0:
            candidate = word_ends[index]
            if candidate <= start + (end - start) // 2:
                break
            tail = tokenizer.encode(
                text[candidate:end], add_special_tokens=False, truncation=False, verbose=False
            )
            if len(tail) > overlap_tokens:
                break
            next_start = candidate
            index -= 1
        start = next_start
    return chunks
