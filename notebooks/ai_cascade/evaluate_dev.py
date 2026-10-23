"""Compare the keyword rule and the cascade on the website_feasibility dev pages under ADR 0001."""
import json
import sys
from collections import Counter
from pathlib import Path

from cascade import KEYWORD, all_text, determine

ROOT = Path(__file__).resolve().parents[2]
DEV = ROOT / "notebooks/website_feasibility"
OUT = Path(__file__).resolve().parent / "dev_results.json"


def macro_f1(pairs):
    """Macro-F1 over ai/non_ai for pages whose gold determination is resolved; abstentions count as errors."""
    scores = []
    for cls in ("ai", "non_ai"):
        tp = sum(g == cls and p == cls for g, p in pairs)
        fp = sum(g != cls and p == cls for g, p in pairs)
        fn = sum(g == cls and p != cls for g, p in pairs)
        prec, rec = (tp / (tp + fp) if tp + fp else 0), (tp / (tp + fn) if tp + fn else 0)
        scores.append(2 * prec * rec / (prec + rec) if prec + rec else 0)
    return sum(scores) / 2


def summarize(name, gold, predicted):
    resolved = [(gold[s], predicted[s]) for s in gold if gold[s] != "unresolved"]
    unresolved = [predicted[s] for s in gold if gold[s] == "unresolved"]
    return {"method": name, "resolved_pages": len(resolved), "resolved_macro_f1": macro_f1(resolved),
            "resolved_accuracy": sum(g == p for g, p in resolved) / len(resolved),
            "false_alarms": sum(g == "non_ai" and p == "ai" for g, p in resolved),
            "missed_ai": sum(g == "ai" and p != "ai" for g, p in resolved),
            "resolved_abstained": sum(p == "unresolved" for _, p in resolved),
            "gold_unresolved_pages": len(unresolved), "gold_unresolved_predictions": dict(Counter(unresolved)),
            "confusion": {f"{g}->{p}": n for (g, p), n in sorted(Counter((gold[s], predicted[s]) for s in gold).items())}}


def main():
    captures = [c for c in map(json.loads, (DEV / "captures/results.jsonl").open(encoding="utf-8")) if c["outcome"] == "extracted"]
    rows = {r["sample_id"]: r for r in json.loads((DEV / "results.json").read_text())["rows"]}
    gold = {c["sample_id"]: rows[c["sample_id"]]["determination"] for c in captures}
    keyword = {c["sample_id"]: "ai" if KEYWORD.search(all_text(c)) else "non_ai" for c in captures}
    cascade = determine(captures)
    predicted = {s: v["determination"] for s, v in cascade.items()}
    report = {"keyword_rule": summarize("keyword_rule", gold, keyword), "cascade": summarize("cascade", gold, predicted),
              "stages": dict(Counter(v["stage"] for v in cascade.values())),
              "cascade_errors": [{"sample_id": s, "source": rows[s]["source"], "title": rows[s]["title"], "gold": gold[s],
                                  **cascade[s]} for s in gold if gold[s] != predicted[s]]}
    OUT.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    for key in ("keyword_rule", "cascade"):
        r = report[key]
        print(f"{key:<13} resolved macroF1={r['resolved_macro_f1']:.3f} acc={r['resolved_accuracy']:.3f} "
              f"false_alarms={r['false_alarms']} missed_ai={r['missed_ai']} abstained={r['resolved_abstained']} "
              f"| gold-unresolved -> {r['gold_unresolved_predictions']}")
    print("stages:", report["stages"])
    for e in report["cascade_errors"]:
        print(f"  [{e['source'][:5]}] gold={e['gold']:<10} pred={e['determination']:<10} {e['stage']:<17} "
              f"{(e['title'] or '')[:50]!r} {e.get('reason', '')}")


if __name__ == "__main__":
    sys.exit(main())
