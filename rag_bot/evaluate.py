"""Offline, versioned documentation retrieval evaluation."""

import argparse
import json
import math
import platform
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, replace
from hashlib import sha256
from pathlib import Path
from statistics import mean, median
from time import perf_counter

import numpy as np

from .hybrid import HybridConfig, HybridRetriever, fuse
from .profiles import DOCS_ONLY, load_snapshot
from .retrieval import ChunkKeywordIndex, search
from .semantic import MODEL_NAME, MODEL_REVISION, SemanticRetriever, load_model


DIRECTORY = Path(__file__).with_name("evaluation")
K = 5
RULE_VERSION = "direct-coverage-and-abstention-v1"
CUTOFFS = (0.15, 0.20, 0.25, 0.30, 0.35, 0.40)
BEHAVIORS = {
    "definition": ("answerable", "retrieve_direct"),
    "paraphrase": ("answerable", "retrieve_direct"),
    "risk_policy": ("answerable", "retrieve_direct"),
    "multi_evidence": ("answerable", "retrieve_direct"),
    "identifier": ("answerable", "retrieve_direct"),
    "out_of_domain": ("out_of_domain", "empty"),
    "unsupported": ("insufficient", "context_only"),
}


@dataclass(frozen=True)
class Settings:
    cutoff: float = 0.25
    smoothing: int = 60
    depth: int = 20
    cap: int | None = 2
    limit: int = 5

    def hybrid(self, count):
        return HybridConfig(self.smoothing, self.depth, self.limit,
                            self.cap if self.cap is not None else max(count, 1))


DEFAULT = Settings()


def load_benchmark(path, corpus_version, chunk_map):
    """Check schema, relevance identities, grades, and partition isolation."""
    raw = path.read_bytes()
    data = json.loads(raw)
    if (not isinstance(data, dict) or data.get("corpus_profile") != DOCS_ONLY
            or data.get("corpus_version") != corpus_version):
        raise ValueError("Benchmark corpus version or profile does not match the current corpus.")
    version, questions = data.get("version"), data.get("questions")
    if not isinstance(version, str) or not version or not isinstance(questions, list):
        raise ValueError("Invalid benchmark header.")
    identities, question_text, partitions, families = set(), set(), set(), {}
    for q in questions:
        fields = ("id", "text", "category", "partition", "family",
                  "answerability", "expected_behavior", "rationale")
        if not isinstance(q, dict) or any(
            not isinstance(q.get(key), str) or not q[key].strip() for key in fields
        ):
            raise ValueError("Missing benchmark question metadata.")
        text_key = " ".join(q["text"].casefold().split())
        if q["id"] in identities or text_key in question_text:
            raise ValueError("Duplicate benchmark question ID or text.")
        identities.add(q["id"])
        question_text.add(text_key)
        if q["partition"] not in {"calibration", "held_out"}:
            raise ValueError("Invalid benchmark partition.")
        partitions.add(q["partition"])
        family_partition = families.setdefault(q["family"], q["partition"])
        if family_partition != q["partition"]:
            raise ValueError("Question family crosses benchmark partitions.")
        if BEHAVIORS.get(q["category"]) != (q["answerability"], q["expected_behavior"]):
            raise ValueError("Invalid benchmark category or expected behavior.")
        grades = q.get("chunks")
        groups = q.get("evidence_groups")
        if (not isinstance(grades, dict) or not isinstance(q.get("passages"), dict)
                or any(cid not in chunk_map or type(grade) is not int or grade not in {1, 2}
                       for cid, grade in grades.items())):
            raise ValueError("Invalid grade or stale chunk ID.")
        parents = {}
        for chunk_id, grade in grades.items():
            parent = chunk_map[chunk_id]
            parents[parent] = max(grade, parents.get(parent, 0))
        if (parents != q["passages"]
                or any(type(grade) is not int for grade in q["passages"].values())):
            raise ValueError("Invalid or stale passage relevance IDs.")
        if q["answerability"] == "answerable" and 2 not in grades.values():
            raise ValueError("Answerable questions need direct evidence.")
        if q["answerability"] == "out_of_domain" and grades:
            raise ValueError("Out-of-domain questions cannot list relevant evidence.")
        if q["answerability"] == "insufficient" and (not grades or 2 in grades.values()):
            raise ValueError("Insufficient questions need background-only labels.")
        if not isinstance(groups, list) or any(
            not isinstance(group, list) or not group
            or any(not isinstance(cid, str) or grades.get(cid) != 2 for cid in group)
            for group in groups
        ):
            raise ValueError("Invalid multi-evidence groups.")
        if ((q["category"] == "multi_evidence" and len(groups) < 2)
                or (q["category"] != "multi_evidence" and groups)):
            raise ValueError("Multi-evidence group count is invalid.")
    if partitions != {"calibration", "held_out"}:
        raise ValueError("Both benchmark partitions must be present.")
    return data, sha256(raw).hexdigest()


def unique(ids):
    return list(dict.fromkeys(ids))


def ranking_metrics(ids, labels, k=K):
    ranked = unique(ids)[:k]
    direct = {identity for identity, grade in labels.items() if grade == 2}
    direct_ranks = [rank for rank, identity in enumerate(ranked, 1) if identity in direct]

    def dcg(grades):
        return sum((2 ** grade - 1) / math.log2(rank + 1)
                   for rank, grade in enumerate(grades, 1))

    ideal = dcg(sorted(labels.values(), reverse=True)[:k])
    return {
        "hit": int(bool(direct_ranks)),
        "precision": len(direct_ranks) / k,
        "recall": len(direct_ranks) / len(direct) if direct else 0,
        "rr": 1 / direct_ranks[0] if direct_ranks else 0,
        "ndcg": dcg([labels.get(identity, 0) for identity in ranked]) / ideal if ideal else 0,
    }


def outcome(question, passage_ids, chunk_ids, chunk_map):
    ranked = {"passage": unique(passage_ids)[:K]}
    if chunk_ids is not None:
        ranked["chunk"] = unique(chunk_ids)[:K]
    result = {"distinct_passages": len(ranked["passage"])}
    for unit, ids in ranked.items():
        labels = question[unit + "s"]
        category = question["answerability"]
        metrics = {}
        if category == "answerable":
            metrics.update(ranking_metrics(ids, labels))
            metrics["false_abstention"] = int(not ids)
            groups = question["evidence_groups"]
            if groups:
                if unit == "passage":
                    groups = [{chunk_map[cid] for cid in group} for group in groups]
                retrieved = set(ids)
                found = [bool(retrieved.intersection(group)) for group in groups]
                metrics["evidence_coverage"] = mean(found)
                metrics["all_evidence_groups"] = int(all(found))
        elif category == "out_of_domain":
            metrics["correct_empty"] = int(not ids)
        else:
            metrics["background_hit"] = int(any(labels.get(identity) == 1 for identity in ids))
            metrics["no_results"] = int(not ids)
        result[unit] = metrics
    return result


def describe(question, results):
    rows = []
    for hit in results:
        chunk = getattr(hit, "chunk", None)
        passage = chunk.passage if chunk is not None else hit.passage
        row = {"rank": len(rows) + 1, "passage_id": passage.passage_id,
               "source_path": passage.source_path, "heading": passage.heading,
               "passage_grade": question["passages"].get(passage.passage_id, 0),
               "score": hit.score}
        if chunk is not None:
            row.update(chunk_id=chunk.chunk_id, chunk_grade=question["chunks"].get(chunk.chunk_id, 0))
        if hasattr(hit, "keyword_rank"):
            row.update(keyword_rank=hit.keyword_rank, keyword_score=hit.keyword_score,
                       semantic_rank=hit.semantic_rank, semantic_score=hit.semantic_score)
        rows.append(row)
    passage_ids = [row["passage_id"] for row in rows]
    chunk_ids = [row["chunk_id"] for row in rows] if results and "chunk_id" in rows[0] else None
    return rows, passage_ids, chunk_ids


def summarize(records):
    def group_summary(group):
        result = {"queries": len(group)}
        for unit in ("passage", "chunk"):
            metrics = defaultdict(list)
            for record in group:
                for key, value in record["measures"].get(unit, {}).items():
                    metrics[key].append(value)
            if metrics:
                result[unit] = {key: mean(values) for key, values in metrics.items()}
                result[unit + "_denominators"] = {key: len(values) for key, values in metrics.items()}
        if group:
            result["mean_distinct_passages"] = mean(r["measures"]["distinct_passages"] for r in group)
            latency = sorted(r["latency_ms"] for r in group if r["latency_ms"] is not None)
            if latency:
                result["latency_ms"] = {"mean": mean(latency), "median": median(latency),
                                        "p95_nearest_rank": latency[math.ceil(.95 * len(latency)) - 1]}
        return result

    categories = sorted({record["category"] for record in records})
    return {"overall": group_summary(records),
            "categories": {category: group_summary([r for r in records if r["category"] == category])
                           for category in categories}}


def measure(questions, retrieve, chunk_map, *, chunk_based=True, timing=False):
    records = []
    for q in questions:
        started = perf_counter()
        hits = retrieve(q["text"])
        elapsed_ms = (perf_counter() - started) * 1000 if timing else None
        rows, passage_ids, chunk_ids = describe(q, hits)
        metrics = outcome(q, passage_ids, (chunk_ids or []) if chunk_based else None, chunk_map)
        unit = metrics["chunk" if chunk_based else "passage"]
        errors = []
        if unit.get("false_abstention"):
            errors.append("false_abstention")
        if q["answerability"] == "answerable" and not unit["hit"]:
            errors.append("no_direct_evidence")
        if unit.get("correct_empty") == 0:
            errors.append("out_of_domain_results")
        if unit.get("evidence_coverage", 1) < 1:
            errors.append("incomplete_evidence_groups")
        records.append({"id": q["id"], "category": q["category"],
                        "answerability": q["answerability"], "rankings": rows,
                        "passage_ranking": unique(passage_ids)[:K], "measures": metrics,
                        "errors": errors, "latency_ms": elapsed_ms})
    return {"summary": summarize(records), "questions": records}


def selection_score(overall):
    """Prefer direct evidence, then reward coverage and correct empty retrieval."""
    p, c = overall["passage"], overall["chunk"]
    return (.30 * mean((p["hit"], c["hit"]))
            + .20 * mean((p["ndcg"], c["ndcg"]))
            + .15 * c["evidence_coverage"] + .35 * c["correct_empty"])


def cached_candidates(questions, index, keywords):
    count = max(1, len(index.chunks))
    return {
        q["text"]: (keywords.search(q["text"], limit=count),
                    index.search(q["text"], min_score=-1, limit=count))
        for q in questions
    }


def calibrate(questions, index, keywords, chunk_map):
    if not questions or any(q["partition"] != "calibration" for q in questions):
        raise ValueError("Calibration accepts only calibration questions.")
    candidates = cached_candidates(questions, index, keywords)
    sweep = []

    def evaluate_settings(method, stage, settings):
        def retrieve(text):
            lexical, vectors = candidates[text]
            vectors = [hit for hit in vectors if hit.score >= settings.cutoff]
            if method == "semantic":
                return vectors[:K]
            lexical = lexical[:settings.depth]
            exact = keywords.exact_references(text, {hit.chunk.chunk_id for hit in lexical})
            return fuse(lexical, vectors, exact, settings.hybrid(len(index.chunks)))

        summary = measure(questions, retrieve, chunk_map)["summary"]["overall"]
        score = selection_score(summary)
        sweep.append({"method": method, "stage": stage, "settings": asdict(settings),
                      "selection_score": score, "metrics": summary})
        return score

    def choose(method, stage, current, field, choices):
        options = [current] + [replace(current, **{field: value}) for value in choices
                               if value != getattr(current, field)]
        # max retains the first entry on ties, preferring the incumbent.
        return max(options, key=lambda settings: evaluate_settings(method, stage, settings))

    semantic = choose("semantic", "cutoff", DEFAULT, "cutoff", CUTOFFS)
    hybrid = DEFAULT
    for field, values in (("cutoff", CUTOFFS), ("smoothing", (10, 30, 60)),
                          ("depth", (5, 10, 20)), ("cap", (1, 2, 3, None)), ("limit", (3, 5))):
        hybrid = choose("hybrid", field, hybrid, field, values)
    return {"semantic": asdict(semantic), "hybrid": asdict(hybrid)}, sweep


def run_methods(questions, snapshot, index, keywords, chunk_map, selected):
    semantic_settings = Settings(**selected["semantic"])
    hybrid_settings = Settings(**selected["hybrid"])
    methods = {
        "passage_keyword": (lambda text: search(text, snapshot.passages), False),
        "chunk_keyword": (lambda text: keywords.search(text, limit=K), True),
        "semantic_baseline": (index.search, True),
        "hybrid_baseline": (HybridRetriever(index, keywords).search, True),
        "semantic_selected": (lambda text: index.search(text, min_score=semantic_settings.cutoff), True),
        "hybrid_selected": (HybridRetriever(index, keywords,
                           hybrid_settings.hybrid(len(index.chunks)), hybrid_settings.cutoff).search, True),
    }
    return {name: measure(questions, func, chunk_map, chunk_based=chunk_based, timing=True)
            for name, (func, chunk_based) in methods.items()}


def write_json(path, data):
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--phase", choices=("calibrate", "evaluate"), required=True)
    parser.add_argument("--output", type=Path, default=DIRECTORY / "results")
    args = parser.parse_args()
    snapshot = load_snapshot(DOCS_ONLY)
    index = SemanticRetriever.from_snapshot(snapshot, load_model())
    chunk_map = {chunk.chunk_id: chunk.passage.passage_id for chunk in index.chunks}
    benchmark, benchmark_hash = load_benchmark(DIRECTORY / "benchmark-v1.json",
                                               snapshot.corpus_version, chunk_map)
    keywords = ChunkKeywordIndex(index.chunks)
    identity = {"benchmark_version": benchmark["version"], "benchmark_sha256": benchmark_hash,
                "corpus_version": snapshot.corpus_version, "model": MODEL_NAME,
                "model_revision": MODEL_REVISION, "rule_version": RULE_VERSION,
                "index_identity": index.store.identity, "k": K}
    args.output.mkdir(parents=True, exist_ok=True)
    frozen_path = args.output / "selection.json"
    if args.phase == "calibrate":
        questions = [q for q in benchmark["questions"] if q["partition"] == "calibration"]
        selected, sweep = calibrate(questions, index, keywords, chunk_map)
        frozen = {"identity": identity, "selected": selected, "sweep": sweep,
                  "calibration_ids": [q["id"] for q in questions]}
        write_json(frozen_path, frozen)
        print(f"Frozen selection: {selected}")
        partition = "calibration"
    else:
        frozen = json.loads(frozen_path.read_bytes())
        expected_ids = [q["id"] for q in benchmark["questions"] if q["partition"] == "calibration"]
        if frozen["identity"] != identity or frozen["calibration_ids"] != expected_ids:
            raise ValueError("Frozen selection does not match the benchmark, model, or calibration IDs.")
        partition = "held_out"
        selected = frozen["selected"]
        questions = [q for q in benchmark["questions"] if q["partition"] == partition]
    report = {"identity": identity, "partition": partition, "partition_ids": [q["id"] for q in questions],
              "baseline_settings": asdict(DEFAULT), "selected": selected,
              "environment": {"python": platform.python_version(), "platform": platform.platform(),
                              "numpy": np.__version__, "device": str(index.model.device),
                              "latency": "single sequential query, excludes indexing and metrics"},
              "methods": run_methods(questions, snapshot, index, keywords, chunk_map, selected)}
    write_json(args.output / f"{partition}.json", report)
    print(f"Wrote {partition} report for {len(questions)} questions.")


if __name__ == "__main__":
    main()
