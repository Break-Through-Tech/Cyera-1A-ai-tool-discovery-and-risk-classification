"""Distill the Luna context judge into small stage-3 students and compare cascades on the dev pages."""
import json
from collections import Counter
from pathlib import Path

import numpy as np
from sentence_transformers import SentenceTransformer
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import StratifiedKFold, cross_val_predict
from sklearn.pipeline import make_pipeline

from cascade import KEYWORD, all_text, determine, judge, mention_snippets, page_id
from evaluate_dev import DEV, summarize

HERE = Path(__file__).resolve().parent
POOL = HERE / "pool/captures.jsonl"
OUT = HERE / "student_results.json"
EMBEDDERS = ("sentence-transformers/all-MiniLM-L6-v2", "BAAI/bge-small-en-v1.5")
C_GRID = (0.1, 1.0, 10.0)
WEIGHTS = (None, "balanced")
SEED = 20261023


def student_text(capture, mentions_only=False):
    snippets = mention_snippets(capture)
    if mentions_only:
        snippets = [s for s in snippets if KEYWORD.search(s["text"])] or snippets
    return "\n".join(f"{s['location']}: {s['text']}" for s in snippets)


def extracted(path, split=None):
    rows = [json.loads(line) for line in path.open(encoding="utf-8")]
    return [r for r in rows if r["outcome"] == "extracted" and (split is None or r.get("split") == split)]


def select_c(make, X, y):
    """Pick (C, class weight) by 5-fold macro-F1 on the teacher labels; ties keep the earlier setting."""
    folds = StratifiedKFold(5, shuffle=True, random_state=SEED)
    best = None
    for C in C_GRID:
        for weight in WEIGHTS:
            predicted = cross_val_predict(make(C, weight), X, y, cv=folds)
            f1 = np.mean([2 * ((predicted == c) & (y == c)).sum() / ((predicted == c).sum() + (y == c).sum())
                          for c in np.unique(y)])
            if best is None or f1 > best[2]:
                best = (C, weight, f1)
    return best


def judge_from(model, featurize):
    def judge_fn(captures):
        predicted = model.predict(featurize(captures))
        return {page_id(c): {"determination": p, "ai_type": None, "reason": "student"} for c, p in zip(captures, predicted)}
    return judge_fn


def main():
    train = [c for c in extracted(POOL, "train") if KEYWORD.search(all_text(c))]
    teacher = judge(train)
    y = np.array([teacher[page_id(c)]["determination"] for c in train])
    print(f"teacher-labeled training pages: {len(train)} {dict(Counter(y))}")

    dev = extracted(DEV / "captures/results.jsonl")
    rows = {r["sample_id"]: r for r in json.loads((DEV / "results.json").read_text())["rows"]}
    gold = {c["sample_id"]: rows[c["sample_id"]]["determination"] for c in dev}
    keyword = {c["sample_id"]: "ai" if KEYWORD.search(all_text(c)) else "non_ai" for c in dev}
    luna = {s: v["determination"] for s, v in determine(dev).items()}
    dev_gated = [c for c in dev if KEYWORD.search(all_text(c))]
    luna_gated = {page_id(c): luna[c["sample_id"]] for c in dev_gated}

    report = {"teacher_label_counts": dict(Counter(y)), "dev": {
        "keyword_rule": summarize("keyword_rule", gold, keyword),
        "cascade_luna": summarize("cascade_luna", gold, luna)}, "students": {}}

    def lr(C, weight):
        return LogisticRegression(C=C, max_iter=2000, class_weight=weight)

    candidates = {}
    for mentions_only in (False, True):
        view = "mentions" if mentions_only else "context"
        texts = (lambda m: lambda cs: [student_text(c, m) for c in cs])(mentions_only)
        candidates[f"tfidf_lr[{view}]"] = (
            lambda C, w: make_pipeline(TfidfVectorizer(ngram_range=(1, 2), min_df=2), lr(C, w)), texts)
        for name in EMBEDDERS:
            encoder = SentenceTransformer(name, device="cpu")
            featurize = (lambda enc, t: lambda cs: enc.encode(t(cs), normalize_embeddings=True, batch_size=32))(encoder, texts)
            candidates[f"embed_lr[{name.split('/')[-1]},{view}]"] = (lr, featurize)

    for name, (make, featurize) in candidates.items():
        X = featurize(train)
        C, weight, cv_f1 = select_c(make, X, y)
        model = make(C, weight).fit(X, y)
        cascade = {s: v["determination"] for s, v in determine(dev, judge_from(model, featurize)).items()}
        agreement = np.mean([cascade[c["sample_id"]] == luna_gated[page_id(c)] for c in dev_gated])
        report["students"][name] = {"C": C, "class_weight": weight or "ordinary", "train_cv_macro_f1_vs_teacher": cv_f1,
                                    "dev_stage3_agreement_with_luna": agreement,
                                    "dev": summarize(f"cascade_{name}", gold, cascade)}

    OUT.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"{'method':<44}{'macroF1':>8}{'acc':>7}{'FA':>4}{'miss':>5}{'abst':>5}  gold-unresolved -> predictions")
    rows_out = [(k, v) for k, v in report["dev"].items()] + [(k, v["dev"]) for k, v in report["students"].items()]
    for name, r in rows_out:
        print(f"{name:<44}{r['resolved_macro_f1']:>8.3f}{r['resolved_accuracy']:>7.3f}{r['false_alarms']:>4}"
              f"{r['missed_ai']:>5}{r['resolved_abstained']:>5}  {r['gold_unresolved_predictions']}")
    for name, s in report["students"].items():
        print(f"  {name}: C={s['C']} weight={s['class_weight']} cv_vs_teacher={s['train_cv_macro_f1_vs_teacher']:.3f} "
              f"dev_agreement_with_luna={s['dev_stage3_agreement_with_luna']:.3f}")


if __name__ == "__main__":
    main()
