"""Local Streamlit interface for the independent Cyera retriever."""

import sys
from dataclasses import dataclass
from pathlib import Path
from threading import Lock

import streamlit as st

# Streamlit executes this file as a script. Resolve package imports from the repo.
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rag_bot import semantic
from rag_bot.catalog import catalog_details
from rag_bot.corpus import Passage
from rag_bot.profiles import DOCS_ONLY, PROFILE_NAMES, ProfileError, load_snapshot
from rag_bot.evaluation_view import show_evaluation
from rag_bot.generator import GeneratedAnswer, GenerationError, GeminiGenerator, load_settings
from rag_bot.hybrid import HybridConfig, HybridResult, HybridRetriever
from rag_bot.presets import PRESETS, SEMANTIC_STABLE
from rag_bot.prompts import GroundedPrompt
from rag_bot.rag import RagAnswer, RagChat
from rag_bot.retrieval import ChunkKeywordIndex, SearchResult, search
from rag_bot.vector_store import CACHE_DIR


KEYWORD = "Keyword Search"
SEMANTIC = "Semantic Search"
GEMINI = "RAG — Gemini"
DEMO = "Demo — Mock Generation"
HYBRID = "Hybrid Search"
MODES = (KEYWORD, SEMANTIC, HYBRID, GEMINI, DEMO)
QUESTIONS = (
    "What is a Tool Candidate?",
    "What is the difference between an AI Tool and an AI Mention?",
    "How is contextual risk evaluated?",
    "Does visiting an application prove confidential information was submitted?",
    "What is the risk tier of a specific employee's ChatGPT usage?",
    "Can an AI marketing claim alone establish what software actually does?",
    "Show chunk daaa5efada9a909ccb56.",
    "How do I bake a chocolate cake?",
)
EXAMPLE_NOTES = {
    QUESTIONS[0]: "Definition · Semantic — Stable",
    QUESTIONS[2]: "Compare component ranks · Hybrid Search with diagnostics",
    QUESTIONS[4]: "Scope limit · Demo surfaces background; employee records are unavailable",
    QUESTIONS[5]: "Paraphrase · Semantic — Stable",
    QUESTIONS[6]: "Exact reference · Hybrid Search",
    QUESTIONS[7]: "Out-of-domain abstention · Semantic or Hybrid Search",
}


@st.cache_resource(show_spinner=False)
def cached_model(model_name, revision):
    return semantic.load_model(), Lock()


@st.cache_resource(show_spinner=False)
def cached_index(profile, corpus_version, model_name, revision, chunking_signature,
                 cache_dir, _snapshot):
    model, lock = cached_model(model_name, revision)
    with lock:
        index = semantic.SemanticRetriever.from_snapshot(_snapshot, model, cache_dir=cache_dir)
        return index, lock, ChunkKeywordIndex(index.chunks)


def load_index(snapshot, cache_dir, rebuild=False):
    arguments = (snapshot.profile, snapshot.corpus_version, semantic.MODEL_NAME,
                 semantic.MODEL_REVISION, semantic.chunking_config(), cache_dir, snapshot)
    if not rebuild:
        return cached_index(*arguments)
    model, lock = cached_model(semantic.MODEL_NAME, semantic.MODEL_REVISION)
    with lock:
        result = semantic.SemanticRetriever.from_snapshot(
            snapshot, model, cache_dir=cache_dir, rebuild=True
        )
    cached_index.clear(*arguments)
    return result, lock, ChunkKeywordIndex(result.chunks)


class TurnRetriever:
    """Capture the results of one search without changing the shared index."""

    def __init__(self, retrieve, lock):
        self.retrieve = retrieve
        self.lock = lock
        self.matches = []

    def search(self, question):
        with self.lock:
            self.matches = self.retrieve(question)
        return self.matches


class DemoGenerator:
    """Return a deterministic reference to the first excerpt in the actual prompt."""

    def generate(self, prompt: GroundedPrompt) -> GeneratedAnswer:
        return GeneratedAnswer(
            "The highest-ranked excerpt is shown under citation 1.",
            "partial",
            (prompt.evidence[0].label,),
            ("This simulation selects an excerpt by rank alone. It does not assess claim support.",),
        )


@dataclass(frozen=True)
class Turn:
    question: str
    mode: str
    corpus_profile: str
    corpus_version: str
    strategy: str
    preset: str = "Passage keyword"
    cutoff: float | None = None
    result_limit: int | None = None
    hybrid_config: HybridConfig | None = None
    matches: tuple[SearchResult | semantic.SemanticResult | HybridResult, ...] = ()
    answer: RagAnswer | None = None
    error: str | None = None


def answer_question(question, mode, snapshot, index, lock, cutoff, settings, consent,
                    strategy, keyword_index, hybrid_config, preset_label="Passage keyword"):
    result_limit = hybrid_config.limit if hybrid_config is not None else (
        SEMANTIC_STABLE.limit if strategy == "semantic" else None
    )

    def turn(**kwargs):
        return Turn(question, mode, snapshot.profile, snapshot.corpus_version,
                    strategy, preset=preset_label, result_limit=result_limit,
                    hybrid_config=hybrid_config, **kwargs)

    if mode == GEMINI and snapshot.profile != DOCS_ONLY:
        return turn(error="Gemini is available only for docs_only.")
    if mode == KEYWORD:
        return turn(matches=tuple(search(question, snapshot.passages)))

    if index is None:
        return turn(cutoff=cutoff, error="The local embedding model or index is unavailable.")
    if hybrid_config is not None:
        retrieve = HybridRetriever(index, keyword_index, hybrid_config, cutoff).search
    else:
        def retrieve(text):
            return index.search(text, min_score=cutoff, limit=result_limit)

    retriever = TurnRetriever(retrieve, lock)
    if mode == GEMINI and (not consent or settings is None):
        return turn(cutoff=cutoff,
                    error="Configure Gemini and opt in before submitting a Gemini question.")

    try:
        if mode in (SEMANTIC, HYBRID):
            retriever.search(question)
            answer = None
        elif mode == DEMO:
            answer = RagChat(retriever, DemoGenerator(), corpus_profile=snapshot.profile,
                             corpus_version=snapshot.corpus_version).ask(question)
        else:
            generator = GeminiGenerator(settings)
            try:
                answer = RagChat(retriever, generator, corpus_profile=snapshot.profile,
                                 corpus_version=snapshot.corpus_version).ask(question)
            finally:
                generator.close()
        return turn(cutoff=cutoff, matches=tuple(retriever.matches), answer=answer)
    except GenerationError as error:
        return turn(cutoff=cutoff, matches=tuple(retriever.matches), error=str(error))
    except ValueError as error:
        message = ("The question exceeds the embedding model's input limit. Shorten it and try again."
                   if str(error).startswith("Embedding input exceeds") else
                   "Retrieval could not process this question.")
        return turn(cutoff=cutoff, matches=tuple(retriever.matches), error=message)
    except (RuntimeError, OSError):
        return turn(cutoff=cutoff, matches=tuple(retriever.matches),
                    error="This request failed. Try again or switch to a local retrieval mode.")


def show_source(label, passage: Passage, chunk=None, score=None, score_name=""):
    title = f"{label} · {passage.source_path} · {passage.heading}"
    if score is not None:
        precision = 6 if score_name == "RRF" else 3
        title += f" · {score_name} {score:.{precision}f}"
    with st.expander(title):
        st.text(f"Source: {passage.source_path}\nHeading: {passage.heading}\n"
                f"Passage ID: {passage.passage_id}\nSource role: {passage.source_role}\n"
                f"Content version: {passage.content_version}")
        if passage.catalog is not None:
            st.text(catalog_details(passage.catalog))
        if chunk is not None:
            st.text(f"Chunk ID: {chunk.chunk_id}\nCharacters: {chunk.start}:{chunk.end}")
        st.text(chunk.text if chunk is not None else passage.text)


def show_turn(turn, show_sources, show_diagnostics):
    with st.chat_message("user"):
        st.text(turn.question)
    with st.chat_message("assistant"):
        st.caption(f"{turn.mode} · {turn.preset}")
        with st.expander("Turn details"):
            st.text(f"Retrieval strategy: {turn.strategy}\nCorpus: {turn.corpus_profile}"
                    f"\nCorpus version: {turn.corpus_version}")
            if turn.result_limit is not None:
                st.text(f"Result limit: {turn.result_limit}")
        if turn.mode == DEMO:
            st.info("Simulated response · Gemini was not used")
        if turn.error:
            st.error(f"Request failed: {turn.error}")
        elif turn.answer is not None:
            if turn.mode == GEMINI and turn.matches:
                st.caption("Gemini evaluated the retrieved evidence" if turn.answer.status == "insufficient"
                           else "Gemini-generated response")
            elif not turn.matches:
                st.info("No relevant evidence was retrieved.")
            st.text(turn.answer.answer)
            st.caption(f"Answer status: {turn.answer.status}")
            for limitation in turn.answer.limitations:
                st.text(f"Limitation: {limitation}")
        elif turn.matches:
            st.text(f"{len(turn.matches)} ranked result(s).")
        else:
            st.info("No relevant evidence was retrieved.")

        if turn.matches and turn.corpus_profile == DOCS_ONLY:
            st.caption("Project documentation can provide governance background. "
                       "Case-specific activity, approvals, submissions, and risk assessments "
                       "require evidence outside this corpus.")

        if turn.hybrid_config is not None:
            st.caption(f"{turn.hybrid_config.summary()}, cosine cutoff={turn.cutoff:g}")
        elif turn.cutoff is not None:
            st.caption(f"Cosine cutoff: {turn.cutoff:g}")
        score_name = {
            "keyword": "Keyword score", "semantic": "Cosine similarity", "hybrid": "RRF",
        }[turn.strategy]
        if show_diagnostics:
            with st.expander("Retrieval diagnostics"):
                st.text(f"Returned results: {len(turn.matches)}")
                if turn.cutoff is not None:
                    st.text(f"Provisional cosine cutoff: {turn.cutoff:.2f}")
                for rank, match in enumerate(turn.matches, 1):
                    precision = 6 if isinstance(match, HybridResult) else 3
                    st.text(f"Rank {rank} · {score_name} {match.score:.{precision}f}")
                    if isinstance(match, HybridResult):
                        st.text(match.diagnostics())
        if not show_sources:
            return
        if turn.answer is not None and turn.answer.cited_sources:
            st.markdown("**Cited sources**")
            scores = {match.chunk.chunk_id: match.score for match in turn.matches}
            for item in turn.answer.cited_sources:
                show_source(f"Citation {item.label}", item.chunk.passage, item.chunk,
                            scores.get(item.chunk.chunk_id), score_name)
        if turn.matches:
            st.markdown("**Retrieved evidence**")
            for rank, match in enumerate(turn.matches, 1):
                chunk = getattr(match, "chunk", None)
                passage = match.passage if chunk is None else chunk.passage
                show_source(f"Rank {rank}", passage, chunk, match.score, score_name)


def main():
    st.set_page_config(page_title="AI Governance Assistant", layout="centered")
    st.title("AI Governance Assistant")
    st.caption("Cyera | AI Studio | Independent RAG Prototype")
    assistant_tab, evaluation_tab = st.tabs(("Assistant", "Retrieval evaluation"))
    with assistant_tab:
        assistant_view()
    with evaluation_tab:
        try:
            version = load_snapshot(DOCS_ONLY).corpus_version
        except (OSError, ValueError):
            version = None
        show_evaluation(version)


def assistant_view():
    st.session_state.setdefault("turns", [])

    with st.sidebar:
        st.header("Retrieval settings")
        mode = st.selectbox("Operating mode", MODES, index=1)
        profile = st.selectbox("Corpus profile", PROFILE_NAMES)
        strategy = {KEYWORD: "keyword", SEMANTIC: "semantic", HYBRID: "hybrid"}.get(mode)
        if strategy is None:
            strategy = st.selectbox("Retrieval strategy", ("semantic", "hybrid"))
        cutoff = None
        hybrid_config = None
        preset_label = "Passage keyword"
        if strategy != "keyword":
            options = [key for key, preset in PRESETS.items() if preset.strategy == strategy]
            selected_preset = st.selectbox("Retrieval preset", options,
                                           format_func=lambda key: PRESETS[key].label)
            preset = PRESETS[selected_preset]
            preset_label = preset.label
            with st.expander("Advanced retrieval settings"):
                cutoff = st.number_input(
                    "Minimum cosine similarity", -1.0, 1.0, preset.cutoff,
                    step=0.05, format="%.2f", key=f"cutoff-{preset.key}",
                )
                if strategy == "hybrid":
                    smoothing = st.number_input("RRF smoothing", min_value=0, value=preset.smoothing,
                                                key=f"smoothing-{preset.key}")
                    depth = st.number_input("Candidates per method", min_value=1, value=preset.depth,
                                            key=f"depth-{preset.key}")
                    limit = st.number_input("Final result limit", min_value=1, value=preset.limit,
                                            key=f"limit-{preset.key}")
                    cap = st.number_input("Maximum per passage", min_value=1, value=preset.cap,
                                          placeholder="No cap", key=f"cap-{preset.key}")
                    hybrid_config = HybridConfig(smoothing, depth, limit, cap)
                if cutoff != preset.cutoff or (hybrid_config is not None
                                               and hybrid_config != preset.hybrid_config()):
                    preset_label += " (custom settings)"
        st.caption(f"Active retrieval: {preset_label}")

        show_sources = st.toggle("Show source evidence", value=True)
        show_diagnostics = st.toggle("Show retrieval diagnostics")
        if st.button("Clear conversation"):
            st.session_state.turns.clear()

        st.subheader("Knowledge base")
        st.text(f"Corpus profile: {profile}")
        st.text(semantic.MODEL_NAME)
        snapshot = None
        try:
            snapshot = load_snapshot(profile)
            st.text(f"Corpus version: {snapshot.corpus_version}")
            st.text(f"Loaded passages: {len(snapshot.passages)}")
            st.text(f"Source roles: {', '.join(snapshot.source_roles)}")
            for notice in snapshot.notices:
                st.caption(notice)
            if snapshot.exclusions:
                st.text(f"Excluded catalog listings: {len(snapshot.exclusions)}")
        except ProfileError as error:
            st.warning(str(error))
        except (OSError, ValueError):
            st.error("The approved corpus could not be loaded.")
        index = lock = keyword_index = None
        if snapshot is not None and mode != KEYWORD:
            persist = st.toggle("Persistent vector cache", value=True, key="persist_vectors")
            rebuild = st.button("Rebuild current index", disabled=not persist)
            try:
                with st.spinner("Preparing local embedding index…"):
                    index, lock, keyword_index = load_index(snapshot, CACHE_DIR if persist else None, rebuild)
                st.text(f"Indexed chunks: {len(index.chunks)}")
                st.text(f"Embedding dimension: {index.dimension}")
                st.caption(index.index_report.summary())
            except (ImportError, OSError, RuntimeError, ValueError):
                st.warning("The embedding index is unavailable. Keyword Search is still available.")
        elif snapshot is not None:
            st.caption("Keyword Search uses no semantic index.")

        st.subheader("Generation")
        settings = None
        consent = False
        if mode == GEMINI and profile != DOCS_ONLY:
            st.warning("Gemini is available only for docs_only.")
        elif mode == GEMINI:
            try:
                settings = load_settings()
                st.caption("Credentials and model are configured. Connectivity is unverified.")
            except GenerationError as error:
                st.warning(str(error))
            st.caption("Gemini live verification is pending after a prepaid-credit billing error.")
            consent = st.checkbox("Send my questions and retrieved project excerpts to Gemini",
                                  key="gemini_consent")
        elif mode == DEMO:
            st.caption("Local simulation. No API requests.")
        else:
            st.caption("Local retrieval. Generation is inactive.")

    blocked = (snapshot is None or (mode != KEYWORD and index is None)
               or (mode == GEMINI and (not consent or settings is None)))
    st.caption("Each question is handled independently. The documentation index contains "
               "project rules and terminology. Case-specific enterprise records are unavailable.")
    selected = None
    with st.expander("Suggested questions"):
        for number, example in enumerate(QUESTIONS):
            if st.button(example, key=f"example_{number}", disabled=blocked):
                selected = example
            if example in EXAMPLE_NOTES:
                st.caption(EXAMPLE_NOTES[example])
    for turn in st.session_state.turns:
        show_turn(turn, show_sources, show_diagnostics)

    entered = st.chat_input("Ask about the approved project documents", disabled=blocked)
    question = (selected or entered or "").strip()
    if question and not blocked:
        with st.spinner("Retrieving project evidence…" if mode != GEMINI else
                        "Retrieving evidence and preparing the Gemini response…"):
            turn = answer_question(question, mode, snapshot, index, lock, cutoff, settings, consent,
                                   strategy, keyword_index, hybrid_config, preset_label)
        st.session_state.turns.append(turn)
        show_turn(turn, show_sources, show_diagnostics)


if __name__ == "__main__":
    main()
