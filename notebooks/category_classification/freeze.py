"""Freeze the test candidates and their abstention thresholds, chosen on validation homepages only."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

import methods
from evaluate import labels_of, load_splits, load_transfer, page_text


HERE = Path(__file__).resolve().parent
FREEZE = HERE / "FREEZE.json"
FROZEN_FILES = ("category_descriptions.py", "methods.py", "evaluate.py", "freeze.py", "evaluate_test.py")
TARGET_ACCURACY = 0.70
BGE = "BAAI/bge-small-en-v1.5"
CANDIDATES = {
    "knn[bge-small-en-v1.5,k=15]": {"method": "knn", "embedder": BGE, "k": 15},
    "tfidf_lr[C=4,plain]": {"method": "tfidf_lr", "c": 4, "class_weight": None},
    "embed_lr[bge-small-en-v1.5,C=10,plain]": {"method": "embed_lr", "embedder": BGE, "c": 10, "class_weight": None},
    "jev": {"method": "jev", "model": methods.JEV_MODEL},
}


def build(config: dict, train_text: list[str], train_labels: list[str], labels: list[str]):
    """A scorer over (texts, Jev states) so Jev can take the structured page state the backend sends."""
    if config["method"] == "knn":
        function = methods.knn(config["embedder"], train_text, train_labels, labels, k=config["k"])
    elif config["method"] == "tfidf_lr":
        function = methods.tfidf_lr(train_text, train_labels, labels, c=config["c"], class_weight=config["class_weight"])
    elif config["method"] == "embed_lr":
        function = methods.embed_lr(config["embedder"], train_text, train_labels, labels, c=config["c"],
                                    class_weight=config["class_weight"])
    elif config["method"] == "jev":
        return lambda texts, states: methods.jev(states, labels)
    else:
        raise ValueError(config["method"])
    return lambda texts, states: (function(texts), 0.0, 0.0)


def lowest_threshold(top: np.ndarray, correct: np.ndarray, target: float) -> float | None:
    """The lowest top score whose kept rows (top >= threshold) reach the target accuracy."""
    for threshold in np.unique(top):
        kept = top >= threshold
        if correct[kept].mean() >= target:
            return float(threshold)
    return None


def embedder_revision(name: str) -> str:
    ref = Path.home() / ".cache/huggingface/hub" / f"models--{name.replace('/', '--')}" / "refs/main"
    return ref.read_text().strip()


def main() -> None:
    if FREEZE.exists():
        raise SystemExit("FREEZE.json already exists; a new freeze needs a new test set")
    splits = load_splits()
    labels = labels_of(splits["train"])
    train_text = [row["description_text"] for row in splits["train"]]
    train_labels = [row["category"] for row in splits["train"]]
    pages = load_transfer("validation")
    texts = [page_text(page, "full") for page in pages]
    states = [methods.page_state(page) for page in pages]
    expected = np.array([page["category"] for page in pages])

    frozen = {}
    for name, config in CANDIDATES.items():
        scores, _, _ = build(config, train_text, train_labels, labels)(texts, states)
        top = scores.max(axis=1)
        correct = np.array(labels)[scores.argmax(axis=1)] == expected
        threshold = lowest_threshold(top, correct, TARGET_ACCURACY)
        kept = top >= threshold if threshold is not None else np.zeros(len(top), bool)
        frozen[name] = config | {
            "abstain_below_top_score": threshold,
            "validation_pages": {"rows": len(top), "coverage": float(kept.mean()),
                                 "accuracy_when_answering": float(correct[kept].mean()) if kept.any() else None},
        }
        print(name, frozen[name])

    record = {
        "frozen_at": datetime.now(timezone.utc).isoformat(),
        "file_sha256": {file: hashlib.sha256((HERE / file).read_bytes()).hexdigest() for file in FROZEN_FILES},
        "embedder_revisions": {BGE: embedder_revision(BGE)},
        "threshold_rule": f"lowest top score with accuracy >= {TARGET_ACCURACY} on validation homepages (full view)",
        "test_inputs": ["test descriptions", "test-split homepages, full view (Jev: structured page state)"],
        "candidates": frozen,
        "note": "Configurations chosen on validation descriptions and validation homepages only. The v1 test split "
                "was scored once by the fixed TF-IDF baseline, so this is its second use.",
    }
    FREEZE.write_text(json.dumps(record, indent=1) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
