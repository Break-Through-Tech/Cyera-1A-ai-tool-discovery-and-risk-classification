"""Compare every category method on validation descriptions and validation homepages; never reads test."""

from __future__ import annotations

import json
import time
from pathlib import Path

import methods
from evaluate import VIEWS, labels_of, load_splits, load_transfer, page_text, score, summary_line


HERE = Path(__file__).resolve().parent
OUT = HERE / "validation_results.json"


def candidates(train_text: list[str], train_labels: list[str], labels: list[str]) -> dict:
    """Method id -> (trained on catalog labels, score function over texts)."""
    found = {}
    for c in (1, 4, 16):
        for weight in (None, "balanced"):
            found[f"tfidf_lr[C={c},{weight or 'plain'}]"] = (
                True, methods.tfidf_lr(train_text, train_labels, labels, c=c, class_weight=weight))
    for name in methods.EMBEDDERS:
        short = name.split("/")[-1]
        found[f"zero_shot[{short}]"] = (False, methods.zero_shot(name, labels))
        for k in (5, 15, 30):
            found[f"knn[{short},k={k}]"] = (True, methods.knn(name, train_text, train_labels, labels, k=k))
        for c in (1, 10):
            for weight in (None, "balanced"):
                found[f"embed_lr[{short},C={c},{weight or 'plain'}]"] = (
                    True, methods.embed_lr(name, train_text, train_labels, labels, c=c, class_weight=weight))
    return found


def timed(function, texts: list[str]):
    started = time.perf_counter()
    scores = function(texts)
    return scores, time.perf_counter() - started


def main() -> None:
    splits = load_splits()
    labels = labels_of(splits["train"])
    train_text = [row["description_text"] for row in splits["train"]]
    train_labels = [row["category"] for row in splits["train"]]
    validation = splits["validation"]
    pages = {split: load_transfer(split) for split in ("validation", "train")}
    sets = {"validation_descriptions": ([row["description_text"] for row in validation],
                                        [row["category"] for row in validation])}
    for split, rows in pages.items():
        for view in VIEWS:
            sets[f"{split}_pages[{view}]"] = ([page_text(page, view) for page in rows],
                                              [page["category"] for page in rows])

    results = {}
    for method, (trained, function) in candidates(train_text, train_labels, labels).items():
        results[method] = {}
        for name, (texts, expected) in sets.items():
            if trained and name.startswith("train_pages"):
                continue
            scores, seconds = timed(function, texts)
            results[method][name] = score(expected, scores, labels, seconds=seconds)

    states = {"validation_descriptions": [methods.description_state(text) for text in sets["validation_descriptions"][0]]}
    for split, rows in pages.items():
        states[f"{split}_pages[full]"] = [methods.page_state(page) for page in rows]
    results["jev"] = {}
    for name, state in states.items():
        scores, cost, seconds = methods.jev(state, labels)
        results["jev"][name] = score(sets[name][1], scores, labels, cost_usd=cost, seconds=seconds)

    OUT.write_text(json.dumps({"labels": labels, "results": results}, indent=1) + "\n", encoding="utf-8")
    for name in sets:
        print(f"\n== {name}")
        ranked = sorted(((method, sets_[name]) for method, sets_ in results.items() if name in sets_),
                        key=lambda item: -item[1]["accuracy"])
        for method, result in ranked:
            print(summary_line(method, result))


if __name__ == "__main__":
    main()
