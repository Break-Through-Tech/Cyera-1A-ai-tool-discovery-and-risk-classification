"""Compare four search methods on approved Markdown using the cached CPU model."""

from tempfile import TemporaryDirectory
from pathlib import Path
from time import perf_counter

from .hybrid import HybridRetriever
from .profiles import load_snapshot
from .retrieval import ChunkKeywordIndex, search
from .semantic import SemanticRetriever, load_model
from .smoke_semantic import QUESTIONS


def main() -> None:
    snapshot = load_snapshot()
    with TemporaryDirectory(prefix="rag-hybrid-smoke-") as temporary:
        index = SemanticRetriever.from_snapshot(snapshot, load_model(), cache_dir=Path(temporary))
        keywords = ChunkKeywordIndex(index.chunks)
        hybrid = HybridRetriever(index, keywords)
        definitions = next(p for p in snapshot.passages if p.heading == "Language")
        candidate = hybrid.search(QUESTIONS[0])[0].chunk
        questions = QUESTIONS + (
            "How do uncertain observations get grouped before software identity is resolved?",
            "Can an AI marketing claim alone establish what software actually does?",
            f"Find passage {definitions.passage_id}.",
            f"Show chunk {candidate.chunk_id}.",
            "How do I bake a chocolate cake for the governance committee?",
            "What bike tire pressure should I use for a risk assessment team outing?",
            "How do I water an orchid using a tool from my kitchen?",
        )
        for question in questions:
            print(f"\n{question}")
            for name, retrieve in (
                ("Passage keyword", lambda text: search(text, snapshot.passages)),
                ("Chunk keyword", lambda text: keywords.search(text, limit=5)),
                ("Semantic", index.search),
                ("Hybrid", hybrid.search),
            ):
                started = perf_counter()
                results = retrieve(question)
                elapsed = (perf_counter() - started) * 1000
                passages = {
                    result.chunk.passage.passage_id if hasattr(result, "chunk")
                    else result.passage.passage_id for result in results
                }
                print(f"  {name}: {len(results)} hits / {len(passages)} passages / {elapsed:.2f} ms")
                for rank, result in enumerate(results, 1):
                    chunk = getattr(result, "chunk", None)
                    passage = chunk.passage if chunk else result.passage
                    identity = chunk.chunk_id if chunk else passage.passage_id
                    details = result.diagnostics() if name == "Hybrid" else ""
                    print(f"    {rank}. {identity} {result.score:.6f} "
                          f"{passage.source_path} > {passage.heading} {details}".rstrip())
            if question == QUESTIONS[-1]:
                assert not hybrid.search(question)
        assert any(result.chunk.chunk_id == candidate.chunk_id
                   for result in hybrid.search(f"Show chunk {candidate.chunk_id}."))


if __name__ == "__main__":
    main()
