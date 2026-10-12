"""Check an operational stage handoff before another stage consumes it."""
import json
import sys
from pathlib import Path


class InvalidHandoff(ValueError):
    pass


def check(data, stage, ids):
    def require(condition, reason):
        if not condition:
            raise InvalidHandoff(reason)

    require(isinstance(data, dict) and data.get("stage") == stage, "wrong stage")
    records = data.get("records")
    require(isinstance(records, list), "missing records")
    actual = [row.get("product_group_id") for row in records if isinstance(row, dict)]
    require(len(actual) == len(ids) == len(records), "wrong record count")
    require(len(set(actual)) == len(actual) and set(actual) == set(ids), "group coverage mismatch")
    for row in records:
        require(row.get("ai_status") in ("ai", "non_ai"), "invalid binary label")
        require(row.get("evidence_strength") in ("supported", "weak"), "invalid evidence strength")
        require(type(row.get("forced_decision")) is bool, "missing forced flag")
        require(not row["forced_decision"] or row["evidence_strength"] == "weak", "forced label marked supported")
        require(isinstance(row.get("rationale"), str) and bool(row["rationale"]), "missing rationale")
        require(isinstance(row.get("version_scope"), str) and bool(row["version_scope"]), "missing version scope")
        for flag in ("grouping_conflict", "structural_blocker", "needs_adjudication"):
            require(type(row.get(flag)) is bool, "missing stage flag: " + flag)
        require(not row["grouping_conflict"] or row["structural_blocker"], "group conflict lacks blocker")
        require(isinstance(row.get("issues"), list), "missing issues")
        if row["ai_status"] == "non_ai":
            require(all(row.get(k) is None for k in ("ai_type", "ai_type_rationale", "ai_type_evidence_strength", "ai_type_forced_decision")), "non-AI subtype populated")
        else:
            require(row.get("ai_type") in ("ai_native", "ai_enabled"), "missing AI subtype")
            require(row.get("ai_type_evidence_strength") in ("supported", "weak"), "invalid subtype evidence")
            require(type(row.get("ai_type_forced_decision")) is bool, "missing subtype forced flag")
            require(not row["ai_type_forced_decision"] or row["ai_type_evidence_strength"] == "weak", "forced subtype marked supported")
            require(isinstance(row.get("ai_type_rationale"), str) and bool(row["ai_type_rationale"]), "missing subtype rationale")
        require(isinstance(row.get("sources"), list), "missing source ledger")
        require(row["sources"] or row["evidence_strength"] == "weak" or row["structural_blocker"], "supported label without evidence")
        for source in row["sources"]:
            require(isinstance(source, dict), "invalid source")
            require(all(isinstance(source.get(k), str) and source[k] for k in ("url", "excerpt", "applicability")), "missing source content")
            require(source.get("source_type") in ("official", "archived_official", "secondary", "source_dataset"), "invalid source type")
            require(isinstance(source.get("supports"), list) and source["supports"], "missing source role")
            require(all(k in source for k in ("captured_at", "capture_reference", "publication_or_version")), "missing capture provenance fields")
        counts = row.get("research_counts")
        require(isinstance(counts, dict), "missing research counters")
        require(all(type(counts.get(k)) is int and counts[k] >= 0 for k in ("search_rounds", "full_page_reads")), "invalid research counters")
        # Observations must stay truthful; execution limits are audited separately.
    return {"stage": stage, "groups": len(records), "structural_blockers": sum(r["structural_blocker"] for r in records)}


def self_test():
    row = {"product_group_id": "one", "ai_status": "non_ai", "ai_type": None, "evidence_strength": "weak", "forced_decision": True, "ai_type_evidence_strength": None, "ai_type_forced_decision": None, "rationale": "Insufficient evidence; forced candidate.", "ai_type_rationale": None, "version_scope": "Undated source.", "grouping_conflict": False, "structural_blocker": False, "needs_adjudication": True, "issues": [], "sources": [], "research_counts": {"search_rounds": 4, "full_page_reads": 0}}
    assert check({"stage": "blind", "records": [row]}, "blind", ["one"])["groups"] == 1
    cases = [("blind", []), ("other", [row]), ("blind", [row, row]), ("blind", [{**row, "ai_status": "unknown"}]), ("blind", [{**row, "ai_type": "ai_native"}]), ("blind", [{**row, "evidence_strength": "supported"}]), ("blind", [{**row, "research_counts": {"search_rounds": -1, "full_page_reads": 0}}]), ("blind", [{**row, "grouping_conflict": True}])]
    for stage, records in cases:
        try:
            check({"stage": stage, "records": records}, "blind", ["one"])
        except InvalidHandoff:
            continue
        raise AssertionError("accepted invalid handoff")
    print("Handoff self-check: 9 cases passed; observed counters are not clamped.")


if __name__ == "__main__":
    if sys.argv[1:] == ["--self-test"]:
        self_test()
    else:
        filename, stage, *ids = sys.argv[1:]
        print(json.dumps(check(json.loads(Path(filename).read_text()), stage, ids)))
