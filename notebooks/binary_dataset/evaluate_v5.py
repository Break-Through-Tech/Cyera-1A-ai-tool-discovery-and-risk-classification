"""Score the frozen v4 TF-IDF + logistic regression model and a v5-reselected model on binary-ai-v5."""
import csv
import json
import re
import warnings
from pathlib import Path

import numpy as np
from sklearn.base import clone
from sklearn.exceptions import ConvergenceWarning
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, average_precision_score, confusion_matrix, f1_score, precision_recall_fscore_support
from sklearn.pipeline import Pipeline

ROOT = Path(__file__).resolve().parents[2]
V4 = ROOT / "data/binary_ai_dataset/v4"
V5 = ROOT / "data/binary_ai_dataset/v5"
OUT = Path(__file__).resolve().parent / "v5_evaluation.json"
LABELS = ["non_ai", "ai"]
V4_SEED = 20261014
FROZEN_V4 = {"C": 10.0, "class_weight": "balanced", "ai_cutoff": 0.5}
V4_TEST_MACRO_F1 = 0.9593
EXPERIMENT_C = (0.1, 1.0, 10.0)
EXPERIMENT_WEIGHTS = (None, "balanced")
KEYWORD = re.compile(
    r"\b(?:AI|AIOps|artificial[\s-]+intelligence|ML|machine[\s-]+learning|"
    r"deep[\s-]+learning|neural[\s-]+networks?|LLMs?|"
    r"large[\s-]+language[\s-]+models?|NLP|"
    r"natural[\s-]+language[\s-]+(?:processing|understanding)|"
    r"generative[\s-]+AI)\b", re.IGNORECASE)


def load(directory, partition):
    with (directory / f"{partition}.csv").open(encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    meta = {m["example_id"]: m for m in json.loads((directory / f"{partition}.metadata.json").read_bytes())}
    for row in rows:
        m = meta[row["example_id"]]
        row["enterprise"] = any(x["source"] == "enterprise" for x in m["members"])
        row["new_in_v5"] = m.get("new_in_v5", False)
    return rows


def pipeline(C, class_weight):
    return Pipeline([("tfidf", TfidfVectorizer(ngram_range=(1, 2), min_df=2)),
                     ("classifier", LogisticRegression(solver="liblinear", max_iter=1000, random_state=V4_SEED,
                                                       C=C, class_weight=class_weight))])


def fit(rows, C, class_weight):
    model = pipeline(C, class_weight)
    with warnings.catch_warnings():
        warnings.simplefilter("error", ConvergenceWarning)
        model.fit([r["description_text"] for r in rows], [r["label"] for r in rows])
    return model


def ai_scores(model, rows):
    column = model.named_steps["classifier"].classes_.tolist().index("ai")
    return model.predict_proba([r["description_text"] for r in rows])[:, column]


def metrics(truth, predictions, scores=None):
    if not truth:
        return None
    matrix = confusion_matrix(truth, predictions, labels=LABELS)
    p, r, f, s = precision_recall_fscore_support(truth, predictions, labels=LABELS, zero_division=0)
    result = {"examples": len(truth), "accuracy": accuracy_score(truth, predictions),
              "macro_f1": f1_score(truth, predictions, labels=LABELS, average="macro", zero_division=0),
              "per_class": {label: {"support": int(s[i]), "precision": p[i], "recall": r[i], "f1": f[i]}
                            for i, label in enumerate(LABELS)},
              "false_positives": int(matrix[0, 1]), "missed_ai": int(matrix[1, 0]), "confusion": matrix.tolist()}
    if scores is not None and len(set(truth)) == 2:
        y = [t == "ai" for t in truth]
        result["ai_average_precision"] = average_precision_score(y, scores)
        result["non_ai_average_precision"] = average_precision_score([not v for v in y], [1 - x for x in scores])
    return result


SLICES = {"all": lambda r: True, "v4_carried": lambda r: not r["new_in_v5"], "new_in_v5": lambda r: r["new_in_v5"],
          "enterprise": lambda r: r["enterprise"], "new_in_v5_enterprise": lambda r: r["new_in_v5"] and r["enterprise"]}


def sliced(rows, predictions, scores=None):
    out = {}
    for name, keep in SLICES.items():
        idx = [i for i, r in enumerate(rows) if keep(r)]
        out[name] = metrics([rows[i]["label"] for i in idx], [predictions[i] for i in idx],
                            None if scores is None else [scores[i] for i in idx])
    return out


def score_all(model, rows, cutoff=0.5):
    scores = ai_scores(model, rows)
    predictions = np.where(scores >= cutoff, "ai", "non_ai").tolist()
    return predictions, scores.tolist()


def baselines(rows):
    return {"always_ai": sliced(rows, ["ai"] * len(rows)),
            "keyword": sliced(rows, ["ai" if KEYWORD.search(r["description_text"]) else "non_ai" for r in rows])}


def errors(rows, predictions, scores, limit=40):
    found = [{"example_id": r["example_id"], "label": r["label"], "ai_score": round(s, 4), "new_in_v5": r["new_in_v5"],
              "description_text": r["description_text"][:240]}
             for r, p, s in zip(rows, predictions, scores) if p != r["label"] and r["enterprise"]]
    return sorted(found, key=lambda e: (not e["new_in_v5"], e["example_id"]))[:limit]


def main():
    v4_train, v4_test = load(V4, "train"), load(V4, "test")
    v5_train, v5_validation, v5_test = load(V5, "train"), load(V5, "validation"), load(V5, "test")

    frozen = fit(v4_train, FROZEN_V4["C"], FROZEN_V4["class_weight"])
    v4_predictions, _ = score_all(frozen, v4_test, FROZEN_V4["ai_cutoff"])
    reproduced = metrics([r["label"] for r in v4_test], v4_predictions)["macro_f1"]
    if round(reproduced, 4) != V4_TEST_MACRO_F1:
        raise ValueError(f"frozen v4 model did not reproduce v4 test macro-F1: {reproduced:.4f}")
    frozen_predictions, frozen_scores = score_all(frozen, v5_test, FROZEN_V4["ai_cutoff"])

    experiments = []
    for C in EXPERIMENT_C:
        for weight in EXPERIMENT_WEIGHTS:
            model = fit(v5_train, C, weight)
            predictions, scores = score_all(model, v5_validation)
            experiments.append({"C": C, "class_weight": weight, "model": model,
                                "validation": sliced(v5_validation, predictions, scores)})
    selected = max(experiments, key=lambda e: e["validation"]["all"]["macro_f1"])
    v5_predictions, v5_scores = score_all(selected["model"], v5_test)

    report = {
        "dataset": "binary-ai-v5", "v5_manifest_sha256": __import__("hashlib").sha256((V5 / "manifest.json").read_bytes()).hexdigest(),
        "reproduced_v4_test_macro_f1": reproduced,
        "frozen_v4_model": {"settings": FROZEN_V4, "trained_on": "v4 train", "v5_test": sliced(v5_test, frozen_predictions, frozen_scores),
                            "enterprise_test_errors": errors(v5_test, frozen_predictions, frozen_scores)},
        "v5_reselected_model": {
            "grid": [{"C": e["C"], "class_weight": e["class_weight"] or "ordinary",
                      "validation_macro_f1": e["validation"]["all"]["macro_f1"],
                      "validation_enterprise_macro_f1": e["validation"]["enterprise"]["macro_f1"]} for e in experiments],
            "selected": {"C": selected["C"], "class_weight": selected["class_weight"] or "ordinary", "ai_cutoff": 0.5,
                         "selection": "pooled v5 validation macro-F1; ties keep the first setting"},
            "trained_on": "v5 train", "v5_test": sliced(v5_test, v5_predictions, v5_scores),
            "enterprise_test_errors": errors(v5_test, v5_predictions, v5_scores)},
        "baselines_v5_test": baselines(v5_test),
        "notes": ["v4_carried test examples were scored once in the v4 experiment; new_in_v5 examples are previously unscored.",
                  "Probability scores are uncalibrated; no threshold was tuned.",
                  "AIToolBuzz supplies AI-only rows, so source/style confounding remains."],
    }
    OUT.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

    print(f"Reproduced frozen v4 test macro-F1: {reproduced:.4f}")
    print("v5 grid (validation macro-F1):", [(g["C"], g["class_weight"], round(g["validation_macro_f1"], 4))
                                             for g in report["v5_reselected_model"]["grid"]])
    print("Selected:", report["v5_reselected_model"]["selected"])
    rows = [("frozen v4", report["frozen_v4_model"]["v5_test"]), ("v5 reselected", report["v5_reselected_model"]["v5_test"]),
            ("keyword", report["baselines_v5_test"]["keyword"])]
    print(f"{'model':<14}{'slice':<22}{'n':>6}{'macroF1':>9}{'FP':>5}{'missAI':>7}{'AIrec':>7}{'nonAIrec':>9}")
    for name, result in rows:
        for slice_name, m in result.items():
            if m:
                print(f"{name:<14}{slice_name:<22}{m['examples']:>6}{m['macro_f1']:>9.4f}{m['false_positives']:>5}"
                      f"{m['missed_ai']:>7}{m['per_class']['ai']['recall']:>7.3f}{m['per_class']['non_ai']['recall']:>9.3f}")
    print("Wrote", OUT.relative_to(ROOT))


if __name__ == "__main__":
    main()
