"""Opt-in live Gemini smoke test using six fixed project questions."""

import argparse
import sys

from .generator import GeminiGenerator, GenerationError, load_settings
from .corpus import load_passages
from .rag import RagChat, show_answer
from .semantic import SemanticRetriever, load_model


QUESTIONS = (
    "What is a Tool Candidate?",
    "What is the difference between an AI Tool and an AI Mention?",
    "Does visiting an application prove confidential information was submitted?",
    "How is contextual risk evaluated?",
    "What is the risk tier of a specific employee's ChatGPT usage?",
    "How do I bake a chocolate cake?",
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true",
                        help="Authorize sending questions and retrieved project excerpts to Gemini")
    if not parser.parse_args().live:
        parser.error("--live is required to authorize Gemini requests and applicable API usage.")

    try:
        settings = load_settings()
        retriever = SemanticRetriever(load_passages(), load_model())
        generator = GeminiGenerator(settings)
        try:
            chat = RagChat(retriever, generator)
            results = []
            for question in QUESTIONS:
                print(f"\nQuestion: {question}")
                result = chat.ask(question)
                show_answer(result)
                results.append(result)
        finally:
            generator.close()
    except GenerationError as error:
        print(f"Gemini smoke test failed: {error}", file=sys.stderr)
        return 1
    except (ImportError, OSError, RuntimeError, ValueError):
        print("Gemini smoke test could not complete. Check local retrieval resources.", file=sys.stderr)
        return 1

    if not all(result.cited_sources for result in results[:4]):
        print("Review required: a project question returned no cited answer.", file=sys.stderr)
        return 1
    if any(result.status == "sufficient" for result in results[-2:]):
        print("Review required: a question lacking supporting evidence was marked sufficient.",
              file=sys.stderr)
        return 1
    print("\nReview the cited excerpts and confirm the last two answers assign no employee risk tier and give no recipe.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
