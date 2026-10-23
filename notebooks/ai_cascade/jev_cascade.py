"""AI Determination cascade with Jev as the judge: the v2 gate, then Jev on full homepage text with a P(ai) cutoff."""
import cascade_v2
import jev_judge

STATE_MODE = "full"
AI_CUTOFF = 0.4


def decide(f):
    if f["p_ai"] >= AI_CUTOFF:
        return "ai"
    return max(("non_ai", "unresolved"), key=lambda k: f[f"p_{k}"])


def determine(captures):
    """Return {sample_id: {"determination", "stage", ...}} for every capture, keeping Jev's probabilities for audit."""
    out, gated = {}, []
    for capture in captures:
        text = cascade_v2.all_text(capture)
        if cascade_v2.gate(text):
            gated.append(capture)
        elif len(text.strip()) < cascade_v2.MIN_TEXT_CHARS:
            out[capture["sample_id"]] = {"determination": "unresolved", "stage": "insufficient_text"}
        else:
            out[capture["sample_id"]] = {"determination": "non_ai", "stage": "keyword_gate"}
    results = jev_judge.ask(gated, STATE_MODE) if gated else {}
    for capture in gated:
        f = jev_judge.features(results[capture["sample_id"]])
        out[capture["sample_id"]] = {"determination": decide(f), "stage": "jev_judge", "model": results[capture["sample_id"]]["model"],
                                     **{k: round(v, 4) for k, v in f.items()}}
    return out
