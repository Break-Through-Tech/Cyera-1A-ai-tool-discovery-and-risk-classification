"""Shared scoring for category methods. Every method yields a rows x labels score matrix."""

from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path

import numpy as np

from train_baseline import DATA, metrics


ROOT = Path(__file__).resolve().parents[2]
TRANSFER = ROOT / "data/category_classification/transfer_v1"
COVERAGES = (0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0)
VIEWS = ("meta", "body", "full")


def load_split(name: str, manifest: dict) -> list[dict[str, str]]:
    """The manifest hashes CRLF files written on Windows; a Linux checkout has LF line endings."""
    path = DATA / f"{name}.csv"
    crlf = path.read_bytes().replace(b"\r\n", b"\n").replace(b"\n", b"\r\n")
    if hashlib.sha256(crlf).hexdigest() != manifest["partitions"][name]["sha256"]:
        raise ValueError(f"Frozen {name} partition changed")
    with path.open(encoding="utf-8", newline="") as stream:
        rows = list(csv.DictReader(stream))
    if len(rows) != manifest["partitions"][name]["rows"]:
        raise ValueError(f"Unexpected {name} row count")
    return rows


def load_splits() -> dict[str, list[dict[str, str]]]:
    manifest = json.loads((DATA / "manifest.json").read_text(encoding="utf-8"))
    return {name: load_split(name, manifest) for name in ("train", "validation", "test")}


def labels_of(train: list[dict[str, str]]) -> list[str]:
    labels = sorted({row["category"] for row in train})
    if len(labels) != 14:
        raise ValueError("Expected all 14 training categories")
    return labels


def load_transfer(split: str) -> list[dict]:
    """Homepages of catalog Tools in one frozen split; the train split's pages are only for untrained methods."""
    path = TRANSFER / "pages.jsonl"
    summary = json.loads((TRANSFER / "summary.json").read_text(encoding="utf-8"))
    if hashlib.sha256(path.read_bytes()).hexdigest() != summary["pages_sha256"]:
        raise ValueError("Transfer pages changed since the summary was written")
    rows = [json.loads(line) for line in path.open(encoding="utf-8")]
    return [row for row in rows if row["catalog_split"] == split]


def page_text(page: dict, view: str) -> str:
    """``full`` joins the fields the way the backend's homepage evidence text does."""
    if view == "meta":
        parts = (page["title"], page["meta_description"])
    elif view == "body":
        parts = (page["body"],)
    elif view == "full":
        parts = (page["title"], page["meta_description"], page["headings"], page["body"])
    else:
        raise ValueError(f"Unknown view {view}")
    return " ".join(part for part in parts if part)


def coverage_curve(expected: list[str], predicted: list[str], confidence: np.ndarray,
                   labels: list[str]) -> list[dict]:
    """Keep the most confident fraction of rows and abstain on the rest."""
    order = np.argsort(-confidence, kind="stable")
    curve = []
    for coverage in COVERAGES:
        kept = order[: max(1, round(coverage * len(order)))]
        result = metrics([expected[i] for i in kept], [predicted[i] for i in kept], labels)
        curve.append({
            "coverage": coverage,
            "threshold": float(confidence[kept[-1]]),
            "accuracy": result["accuracy"],
            "macro_f1": result["macro_f1"],
        })
    return curve


def score(expected: list[str], scores: np.ndarray, labels: list[str], *,
          cost_usd: float = 0.0, seconds: float = 0.0) -> dict:
    if scores.shape != (len(expected), len(labels)):
        raise ValueError("Score matrix does not match rows x labels")
    ranked = np.sort(scores, axis=1)
    top, margin = ranked[:, -1], ranked[:, -1] - ranked[:, -2]
    predicted = [labels[i] for i in scores.argmax(axis=1)]
    return {
        "rows": len(expected),
        **metrics(expected, predicted, labels),
        "coverage_by_top_score": coverage_curve(expected, predicted, top, labels),
        "coverage_by_margin": coverage_curve(expected, predicted, margin, labels),
        "cost_usd": cost_usd,
        "seconds_per_row": seconds / max(1, len(expected)),
    }


def summary_line(name: str, result: dict) -> str:
    at_half = next(point for point in result["coverage_by_top_score"] if point["coverage"] == 0.5)
    return (f"{name:<48} n={result['rows']:<5} acc {result['accuracy']:.3f}  "
            f"macroF1 {result['macro_f1']:.3f}  wF1 {result['weighted_f1']:.3f}  "
            f"acc@50% {at_half['accuracy']:.3f}")
