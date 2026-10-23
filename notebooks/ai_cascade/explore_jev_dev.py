"""Explore Jev decision rules on the 440 development pages; nothing here may read test2 labels."""
import json
from collections import Counter
from pathlib import Path

import cascade_v2
import jev_judge
from evaluate_dev import summarize
from evaluate_v2_dev import development_pages

HERE = Path(__file__).resolve().parent
OUT = HERE / "jev_dev_results.json"


def by_choice(f):
    return max(("ai", "non_ai", "unresolved"), key=lambda k: f[f"p_{k}"])


def by_threshold(t):
    def rule(f):
        if f["p_ai"] >= t:
            return "ai"
        return "non_ai" if f["p_non_ai"] >= t else "unresolved"
    return rule


def by_questions(t):
    def rule(f):
        if f["describes_product"] < 0.5:
            return "unresolved"
        if f["own_ai_task"] >= t:
            return "ai"
        return "unresolved" if f["vague_ai_claim"] >= t and f["ai_only_subject"] < t else "non_ai"
    return rule


def gated(rule, feats, captures):
    """Apply the v2 gate first; only gate-matching pages reach the Jev rule."""
    out = {}
    for c in captures:
        text = cascade_v2.all_text(c)
        if cascade_v2.gate(text):
            out[c["sample_id"]] = rule(feats[c["sample_id"]])
        else:
            out[c["sample_id"]] = "unresolved" if len(text.strip()) < cascade_v2.MIN_TEXT_CHARS else "non_ai"
    return out


def unsupported_ai(gold, pred):
    return sum(pred[s] == "ai" and gold[s] != "ai" for s in gold)


def main():
    captures, gold = development_pages()
    snip = {s: jev_judge.features(r) for s, r in jev_judge.ask(captures, "snippets").items()}
    full = {s: jev_judge.features(r) for s, r in jev_judge.ask(captures, "full").items()}
    luna = {s: v["determination"] for s, v in cascade_v2.determine(captures).items()}

    candidates = {"luna_v2_cascade": luna,
                  "jev_snippets_choice": gated(by_choice, snip, captures),
                  "jev_full_choice": gated(by_choice, full, captures),
                  "jev_full_choice_no_gate": {s: by_choice(f) for s, f in full.items()}}
    for t in (0.5, 0.6, 0.7, 0.8, 0.9):
        candidates[f"jev_full_threshold_{t}"] = gated(by_threshold(t), full, captures)
        candidates[f"jev_full_questions_{t}"] = gated(by_questions(t), full, captures)
    for t in (0.6, 0.8, 0.9):
        escalate = {s: snip[s] if max(snip[s]["p_ai"], snip[s]["p_non_ai"], snip[s]["p_unresolved"]) >= t else full[s]
                    for s in snip}
        candidates[f"jev_escalate_{t}"] = gated(by_choice, escalate, captures)

    rows = {}
    for name, pred in candidates.items():
        r = summarize(name, gold, pred)
        r["unsupported_ai_calls"] = unsupported_ai(gold, pred)
        rows[name] = r
        print(f"{name:<28} macroF1={r['resolved_macro_f1']:.3f} acc={r['resolved_accuracy']:.3f} fa={r['false_alarms']:>2} "
              f"miss={r['missed_ai']:>2} abst={r['resolved_abstained']:>2} unsupported_ai={r['unsupported_ai_calls']:>2} "
              f"gold-unres->{r['gold_unresolved_predictions']}")

    calibration = {}
    for lo in (0.0, 0.1, 0.3, 0.5, 0.7, 0.9, 0.99):
        hi = {0.0: 0.1, 0.1: 0.3, 0.3: 0.5, 0.5: 0.7, 0.7: 0.9, 0.9: 0.99, 0.99: 1.01}[lo]
        ids = [s for s, f in full.items() if lo <= f["p_ai"] < hi and gold[s] != "unresolved"]
        calibration[f"{lo}-{min(hi, 1.0)}"] = {"pages": len(ids), "gold_ai_rate": sum(gold[s] == "ai" for s in ids) / len(ids) if ids else None}
    print("calibration of full-text P(ai) on resolved pages:", json.dumps(calibration))
    tokens = sum(r["usage"]["input_tokens"] for m in ("snippets", "full") for r in jev_judge.ask(captures, m).values())
    print(f"input tokens used for both modes: {tokens:,} (~${tokens * 0.042 / 1e6:.3f})")
    print("models:", Counter(r["model"] for r in jev_judge.ask(captures, "full").values()))
    OUT.write_text(json.dumps({"candidates": rows, "calibration_full_p_ai": calibration, "input_tokens": tokens},
                              indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
