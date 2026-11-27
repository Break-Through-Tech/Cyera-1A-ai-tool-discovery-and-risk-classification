"""Opt-in checks and retrieval comparison using the pinned, cached CPU model."""

import argparse

import numpy as np

from .chunking import token_count
from .corpus import load_passages
from .retrieval import search
from .semantic import (
    EMBEDDING_DIMENSION,
    MODEL_INPUT_LIMIT,
    MODEL_NAME,
    MODEL_REVISION,
    SemanticRetriever,
    load_model,
)


QUESTIONS = (
    "What is a Tool Candidate?",
    "What is the difference between an AI Tool and an AI Mention?",
    "How do we identify potentially unknown software applications?",
    "Does visiting an application prove confidential information was submitted?",
    "How is contextual risk evaluated?",
    "How do I bake a chocolate cake?",
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--compare", action="store_true", help="Print both rankings for six questions")
    args = parser.parse_args()

    passages = load_passages()
    model = load_model()
    retriever = SemanticRetriever(passages, model)
    assert str(model.device) == "cpu"
    assert retriever.embeddings.shape == (len(retriever.chunks), EMBEDDING_DIMENSION)
    np.testing.assert_allclose(np.linalg.norm(retriever.embeddings, axis=1), 1, atol=1e-6)

    print(f"{MODEL_NAME} @ {MODEL_REVISION} (CPU)")
    print(f"Original inputs including heading and special tokens (limit {MODEL_INPUT_LIMIT}):")
    for passage in passages:
        count = token_count(model.tokenizer, f"{passage.heading}\n{passage.text}")
        chunks = [chunk for chunk in retriever.chunks if chunk.passage == passage]
        assert chunks[0].start == 0 and chunks[-1].end == len(passage.text)
        assert all(a.start < b.start <= a.end < b.end for a, b in zip(chunks, chunks[1:]))
        print(f"  {count:4} tokens -> {len(chunks)} chunk(s) | {passage.source_path} > {passage.heading}")

    largest = max(token_count(model.tokenizer, chunk.embedding_text) for chunk in retriever.chunks)
    assert largest <= MODEL_INPUT_LIMIT
    hits = retriever.search(QUESTIONS[0])
    assert hits and "grouping of identity clues" in hits[0].chunk.text
    print(f"Smoke test passed. Matrix {retriever.embeddings.shape}, largest input {largest} tokens.")

    if args.compare:
        for question in QUESTIONS:
            print(f"\n{question}")
            keyword = search(question, passages)
            semantic = retriever.search(question)
            for hit in keyword:
                print(f"  keyword  {hit.score:6.3f} {hit.passage.source_path} > {hit.passage.heading}")
            if not keyword:
                print("  keyword  no results")
            for hit in semantic:
                p = hit.chunk.passage
                print(f"  semantic {hit.score:6.3f} {p.source_path} > {p.heading} [{hit.chunk.start}:{hit.chunk.end}]")
            if not semantic:
                print("  semantic no results")


if __name__ == "__main__":
    main()
