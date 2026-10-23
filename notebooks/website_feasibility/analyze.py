"""Score the v4 keyword rule against blind website-text labels from two independent passes."""
import json
import re
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
KEYWORD = re.compile(
    r"\b(?:AI|AIOps|artificial[\s-]+intelligence|ML|machine[\s-]+learning|"
    r"deep[\s-]+learning|neural[\s-]+networks?|LLMs?|"
    r"large[\s-]+language[\s-]+models?|NLP|"
    r"natural[\s-]+language[\s-]+(?:processing|understanding)|"
    r"generative[\s-]+AI)\b", re.IGNORECASE)
DEFINITIONS = {"any_product_ai_claim": {"ai_core", "ai_feature", "ai_mention_only"},
               "real_ai_capability": {"ai_core", "ai_feature"}}
# ADR 0001 mapping; see labeling/RUBRIC.md.
DETERMINATION = {"ai_core": "ai", "ai_feature": "ai", "ai_mention_only": "unresolved",
                 "no_ai": "non_ai", "insufficient": "unresolved"}
SOURCES = ("aitoolbuzz", "companyenrich")


def metadata_text(capture):
    meta = capture.get("metadata", {})
    return " ".join(filter(None, [capture.get("title"), meta.get("description"), meta.get("og:description"),
                                  " ".join(capture.get("headings", []))]))


def load_labels(pass_name):
    labels = {}
    for path in sorted((HERE / "labeling").glob(f"labels_{pass_name}_*.json")):
        for item in json.loads(path.read_text()):
            labels[item["sample_id"]] = item
    return labels


def score(rows, positive, field):
    tp = sum(r[field] and r["label"] in positive for r in rows)
    fp = sum(r[field] and r["label"] not in positive for r in rows)
    fn = sum(not r[field] and r["label"] in positive for r in rows)
    tn = len(rows) - tp - fp - fn

    def f1(p_num, p_den, r_den):
        p, r = (p_num / p_den if p_den else 0), (p_num / r_den if r_den else 0)
        return (2 * p * r / (p + r) if p + r else 0), p, r

    f_ai, precision, recall = f1(tp, tp + fp, tp + fn)
    f_non, _, _ = f1(tn, tn + fn, tn + fp)
    return {"pages": len(rows), "ai_pages": tp + fn, "accuracy": (tp + tn) / len(rows), "macro_f1": (f_ai + f_non) / 2,
            "ai_precision": precision, "ai_recall": recall, "false_alarms": fp, "misses": fn}


def main():
    captures = [json.loads(line) for line in (HERE / "captures/results.jsonl").open(encoding="utf-8")]
    a, b = load_labels("A"), load_labels("B")
    rows, disputes = [], []
    for c in captures:
        if c["outcome"] != "extracted":
            continue
        la, lb = a[c["sample_id"]], b[c["sample_id"]]
        if la["label"] != lb["label"]:
            disputes.append({"sample_id": c["sample_id"], "source": c["source"], "title": c.get("title"),
                             "labels": [la["label"], lb["label"]], "evidence": [la["evidence"], lb["evidence"]]})
        da, db = DETERMINATION[la["label"]], DETERMINATION[lb["label"]]
        rows.append({"sample_id": c["sample_id"], "source": c["source"], "title": c.get("title"),
                     "label": la["label"] if la["label"] == lb["label"] else "disputed",
                     "determination": da if da == db else "unresolved",
                     "keyword_metadata": bool(KEYWORD.search(metadata_text(c))),
                     "keyword_full_page": bool(KEYWORD.search(metadata_text(c) + " " + (c.get("main_text") or ""))),
                     "catalog_says_ai": c["source"] == "aitoolbuzz"})
    scored = [r for r in rows if r["label"] not in {"insufficient", "disputed"}]
    resolved = [{**r, "label": r["determination"]} for r in rows if r["determination"] != "unresolved"]
    adr_score = {"keyword_metadata_only": score(resolved, {"ai"}, "keyword_metadata"),
                 "keyword_full_page": score(resolved, {"ai"}, "keyword_full_page"),
                 "catalog_source_as_label": score(resolved, {"ai"}, "catalog_says_ai"),
                 **{f"keyword_full_page_{s}": score([r for r in resolved if r["source"] == s], {"ai"}, "keyword_full_page")
                    for s in SOURCES}}
    report = {
        "fetch_outcomes": {s: dict(Counter(c["outcome"] for c in captures if c["source"] == s)) for s in SOURCES},
        "pass_agreement": {"pages": len(rows), "agreed": len(rows) - len(disputes)},
        "disputes": disputes,
        "labels_by_source": {s: dict(Counter(r["label"] for r in rows if r["source"] == s)) for s in SOURCES},
        "determinations_by_source": {s: dict(Counter(r["determination"] for r in rows if r["source"] == s)) for s in SOURCES},
        "adr_0001_scores": adr_score,
        "scores": {name: {"keyword_metadata_only": score(scored, pos, "keyword_metadata"),
                          "keyword_full_page": score(scored, pos, "keyword_full_page"),
                          "catalog_source_as_label": score(scored, pos, "catalog_says_ai"),
                          **{f"keyword_full_page_{s}": score([r for r in scored if r["source"] == s], pos, "keyword_full_page")
                             for s in SOURCES}}
                   for name, pos in DEFINITIONS.items()},
        "keyword_full_page_hits_by_label": {l: [sum(r["keyword_full_page"] for r in scored if r["label"] == l),
                                                sum(r["label"] == l for r in scored)]
                                            for l in ("ai_core", "ai_feature", "ai_mention_only", "no_ai")},
        "rows": rows,
    }
    (HERE / "results.json").write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print("determinations:", report["determinations_by_source"])
    for name, table in [("adr_0001", adr_score), *report["scores"].items()]:
        print(name)
        for method, s in table.items():
            print(f"  {method:<36} macroF1={s['macro_f1']:.3f} prec={s['ai_precision']:.2f} "
                  f"rec={s['ai_recall']:.2f} false_alarms={s['false_alarms']} misses={s['misses']}")


if __name__ == "__main__":
    main()
