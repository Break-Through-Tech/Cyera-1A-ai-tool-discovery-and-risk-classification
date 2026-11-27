"""Combine local retrieval and Gemini, then validate references before display."""

import re
from dataclasses import dataclass

from .catalog import catalog_details
from .generator import AnswerStatus, GenerationError, GeminiGenerator
from .profiles import DOCS_ONLY
from .prompts import EvidenceItem, build_prompt
from .hybrid import ChunkRetriever


@dataclass(frozen=True)
class RagAnswer:
    answer: str
    status: AnswerStatus
    cited_sources: tuple[EvidenceItem, ...] = ()
    limitations: tuple[str, ...] = ()


class RagChat:
    def __init__(self, retriever: ChunkRetriever, generator: GeminiGenerator, *,
                 corpus_profile: str = DOCS_ONLY, corpus_version: str | None = None):
        self.retriever = retriever
        self.generator = generator
        self.corpus_profile = corpus_profile
        self.corpus_version = corpus_version

    def ask(self, question: str) -> RagAnswer:
        """Use the configured retrieval threshold and validate citations against this turn."""
        matches = self.retriever.search(question)
        if not matches:
            return RagAnswer(
                "The approved project documents did not yield evidence for this question.",
                "insufficient",
                limitations=("No chunk satisfied the selected retriever’s relevance criteria.",),
            )
        prompt = build_prompt(
            question, [match.chunk for match in matches],
            corpus_profile=self.corpus_profile, corpus_version=self.corpus_version,
        )
        reply = self.generator.generate(prompt)
        if any(re.search(r"[\[\]\x1b]|https?://", text, re.IGNORECASE)
               for text in (reply.answer, *reply.limitations)):
            raise GenerationError("Gemini returned unsupported inline references or formatting.")
        evidence = {item.label: item for item in prompt.evidence}
        labels = tuple(dict.fromkeys(reply.citation_labels))
        if any(label not in evidence for label in labels):
            raise GenerationError("The answer could not be validated because it cites unknown evidence.")
        if reply.status == "insufficient":
            if reply.answer or labels or not reply.limitations:
                raise GenerationError("Gemini returned an inconsistent insufficient-evidence response.")
            return RagAnswer(
                "The retrieved evidence is insufficient to answer this question.",
                "insufficient",
                limitations=reply.limitations,
            )
        if not reply.answer or not labels:
            raise GenerationError("The substantive answer could not be validated without citations.")
        if reply.status == "partial" and not reply.limitations:
            raise GenerationError("The partial answer did not state what evidence was missing.")
        return RagAnswer(reply.answer, reply.status, tuple(evidence[label] for label in labels),
                         reply.limitations)


def show_answer(result: RagAnswer) -> None:
    """Print the answer and only citations resolved by the local pipeline."""
    print(f"Answer status: {result.status}\n{result.answer}")
    if result.cited_sources:
        print("\nCitations")
    for item in result.cited_sources:
        chunk = item.chunk
        passage = chunk.passage
        print(f"[{item.label}] {passage.source_path} > {passage.heading}")
        print(f"    Chunk {chunk.chunk_id} | Passage {passage.passage_id}")
        print(f"    Role {passage.source_role} | Version {passage.content_version}")
        if passage.catalog is not None:
            print(catalog_details(passage.catalog))
    if result.limitations:
        print("\nLimitations")
        for limitation in result.limitations:
            print(f"- {limitation}")
