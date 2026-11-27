"""Read frozen evaluation artifacts for display only."""

import json
from hashlib import sha256
from pathlib import Path

from .presets import HYBRID_CALIBRATED
from .semantic import MODEL_NAME, MODEL_REVISION

ROOT = Path(__file__).with_name("evaluation")
METHODS = {
    "passage_keyword": "Passage keyword",
    "chunk_keyword": "Chunk keyword",
    "semantic_baseline": "Semantic",
    "hybrid_baseline": "Hybrid baseline",
    "hybrid_selected": HYBRID_CALIBRATED.label,
}
EXAMPLES = (
    ("DOC-044", "Exact chunk reference", "Hybrid recovered the requested excerpt."),
    ("DOC-051", "Travel false positive", "Both methods retrieved governance material for a travel question."),
    ("DOC-040", "Multiple excerpts", "Both methods missed the deterministic-query excerpt."),
)


def read_evaluation(corpus_version, root=ROOT):
    """Validate provenance and return compact rows without running evaluation."""
    raw = (root / "benchmark-v1.json").read_bytes()
    benchmark = json.loads(raw)
    selection = json.loads((root / "results" / "selection.json").read_bytes())
    identity = selection["identity"]
    if (benchmark["corpus_profile"] != "docs_only"
            or benchmark["corpus_version"] != corpus_version
            or identity["corpus_version"] != corpus_version
            or identity["benchmark_version"] != benchmark["version"]
            or identity["benchmark_sha256"] != sha256(raw).hexdigest()
            or identity["model"] != MODEL_NAME or identity["model_revision"] != MODEL_REVISION
            or identity["k"] != 5):
        raise ValueError("Stale benchmark or model identity.")

    questions = {q["id"]: q for q in benchmark["questions"]}
    partitions = {}
    for partition in ("calibration", "held_out"):
        report = json.loads((root / "results" / f"{partition}.json").read_bytes())
        expected = [qid for qid, question in questions.items() if question["partition"] == partition]
        if (report["identity"] != identity or report["partition_ids"] != expected
                or report["partition"] != partition or report["selected"] != selection["selected"]
                or (partition == "calibration" and expected != selection["calibration_ids"])):
            raise ValueError("Evaluation report does not match the frozen selection.")
        rows = []
        for key, label in METHODS.items():
            result = report["methods"][key]
            overall = result["summary"]["overall"]
            if overall["queries"] != len(expected) or [q["id"] for q in result["questions"]] != expected:
                raise ValueError("Unexpected evaluation report rows.")
            passage = overall["passage"]
            denominators = overall["passage_denominators"]
            latency = overall["latency_ms"]
            rows.append({
                "Method": label,
                "Passage nDCG@5": round(passage["ndcg"], 3),
                "Chunk nDCG@5": round(overall["chunk"]["ndcg"], 3) if "chunk" in overall else None,
                "OOD empty": f"{round(passage['correct_empty'] * denominators['correct_empty'])}/{denominators['correct_empty']}",
                "False abstention": f"{round(passage['false_abstention'] * denominators['false_abstention'])}/{denominators['false_abstention']}",
                "Chunk evidence coverage": (round(overall["chunk"]["evidence_coverage"], 3)
                                            if "chunk" in overall else None),
                "Mean ms": round(latency["mean"], 3),
                "Median ms": round(latency["median"], 3),
                "p95 ms": round(latency["p95_nearest_rank"], 3),
            })
        examples = []
        if partition == "held_out":
            for qid, title, observation in EXAMPLES:
                comparison = []
                for key in ("semantic_baseline", "hybrid_selected"):
                    item = next(q for q in report["methods"][key]["questions"] if q["id"] == qid)
                    first = item["rankings"][0]["heading"] if item["rankings"] else "No results"
                    comparison.append(f"{METHODS[key]}: {first}")
                examples.append((title, questions[qid]["text"], observation, comparison))
        partitions[partition] = (len(expected), rows, examples)
    return benchmark["version"], len(questions), identity, partitions


def show_evaluation(corpus_version):
    import streamlit as st

    st.subheader("Documentation retrieval benchmark")
    st.caption("Small benchmark with analyst-drafted relevance labels awaiting independent human review. "
               "Metrics describe retrieved evidence. Generated-answer accuracy was not measured.")
    try:
        version, count, identity, partitions = read_evaluation(corpus_version)
    except (OSError, ValueError, KeyError, TypeError, AttributeError, StopIteration):
        st.warning("Evaluation reports are missing, incompatible, or stale for the current documentation corpus.")
        return

    st.write(f"{count} questions · {version}")
    with st.expander("Benchmark provenance"):
        st.text(f"Corpus version: {identity['corpus_version']}\nModel revision: {identity['model_revision']}")
    st.caption("OOD means out of domain. Chunk coverage measures required excerpt groups on multi-evidence questions. "
               "A matching passage can still omit a required excerpt.")
    for partition, tab in zip(partitions, st.tabs(("Calibration", "Held-out evaluation"))):
        size, rows, examples = partitions[partition]
        with tab:
            st.write(f"{size} questions")
            st.dataframe(rows, hide_index=True)
            for title, question, observation, comparison in examples:
                with st.expander(title):
                    st.text(question)
                    st.write(observation)
                    st.text("\n".join(comparison))
    st.caption("Latency is from one sequential CPU run, excluding index setup and metric computation.")
