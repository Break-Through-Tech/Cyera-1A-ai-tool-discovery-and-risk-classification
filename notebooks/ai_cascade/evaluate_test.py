"""Score frozen cascades and the keyword rule once on a held-out test sample.

`python evaluate_test.py` reproduces the v1 test on the pool's test split; `python evaluate_test.py test2` scores the
frozen v2 (with v1 and the keyword rule for comparison) on the pool's train-split pages.
"""
import hashlib
import importlib
import json
import sys
from collections import Counter
from pathlib import Path

from cascade import KEYWORD, all_text
from evaluate_dev import summarize

HERE = Path(__file__).resolve().parent
LABELS = HERE / "test_labeling"
DETERMINATION = {"ai_core": "ai", "ai_feature": "ai", "ai_mention_only": "unresolved",
                 "no_ai": "non_ai", "insufficient": "unresolved"}
RUNS = {"test": {"labels": LABELS, "split": "test", "cascades": ("cascade",), "out": HERE / "test_results.json"},
        "test2": {"labels": HERE / "test2_labeling", "split": "train", "cascades": ("cascade_v2", "cascade"),
                  "out": HERE / "test2_results.json"},
        "test2_jev": {"labels": HERE / "test2_labeling", "freeze": "FREEZE_jev.json", "split": "train",
                      "cascades": ("jev_cascade", "cascade_v2"), "out": HERE / "test2_jev_results.json"}}


def load_pass(name, labels_dir=LABELS):
    labels = {}
    for path in sorted(labels_dir.glob(f"labels_{name}_*.json")):
        for item in json.loads(path.read_text()):
            labels[item["sample_id"]] = item
    return labels


def main(run="test"):
    config = RUNS[run]
    freeze = json.loads((config["labels"] / config.get("freeze", "FREEZE.json")).read_text())
    for name, digest in freeze.get("file_sha256", {freeze.get("cascade_file", "cascade.py"): freeze["cascade_py_sha256"]}).items():
        if hashlib.sha256((HERE / name).read_bytes()).hexdigest() != digest:
            raise ValueError(f"{name} changed after the test freeze")
    captures = [c for c in map(json.loads, (HERE / "pool/captures.jsonl").open(encoding="utf-8"))
                if c["split"] == config["split"] and c["outcome"] == "extracted"]
    a, b = load_pass("A", config["labels"]), load_pass("B", config["labels"])
    if set(a) != set(b) or set(a) != {c["sample_id"] for c in captures}:
        raise ValueError("label passes do not cover the test pages exactly")
    gold = {s: DETERMINATION[a[s]["label"]] if DETERMINATION[a[s]["label"]] == DETERMINATION[b[s]["label"]] else "unresolved"
            for s in a}
    by_id = {c["sample_id"]: c for c in captures}

    methods = {"keyword_rule": {c["sample_id"]: {"determination": "ai" if KEYWORD.search(all_text(c)) else "non_ai",
                                                 "stage": "keyword_rule"} for c in captures}}
    for name in config["cascades"]:
        methods[name] = importlib.import_module(name).determine(captures)
    predicted = {m: {s: v["determination"] for s, v in out.items()} for m, out in methods.items()}
    primary = config["cascades"][0]

    spot_check = [{"sample_id": s, "source": by_id[s]["source"], "url": by_id[s]["url"], "title": by_id[s].get("title"),
                   "labels": [a[s]["label"], b[s]["label"]], "confidence": [a[s]["confidence"], b[s]["confidence"]],
                   "gold": gold[s], **{m: p[s] for m, p in predicted.items()},
                   "evidence": [a[s]["evidence"], b[s]["evidence"]], "cascade_reason": methods[primary][s].get("reason", "")}
                  for s in sorted(a) if a[s]["label"] != b[s]["label"] or "low" in (a[s]["confidence"], b[s]["confidence"])]
    report = {
        "freeze": freeze,
        "pages": len(captures), "pages_by_source": dict(Counter(c["source"] for c in captures)),
        "label_agreement": {"exact": sum(a[s]["label"] == b[s]["label"] for s in a),
                            "same_determination": sum(DETERMINATION[a[s]["label"]] == DETERMINATION[b[s]["label"]] for s in a)},
        "gold_determinations": dict(Counter(gold.values())),
        **{m: summarize(m, gold, p) for m, p in predicted.items()},
        "by_source": {src: {m: summarize(m, {s: g for s, g in gold.items() if by_id[s]["source"] == src}, p)
                            for m, p in predicted.items()}
                      for src in ("aitoolbuzz", "companyenrich")},
        "stages": dict(Counter(v["stage"] for v in methods[primary].values())),
        "cascade_errors": [{"sample_id": s, "source": by_id[s]["source"], "title": by_id[s].get("title"), "gold": gold[s],
                            **methods[primary][s]} for s in sorted(gold) if gold[s] != predicted[primary][s]],
        "spot_check": spot_check,
    }
    config["out"].write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    print(f"pages={report['pages']} gold={report['gold_determinations']} agreement={report['label_agreement']}")
    for scope, table in [("all", report), *report["by_source"].items()]:
        for key in predicted:
            r = table[key]
            print(f"{scope:<14}{key:<13} resolved={r['resolved_pages']:>3} macroF1={r['resolved_macro_f1']:.3f} "
                  f"acc={r['resolved_accuracy']:.3f} false_alarms={r['false_alarms']} missed_ai={r['missed_ai']} "
                  f"abstained={r['resolved_abstained']} | gold-unresolved -> {r['gold_unresolved_predictions']}")
    for key in predicted:
        print(f"confusion {key}:", report[key]["confusion"])
    print(f"spot-check pages: {len(spot_check)}")
    for e in report["cascade_errors"]:
        print(f"  [{e['source'][:5]}] gold={e['gold']:<10} pred={e['determination']:<10} {e['stage']:<17} "
              f"{(e['title'] or '')[:50]!r} {e.get('reason', '')}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "test")
