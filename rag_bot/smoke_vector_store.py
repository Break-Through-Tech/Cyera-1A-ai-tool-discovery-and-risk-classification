"""Benchmark cold and warm persistent docs-only retrieval in separate processes."""

import argparse
import json
import subprocess
import sys
from pathlib import Path
from statistics import mean
from tempfile import TemporaryDirectory
from time import perf_counter

from .profiles import load_snapshot
from .semantic import SemanticRetriever, load_model
from .smoke_semantic import QUESTIONS


def run_worker(cache_dir: Path) -> None:
    """Measure one process and emit a machine-readable ranking and timings."""
    started = perf_counter()
    snapshot = load_snapshot()
    model_started = perf_counter()
    model = load_model()
    model_seconds = perf_counter() - model_started
    index = SemanticRetriever.from_snapshot(snapshot, model, cache_dir=cache_dir)
    ready = perf_counter()
    print("ready", flush=True)
    store = index.store
    manifest = json.loads(store.manifest_path.read_bytes())
    vector = store.directory / f"{manifest['vector_sha256']}.npy"
    timings, rankings = [], []
    for question in QUESTIONS:
        before_query = perf_counter()
        hits = index.search(question)
        timings.append(perf_counter() - before_query)
        rankings.append([(hit.chunk.chunk_id, round(hit.score, 7)) for hit in hits])
        if question == QUESTIONS[0]:
            assert hits and "grouping of identity clues" in hits[0].chunk.text
    assert not rankings[-1]
    print(json.dumps({
        "status": index.index_report.status,
        "model_seconds": model_seconds,
        "index_seconds": index.index_report.initialization_seconds,
        "document_seconds": index.index_report.embedding_seconds,
        "worker_ready_seconds": ready - started,
        "query_mean_seconds": mean(timings),
        "manifest_bytes": store.manifest_path.stat().st_size,
        "vector_bytes": vector.stat().st_size,
        "rankings": rankings,
    }))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--worker-cache", type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.worker_cache is not None:
        run_worker(args.worker_cache)
        return

    runs = []
    with TemporaryDirectory(prefix="rag-vector-smoke-") as directory:
        for _ in range(2):
            before_process = perf_counter()
            with subprocess.Popen(
                [sys.executable, "-B", "-m", "rag_bot.smoke_vector_store",
                 "--worker-cache", directory],
                text=True, stdout=subprocess.PIPE,
            ) as worker:
                ready = worker.stdout.readline().strip()
                startup_seconds = perf_counter() - before_process
                output, _ = worker.communicate()
                if worker.returncode or ready != "ready":
                    raise RuntimeError("Smoke worker failed to initialize.")
            run = json.loads(output)
            run["process_startup_seconds"] = startup_seconds
            runs.append(run)

    cold, warm = runs
    assert cold["status"] == "newly built"
    assert warm["status"] == "loaded from disk"
    assert cold["document_seconds"] is not None and warm["document_seconds"] is None
    assert cold.pop("rankings") == warm.pop("rankings")
    print(json.dumps({"cold": cold, "warm": warm}, indent=2))
    print(f"Cold/warm chunk IDs and scores matched for all {len(QUESTIONS)} smoke questions.")


if __name__ == "__main__":
    main()
