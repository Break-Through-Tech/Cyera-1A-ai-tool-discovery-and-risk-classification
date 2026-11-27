"""Display retrieved evidence in the terminal."""

import argparse
import sys
from dataclasses import replace

from .catalog import catalog_details
from .corpus import Passage
from .presets import DEFAULT_PRESETS, PRESETS
from .profiles import DOCS_ONLY, PROFILE_NAMES, ProfileError, load_snapshot
from .retrieval import search


def show_results(question: str, passages: list[Passage], semantic=None, hybrid=None) -> None:
    """Print the ranked passages and the source details needed to find them."""
    if hybrid is not None:
        print(f"Retrieval method: hybrid (minimum cosine {hybrid.min_score:g})")
        print(hybrid.config.summary())
        matches = hybrid.search(question)
    elif semantic is None:
        print("Retrieval method: keyword (weighted word overlap)")
        matches = search(question, passages)
    else:
        print(f"Retrieval method: semantic (cosine similarity, minimum {semantic.min_score:g})")
        matches = semantic.search(question)
    if not matches:
        print("No matching passages found.")
        return

    for rank, result in enumerate(matches, 1):
        if semantic is None:
            passage = result.passage
            print(f"\n[{passage.passage_id}] Score {result.score:.2f}")
            excerpt = passage.text
        else:
            chunk = result.chunk
            passage = chunk.passage
            if hybrid is not None:
                print(f"\nRank {rank} [{chunk.chunk_id}] RRF {result.score:.6f}")
                print(result.diagnostics())
            else:
                print(f"\n[{chunk.chunk_id}] Cosine similarity {result.score:.3f}")
            print(f"Passage ID {passage.passage_id} | Characters {chunk.start}:{chunk.end}")
            excerpt = chunk.text
        print(f"{passage.source_path} > {passage.heading}")
        print(f"Role {passage.source_role} | Version {passage.content_version}")
        if passage.catalog is not None:
            print(catalog_details(passage.catalog))
        print(excerpt)


def main() -> int:
    """Load the corpus and handle a single question or an interactive session."""
    parser = argparse.ArgumentParser(description="Search approved Cyera project documents.")
    parser.add_argument("question", nargs="?", help="Question to search for")
    parser.add_argument("--mode", choices=("keyword", "semantic", "hybrid", "rag"), default="keyword")
    parser.add_argument("--profile", choices=PROFILE_NAMES, default=DOCS_ONLY)
    parser.add_argument("--preset", choices=PRESETS, help="Named retrieval preset")
    parser.add_argument("--min-score", type=float, help="Provisional semantic cosine cutoff")
    parser.add_argument("--retrieval", choices=("semantic", "hybrid"),
                        help="Retrieval strategy for RAG mode (default: semantic)")
    parser.add_argument("--candidate-depth", type=int)
    parser.add_argument("--rrf-k", type=int)
    parser.add_argument("--result-limit", type=int)
    parser.add_argument("--max-per-passage", type=int)
    index_options = parser.add_mutually_exclusive_group()
    index_options.add_argument("--rebuild-index", action="store_true", help="Rebuild this corpus index")
    index_options.add_argument("--no-index-cache", action="store_true", help="Use memory-only vectors")
    args = parser.parse_args()
    if args.retrieval is not None and args.mode != "rag":
        parser.error("--retrieval applies to --mode rag")
    requested = PRESETS.get(args.preset)
    strategy = (args.retrieval or (requested.strategy if requested else "semantic")
                if args.mode == "rag" else args.mode)
    if requested is not None and requested.strategy != strategy:
        parser.error("--preset must match the retrieval strategy")
    preset = requested or DEFAULT_PRESETS.get(strategy)
    use_hybrid = strategy == "hybrid"
    hybrid_options = {
        name: value for name, value in (
            ("candidate_depth", args.candidate_depth), ("smoothing", args.rrf_k),
            ("limit", args.result_limit), ("max_per_passage", args.max_per_passage),
        ) if value is not None
    }
    if hybrid_options and not use_hybrid:
        parser.error("RRF options require hybrid retrieval")
    if args.mode == "keyword" and (args.rebuild_index or args.no_index_cache):
        parser.error("Index options require semantic, hybrid, or RAG mode")
    if args.min_score is not None and args.mode == "keyword":
        parser.error("--min-score requires semantic, hybrid, or RAG mode")
    if args.min_score is not None and not -1 <= args.min_score <= 1:
        parser.error("--min-score must be between -1 and 1")
    if any(value < (0 if key == "smoothing" else 1)
           for key, value in hybrid_options.items()):
        parser.error("RRF smoothing must be nonnegative and other hybrid limits must be positive")
    generator = None
    safe_errors = (ProfileError,)
    try:
        snapshot = load_snapshot(args.profile)
        passages = list(snapshot.passages)
        if args.mode == "rag":
            if snapshot.profile != DOCS_ONLY:
                raise ProfileError("Gemini is available only for docs_only.")
            from .generator import GeminiGenerator, GenerationError, load_settings
            from .rag import RagChat, show_answer

            safe_errors += (GenerationError,)
            settings = load_settings()
        semantic = hybrid = None
        if use_hybrid:
            from .hybrid import HybridRetriever
            from .retrieval import ChunkKeywordIndex

            config = replace(preset.hybrid_config(), **hybrid_options)
        if args.mode != "keyword":
            from .semantic import SemanticRetriever, load_model
            from .vector_store import CACHE_DIR

            min_score = preset.cutoff if args.min_score is None else args.min_score
            semantic = SemanticRetriever.from_snapshot(
                snapshot, load_model(), min_score=min_score, rebuild=args.rebuild_index,
                cache_dir=None if args.no_index_cache else CACHE_DIR,
            )
        if use_hybrid:
            hybrid = HybridRetriever(semantic, ChunkKeywordIndex(semantic.chunks), config, min_score)
        print(f"Corpus profile: {snapshot.profile} | Corpus version: {snapshot.corpus_version}")
        print(f"Loaded passages: {len(passages)} | Source roles: {', '.join(snapshot.source_roles)}")
        if semantic is None:
            print("Indexed chunks: no semantic index in keyword mode")
        else:
            print(f"Indexed chunks: {len(semantic.chunks)} | Embedding dimension: {semantic.dimension}")
            print(semantic.index_report.summary())
            changed = min_score != preset.cutoff or (
                use_hybrid and config != preset.hybrid_config()
            )
            print(f"Retrieval preset: {preset.label}" + (" (custom settings)" if changed else ""))
        for notice in snapshot.notices:
            print(notice)
        if snapshot.exclusions:
            print(f"Excluded catalog listings: {len(snapshot.exclusions)}")
        if args.mode == "rag":
            generator = GeminiGenerator(settings)
            print(f"RAG retrieval: {'hybrid' if hybrid is not None else 'semantic'}")
            if hybrid is not None:
                print(hybrid.config.summary())
            rag = RagChat(hybrid or semantic, generator, corpus_profile=snapshot.profile,
                          corpus_version=snapshot.corpus_version)

        def display(question):
            if generator is None:
                show_results(question, passages, semantic, hybrid)
            else:
                show_answer(rag.ask(question))

    except safe_errors as error:
        print(f"Could not start retrieval: {error}", file=sys.stderr)
        return 1
    except (ImportError, OSError, RuntimeError, ValueError):
        print("Could not start retrieval. Check the corpus and installed dependencies.",
              file=sys.stderr)
        return 1

    try:
        return run_questions(args.question, display, safe_errors)
    finally:
        if generator is not None:
            generator.close()


def run_questions(question, display, safe_errors=()) -> int:
    """Run one question or continue prompting after recoverable failures."""
    if question is not None:
        try:
            display(question)
        except (OSError, RuntimeError, ValueError) as error:
            report_search_error(error, safe_errors)
            return 1
        return 0

    print("Type a question, or press Enter on an empty line to exit.")
    while True:
        try:
            question = input("\nQuestion > ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0
        if not question:
            return 0
        try:
            display(question)
        except (OSError, RuntimeError, ValueError) as error:
            report_search_error(error, safe_errors)


def report_search_error(error, safe_errors):
    if isinstance(error, safe_errors):
        message = str(error)
    elif isinstance(error, ValueError) and str(error).startswith("Embedding input exceeds"):
        message = "Question exceeds the embedding model input limit. Shorten it and try again."
    else:
        message = "The retrieval request failed."
    print(f"Could not search: {message}", file=sys.stderr)


if __name__ == "__main__":
    raise SystemExit(main())
