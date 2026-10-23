"""Explore Jev per-sentence evidence on the 440 development pages: does it find the labelers' evidence, and does a
weak top sentence flag risky decisions? Nothing here may read test2 labels."""
import json
import re
from collections import Counter
from pathlib import Path

import jev_cascade
import jev_judge
from evaluate_test import load_pass
from evaluate_v2_dev import development_pages

HERE = Path(__file__).resolve().parent
OUT = HERE / "jev_evidence_dev_results.json"
LABEL_DIRS = (HERE.parent / "website_feasibility/labeling", HERE / "test_labeling")


def words(text):
    return set(re.findall(r"[a-z0-9]+", text.lower()))


def matches(sentence, quote):
    """True when a labeler quote and an evidence sentence are the same passage, allowing truncation either way."""
    a, b = " ".join(sorted(words(sentence))), " ".join(sorted(words(quote)))
    if not a or not b:
        return False
    s, q = sentence.lower().strip(), quote.lower().strip()
    if s[:60] in q or q[:60] in s:
        return True
    ws, wq = words(sentence), words(quote)
    return len(ws & wq) / len(ws | wq) >= 0.5


def main():
    captures, gold = development_pages()
    quotes = {}
    for d in LABEL_DIRS:
        for name in ("A", "B"):
            for s, item in load_pass(name, d).items():
                if item["label"] in ("ai_core", "ai_feature") and item["evidence"]:
                    quotes.setdefault(s, []).append(item["evidence"])
    decisions = jev_cascade.determine(captures)
    judged = [c for c in captures if decisions[c["sample_id"]]["stage"] == "jev_judge"]
    evidence = jev_judge.ask_evidence(judged)

    hits = Counter()
    for c in judged:
        s = c["sample_id"]
        if gold[s] != "ai" or decisions[s]["determination"] != "ai" or s not in quotes:
            continue
        ranked = [sent for _, sent in evidence[s]]
        hits["pages"] += 1
        hits["top1"] += any(matches(ranked[0], q) for q in quotes[s])
        hits["top3"] += any(matches(r, q) for r in ranked[:3] for q in quotes[s])
        hits["quote_in_candidates"] += any(matches(r, q) for r in ranked for q in quotes[s])
    print("top evidence vs labeler quotes on correct AI calls:", dict(hits))

    flag_rows = {}
    for t in (0.3, 0.4, 0.5, 0.6, 0.7):
        ai_calls = [c["sample_id"] for c in judged if decisions[c["sample_id"]]["determination"] == "ai"]
        flagged = [s for s in ai_calls if evidence[s][0][0] < t]
        kept = [s for s in ai_calls if evidence[s][0][0] >= t]
        others = [c["sample_id"] for c in judged if decisions[c["sample_id"]]["determination"] != "ai"]
        strong_other = [s for s in others if evidence[s][0][0] >= t]
        flag_rows[t] = {"ai_calls": len(ai_calls), "flagged": len(flagged),
                        "flagged_wrong": sum(gold[s] != "ai" for s in flagged),
                        "kept_wrong": sum(gold[s] != "ai" for s in kept),
                        "non_ai_calls_with_strong_evidence": len(strong_other),
                        "of_which_gold_ai": sum(gold[s] == "ai" for s in strong_other)}
        r = flag_rows[t]
        print(f"t={t}: AI calls flagged {r['flagged']:>3}/{r['ai_calls']} (wrong among flagged {r['flagged_wrong']:>2}, "
              f"wrong left unflagged {r['kept_wrong']:>2}) | non-AI calls with evidence>=t {r['non_ai_calls_with_strong_evidence']:>3} "
              f"(gold AI {r['of_which_gold_ai']})")
    tokens = sum(v["usage"]["input_tokens"] for v in json.loads(jev_judge.CACHE.read_text()).values())
    print(f"cache now holds {tokens:,} input tokens (~${tokens * 0.042 / 1e6:.3f} total spent)")
    OUT.write_text(json.dumps({"evidence_vs_labelers": hits, "review_flag": flag_rows}, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
