"""Audit trail for Jev cascade decisions: the strongest evidence sentence per judged page, and a review flag for AI calls
whose best sentence is weak. Decisions themselves come unchanged from jev_cascade.determine."""
import jev_cascade
import jev_judge

REVIEW_EVIDENCE_CUTOFF = 0.6
TOP_EVIDENCE = 3


def classify(captures):
    """Return jev_cascade decisions with top evidence sentences and a needs_review flag added to judged pages."""
    decisions = jev_cascade.determine(captures)
    judged = [c for c in captures if decisions[c["sample_id"]]["stage"] == "jev_judge"]
    evidence = jev_judge.ask_evidence(judged)
    for c in judged:
        d = decisions[c["sample_id"]]
        ranked = evidence[c["sample_id"]]
        d["evidence"] = [{"sentence": s, "probability": round(p, 4)} for p, s in ranked[:TOP_EVIDENCE]]
        d["needs_review"] = d["determination"] == "ai" and (not ranked or ranked[0][0] < REVIEW_EVIDENCE_CUTOFF)
    for d in decisions.values():
        d.setdefault("needs_review", False)
    return decisions
