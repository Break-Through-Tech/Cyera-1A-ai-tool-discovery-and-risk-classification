"""Verify the integration-facing service with the cached CPU model."""

from .service import RetrievalRequest, RetrievalService


def main():
    service = RetrievalService(cache_dir=None)
    semantic = service.retrieve(RetrievalRequest("What is a Tool Candidate?"))
    assert semantic.status == "data", semantic.status
    hit = semantic.matches[0].evidence
    assert hit.source_path == "CONTEXT.md" and "grouping of identity clues" in hit.excerpt
    assert service.resolve(hit.reference).evidence == hit

    hybrid = service.retrieve(RetrievalRequest(
        f"Show chunk {hit.chunk_id}.", limit=1, preset="hybrid-baseline"
    ))
    assert hybrid.status == "data" and hybrid.matches[0].evidence == hit
    assert service.retrieve(RetrievalRequest("How do I bake a chocolate cake?")).status == "no_matches"
    assert service.retrieve(RetrievalRequest("word " * 256)).status == "unsupported_input"
    print(f"Verified {hit.source_path} > {hit.heading} (section {hit.section_passage_id})")
    print(hit.reference)


if __name__ == "__main__":
    main()
