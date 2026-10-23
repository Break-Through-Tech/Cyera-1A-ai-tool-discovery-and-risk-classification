"""Develop cascade v2 on every already-scored page: the website_feasibility dev sample plus the spent v1 test sample."""
import json
import sys
from collections import Counter
from pathlib import Path

import cascade
import cascade_v2
from evaluate_dev import summarize
from evaluate_test import DETERMINATION, load_pass

HERE = Path(__file__).resolve().parent
DEV = HERE.parents[1] / "notebooks/website_feasibility"
OUT = HERE / "v2_dev_results.json"
# Run sequentially: each run rewrites the shared judge cache.


def development_pages():
    """Return (captures, gold) for the 440 pages scored before v2 existed."""
    dev = [c for c in map(json.loads, (DEV / "captures/results.jsonl").open(encoding="utf-8")) if c["outcome"] == "extracted"]
    rows = {r["sample_id"]: r for r in json.loads((DEV / "results.json").read_text())["rows"]}
    gold = {c["sample_id"]: rows[c["sample_id"]]["determination"] for c in dev}
    test = [c for c in map(json.loads, (HERE / "pool/captures.jsonl").open(encoding="utf-8"))
            if c["split"] == "test" and c["outcome"] == "extracted"]
    a, b = load_pass("A"), load_pass("B")
    for s in a:
        da, db = DETERMINATION[a[s]["label"]], DETERMINATION[b[s]["label"]]
        gold[s] = da if da == db else "unresolved"
    return dev + test, gold


def main(gate_only=False, effort=None):
    if effort:
        cascade_v2.JUDGE_EFFORT = effort
    captures, gold = development_pages()
    by_id = {c["sample_id"]: c for c in captures}
    keyword = {c["sample_id"]: "ai" if cascade.KEYWORD.search(cascade.all_text(c)) else "non_ai" for c in captures}
    newly_gated = [c for c in captures if not cascade.KEYWORD.search(cascade.all_text(c)) and cascade_v2.gate(cascade_v2.all_text(c))]
    print(f"pages={len(captures)} gold={dict(Counter(gold.values()))}")
    print(f"capability gate adds {len(newly_gated)} pages to the judge; gold: {dict(Counter(gold[c['sample_id']] for c in newly_gated))}")
    if gate_only:
        for c in newly_gated:
            hits = sorted({m.group(0).lower() for m in cascade_v2.CAPABILITY.finditer(cascade_v2.all_text(c))})
            print(f"  gold={gold[c['sample_id']]:<10} {(c.get('title') or '')[:50]!r} {hits[:5]}")
        return
    v1 = {s: v["determination"] for s, v in cascade.determine(captures).items()}
    v2_full = cascade_v2.determine(captures)
    v2 = {s: v["determination"] for s, v in v2_full.items()}
    report = {"pages": len(captures), "gold_determinations": dict(Counter(gold.values())),
              "keyword_rule": summarize("keyword_rule", gold, keyword), "cascade_v1": summarize("cascade_v1", gold, v1),
              "cascade_v2": summarize("cascade_v2", gold, v2), "stages_v2": dict(Counter(v["stage"] for v in v2_full.values())),
              "v2_errors": [{"sample_id": s, "source": by_id[s]["source"], "title": by_id[s].get("title"), "gold": gold[s],
                             "v1": v1[s], **v2_full[s]} for s in sorted(gold) if gold[s] != v2[s]]}
    OUT.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    for key in ("keyword_rule", "cascade_v1", "cascade_v2"):
        r = report[key]
        print(f"{key:<13} macroF1={r['resolved_macro_f1']:.3f} acc={r['resolved_accuracy']:.3f} false_alarms={r['false_alarms']} "
              f"missed_ai={r['missed_ai']} abstained={r['resolved_abstained']} | gold-unresolved -> {r['gold_unresolved_predictions']}")
    for e in report["v2_errors"]:
        print(f"  [{e['source'][:5]}] gold={e['gold']:<10} v1={e['v1']:<10} v2={e['determination']:<10} {e['stage']:<17} "
              f"{(e['title'] or '')[:45]!r} {e.get('reason', '')}")


if __name__ == "__main__":
    effort = next((a.split("=", 1)[1] for a in sys.argv if a.startswith("--effort=")), None)
    sys.exit(main(gate_only="--gate-only" in sys.argv, effort=effort))
