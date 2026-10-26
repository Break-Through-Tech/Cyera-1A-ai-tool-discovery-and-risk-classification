"""Score each frozen candidate once on test descriptions and test-split homepages."""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path

import numpy as np

import methods
from evaluate import labels_of, load_splits, load_transfer, page_text, score, summary_line
from freeze import BGE, FREEZE, FROZEN_FILES, build, embedder_revision


HERE = Path(__file__).resolve().parent
OUT = HERE / "test_results.json"


def main() -> None:
    if OUT.exists():
        raise SystemExit("test_results.json exists; each frozen candidate is scored on test only once")
    freeze = json.loads(FREEZE.read_text(encoding="utf-8"))
    for file in FROZEN_FILES:
        if hashlib.sha256((HERE / file).read_bytes()).hexdigest() != freeze["file_sha256"][file]:
            raise SystemExit(f"{file} changed since the freeze")
    if embedder_revision(BGE) != freeze["embedder_revisions"][BGE]:
        raise SystemExit("Embedding model revision changed since the freeze")

    splits = load_splits()
    labels = labels_of(splits["train"])
    train_text = [row["description_text"] for row in splits["train"]]
    train_labels = [row["category"] for row in splits["train"]]
    test, pages = splits["test"], load_transfer("test")
    sets = {
        "test_descriptions": ([row["description_text"] for row in test],
                              [methods.description_state(row["description_text"]) for row in test],
                              [row["category"] for row in test]),
        "test_pages[full]": ([page_text(page, "full") for page in pages],
                             [methods.page_state(page) for page in pages],
                             [page["category"] for page in pages]),
    }

    results = {}
    for name, config in freeze["candidates"].items():
        function = build(config, train_text, train_labels, labels)
        results[name] = {}
        for set_name, (texts, states, expected) in sets.items():
            started = time.perf_counter()
            scores, cost, jev_seconds = function(texts, states)
            seconds = jev_seconds if config["method"] == "jev" else time.perf_counter() - started
            result = score(expected, scores, labels, cost_usd=cost, seconds=seconds)
            threshold = config["abstain_below_top_score"]
            kept = scores.max(axis=1) >= threshold if threshold is not None else np.zeros(len(expected), bool)
            correct = np.array(labels)[scores.argmax(axis=1)] == np.array(expected)
            result["frozen_threshold"] = {"coverage": float(kept.mean()),
                                          "accuracy_when_answering": float(correct[kept].mean()) if kept.any() else None}
            results[name][set_name] = result

    OUT.write_text(json.dumps({"freeze_sha256": hashlib.sha256(FREEZE.read_bytes()).hexdigest(),
                               "labels": labels, "results": results}, indent=1) + "\n", encoding="utf-8")
    for set_name in sets:
        print(f"\n== {set_name}")
        for name in results:
            result = results[name][set_name]
            at = result["frozen_threshold"]
            print(summary_line(name, result), f" frozen: coverage {at['coverage']:.3f} "
                  f"acc {at['accuracy_when_answering'] or 0:.3f}")


if __name__ == "__main__":
    main()
