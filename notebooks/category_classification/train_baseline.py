"""Evaluate a fixed description-only 14-category baseline on frozen splits."""

from __future__ import annotations

import csv
import json
from collections import Counter
from pathlib import Path

import sklearn
from sklearn.dummy import DummyClassifier
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, classification_report, confusion_matrix, f1_score
from sklearn.pipeline import make_pipeline


ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data/category_classification/v1"
MODEL_ID = "aitoolbuzz-category-tfidf-logreg-v1"


def load_split(name: str, manifest: dict) -> list[dict[str, str]]:
    path = DATA / f"{name}.csv"
    with path.open(encoding="utf-8", newline="") as stream:
        reader = csv.DictReader(stream)
        if reader.fieldnames != ["tool_id", "group_id", "description_text", "category"]:
            raise ValueError(f"Unexpected {name} schema")
        rows = list(reader)
    if len(rows) != manifest["partitions"][name]["rows"]:
        raise ValueError(f"Unexpected {name} row count")
    return rows


def metrics(expected: list[str], predicted: list[str], labels: list[str]) -> dict:
    per_class = classification_report(expected, predicted, labels=labels,
                                      output_dict=True, zero_division=0)
    return {
        "accuracy": accuracy_score(expected, predicted),
        "macro_f1": f1_score(expected, predicted, labels=labels, average="macro", zero_division=0),
        "weighted_f1": f1_score(expected, predicted, labels=labels, average="weighted", zero_division=0),
        "per_class": {label: per_class[label] for label in labels},
        "confusion_matrix": confusion_matrix(expected, predicted, labels=labels).tolist(),
    }


def main() -> None:
    manifest = json.loads((DATA / "manifest.json").read_text(encoding="utf-8"))
    if manifest["input_feature_allowlist"] != ["description_text"] or manifest["target"] != "category":
        raise ValueError("Unexpected feature or target policy")
    train = load_split("train", manifest)
    validation = load_split("validation", manifest)
    test = load_split("test", manifest)
    by_split = {"train": train, "validation": validation, "test": test}
    ids = [row["tool_id"] for rows in by_split.values() for row in rows]
    if len(ids) != len(set(ids)):
        raise ValueError("Tool ID appears more than once")
    groups = {name: {row["group_id"] for row in rows} for name, rows in by_split.items()}
    if any(groups[left] & groups[right] for left, right in
           (("train", "validation"), ("train", "test"), ("validation", "test"))):
        raise ValueError("Identity group crosses partitions")
    labels = sorted(Counter(row["category"] for row in train))
    if len(labels) != 14:
        raise ValueError("Expected all 14 training categories")
    train_text = [row["description_text"] for row in train]
    train_labels = [row["category"] for row in train]

    # Settings are fixed before test evaluation. Fitting sees train descriptions only.
    model = make_pipeline(
        TfidfVectorizer(ngram_range=(1, 2), min_df=2),
        LogisticRegression(max_iter=1000, random_state=20261014),
    )
    model.fit(train_text, train_labels)
    majority = DummyClassifier(strategy="most_frequent")
    majority.fit([[0]] * len(train), train_labels)

    results = {}
    for name in ("validation", "test"):
        rows = by_split[name]
        text = [row["description_text"] for row in rows]
        expected = [row["category"] for row in rows]
        results[name] = {
            "majority_baseline": metrics(expected, majority.predict([[0]] * len(rows)).tolist(), labels),
            "tfidf_logistic_regression": metrics(expected, model.predict(text).tolist(), labels),
        }

    report = {
        "model_id": MODEL_ID,
        "scikit_learn_version": sklearn.__version__,
        "task": "14-category classification",
        "dataset_id": manifest["dataset_id"],
        "features": ["description_text"],
        "target": "category",
        "labels": labels,
        "model_settings": {"vectorizer": "word TF-IDF 1-2 grams, min_df=2",
                           "classifier": "LogisticRegression max_iter=1000, seed=20261014"},
        "fit_partition": "train",
        "model_selection": "fixed first-pass settings; validation reported, no tuning or refit before test",
        "test_evaluated": True,
        "results": results,
        "limits": [
            "Catalog descriptions only; no evaluation on website-enriched text.",
            "Name, Website, Primary Task, Keywords, and technologies are not model features.",
            "Suspected related tools are grouped by normalized name, hostname, exact description, and near-description similarity at least 0.92; other near-duplicates may remain.",
            "Uncalibrated model scores are not operational confidence estimates.",
        ],
    }
    (DATA / "baseline_evaluation.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    for name in ("validation", "test"):
        result = results[name]
        print(f"{name}: majority macro F1 {result['majority_baseline']['macro_f1']:.4f}; "
              f"TF-IDF macro F1 {result['tfidf_logistic_regression']['macro_f1']:.4f}; "
              f"accuracy {result['tfidf_logistic_regression']['accuracy']:.4f}")


if __name__ == "__main__":
    main()
