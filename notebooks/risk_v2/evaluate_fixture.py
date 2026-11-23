"""Run the v2 synthetic fixture through the connected pipeline and score every stage.

The fixture is uploaded through the real API (`POST /batches`), which runs the default
pipeline: identity resolution -> website fetch -> AI determination -> category
classification -> contextual risk -> save. Results are read back from
`GET /runs/{id}/assessments`, printed with their tier and explanation, and compared with
`data/synthetic_enterprise_activity/v2/evaluation_only/expected_scenarios.csv`.

Every stage is real except, optionally, the Jev judge:

- website fetch uses the real HTTP client and DNS resolver (network access needed);
- category classification uses the real fastembed model (downloaded on first use);
- AI determination uses the real Jev judge when ``TYPESAFE_API_KEY`` is set (environment or
  repository ``.env``). Without a key it uses a labelled stand-in that answers "AI" for every
  page passing the keyword gate, because the real client refuses to run without a key.

Two risk scores are reported:

- end to end: the tiers the pipeline produced from its own AI and category answers;
- risk only: the same identities and categories, but AI status taken from the answer key, so
  only the rubric and context grouping are scored.

Usage, from ``backend/``::

    .venv\\Scripts\\python ..\\notebooks\\risk_v2\\evaluate_fixture.py [--stand-in-judge]
"""

import argparse
import csv
import json
import sys
import tempfile
from collections import Counter
from dataclasses import replace
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "backend"))

from fastapi.testclient import TestClient  # noqa: E402

from app.ai_determination.cascade import AiDetermination  # noqa: E402
from app.ai_determination.jev import JevClient  # noqa: E402
from app.config import Settings  # noqa: E402
from app.main import create_app  # noqa: E402
from app.ingestion.activity import parse_activity  # noqa: E402
from app.pipeline.default import default_pipeline  # noqa: E402
from app.pipeline.identity import load_tool_metadata  # noqa: E402
from app.pipeline.usage_contexts import assess_usage_contexts  # noqa: E402

FIXTURE = REPO / "data/synthetic_enterprise_activity/v2"
OUT = Path(__file__).resolve().parent / "results"
NO_TIER = {"not_applicable", "not_assessed_ai_unresolved"}
# Expected labels whose usage is saved as a not_assessed row (rubric v2.1); not_applicable
# (non-AI) usage gets no row at all.
NOT_ASSESSED = {"not_assessed_ai_unresolved"}


class StandInJudge:
    """Answers "AI" for every request that reaches the judge. Not a real determination."""

    def __call__(self, body):
        questions = body["questions"]
        if "determination" in questions:
            answers = {
                "determination": {"probabilities": {"ai": 0.9, "non_ai": 0.05, "unresolved": 0.05}},
                "own_ai_task": {"noul": 0.7},
                "ai_only_subject": {"noul": 0.1},
                "vague_ai_claim": {"noul": 0.2},
                "describes_product": {"noul": 0.95},
            }
        else:
            answers = {key: {"noul": 0.5} for key in questions}
        return {"model": "stand-in-judge", "answers": answers}


def load_csv(path):
    with path.open(encoding="utf-8", newline="") as stream:
        return list(csv.DictReader(stream))


def run_pipeline(data_dir, judge):
    settings = Settings.from_env()
    settings = replace(
        settings,
        data_dir=data_dir,
        tool_metadata_path=FIXTURE / "scenario_tool_metadata.csv",
        gemini_api_key=None,
    )
    pipeline = default_pipeline(settings, jev=judge)
    captured = {}
    original_save = pipeline.save

    def save(connection, context):
        captured.update(context.results)
        original_save(connection, context)

    client = TestClient(create_app(settings, replace(pipeline, save=save)))
    upload = client.post(
        "/batches",
        files={"file": ("activity.csv", (FIXTURE / "activity.csv").read_bytes(), "text/csv")},
    )
    upload.raise_for_status()
    run = upload.json()["latest_run"]
    if run["status"] != "succeeded":
        raise SystemExit(f"Run failed: {json.dumps(run, indent=2)}")
    rows, offset = [], 0
    while True:
        page = client.get(
            f"/runs/{run['run_id']}/assessments", params={"limit": 100, "offset": offset}
        ).json()
        rows += page["items"]
        offset += page["limit"]
        if offset >= page["total"]:
            break
    return run, rows, captured


def candidate_for(event_ids, identities):
    matches = [i for i, c in enumerate(identities) if set(event_ids) <= set(c.event_ids)]
    return matches[0] if len(matches) == 1 else None


def risk_outcome(context_rows, event_ids):
    """The single context holding exactly the scenario's events, or why there isn't one."""
    holding = [r for r in context_rows if set(r["event_ids"]) & set(event_ids)]
    if not holding:
        return None, "no_context"
    exact = [r for r in holding if set(r["event_ids"]) == set(event_ids)]
    return (exact[0], "exact") if exact else (holding[0], "merged_or_split")


def score_risk(scenario, row, how):
    want_tier = scenario["expected_risk_behavior"]
    if want_tier in NOT_ASSESSED:
        ok = row is not None and how == "exact" and row["tier"] == "not_assessed"
        return {"tier": ok, "all": ok, "got_tier": row["tier"] if row else "no_context"}
    if want_tier in NO_TIER:
        return {"tier": row is None, "all": row is None, "got_tier": row["tier"] if row else "no_context"}
    if row is None or how != "exact":
        return {"tier": False, "all": False, "got_tier": how if row is None else f"{row['tier']} ({how})"}
    fields = {
        "interaction_class": (row["interaction_class"], scenario["expected_interaction_class"]),
        "base_tier": (row["base_tier"], scenario["expected_base_tier"]),
        "tier": (row["tier"], want_tier),
        "first_reason": (row["reason_codes"][0], scenario["expected_first_reason_code"]),
        "flags": (
            sorted(row["flag_reasons"]),
            sorted(filter(None, scenario["expected_flag_reasons"].split("|"))),
        ),
    }
    mismatched = {k: v for k, v in fields.items() if v[0] != v[1]}
    return {"tier": row["tier"] == want_tier, "all": not mismatched, "got_tier": row["tier"],
            "mismatched": mismatched}


def answer_key_ai(identities, scenarios):
    statuses = []
    for candidate in identities:
        labels = {
            s["expected_ai_status"]
            for s in scenarios
            if set(s["event_ids"].split("|")) <= set(candidate.event_ids)
        }
        label = labels.pop() if len(labels) == 1 else "unresolved"
        statuses.append(AiDetermination(label, "answer_key"))
    return statuses


def pct(hits, total):
    return f"{hits}/{total} ({100 * hits / total:.0f}%)" if total else "n/a"


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--stand-in-judge", action="store_true", help="never call the real Jev judge")
    args = parser.parse_args()

    key = Settings.from_env().typesafe_api_key
    use_real = bool(key) and not args.stand_in_judge
    judge = JevClient(key) if use_real else StandInJudge()
    judge_label = "real Jev judge" if use_real else "STAND-IN judge (answers AI for every gate-passing page)"
    scenarios = load_csv(FIXTURE / "evaluation_only/expected_scenarios.csv")

    # Windows may still hold the SQLite file open when the directory is removed.
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        run, rows, results = run_pipeline(Path(tmp), judge)
    identities = results["identities"]
    ais = results["ai_determinations"]
    categories = results["category_classifications"]

    print(f"\nRun {run['run_id']} succeeded with the {judge_label}.")
    print(f"Versions: {json.dumps(run['versions'], indent=2)}\n")
    print("=" * 100)
    print(f"Every Usage Context the pipeline assessed ({len(rows)}):")
    print("=" * 100)
    for row in rows:
        esc = f", escalation {row['escalation']} from {row['base_tier']}" if row["escalation"] else ""
        if row["tier"] == "not_assessed":
            esc = ""
        print(f"\n[{row['tier']}] {row['application_name']} · {row['department']} · "
              f"{row['usage_purpose']} · {row['data_sensitivity_tier']} · {row['interaction_class']}"
              f"  (governance {row['governance_level']}, exposure {row['exposure_level']}{esc})")
        print(f"  {row['explanation']}")
        if row["flag_reasons"]:
            print(f"  flags: {', '.join(row['flag_reasons'])}")

    # Per-scenario scoring of each stage.
    per_scenario = []
    for s in scenarios:
        ids = s["event_ids"].split("|")
        idx = candidate_for(ids, identities)
        identity = identities[idx].outcome if idx is not None else "split"
        ai = ais[idx].determination if idx is not None else "split"
        ai_method = f"{ais[idx].stage}:{ais[idx].reason or ''}" if idx is not None else ""
        cat = categories[idx] if idx is not None else None
        got_category = (cat.category if cat and cat.outcome == "assigned" else
                        cat.outcome if cat else "split")
        row, how = risk_outcome(rows, ids)
        per_scenario.append({
            "scenario": s,
            "identity": identity,
            "ai": ai,
            "ai_method": ai_method,
            "category": got_category,
            "risk": score_risk(s, row, how),
        })

    # Risk-only: same identities and categories, AI status from the answer key.
    events = parse_activity((FIXTURE / "activity.csv").read_bytes())
    metadata = load_tool_metadata(FIXTURE / "scenario_tool_metadata.csv")
    isolated = assess_usage_contexts(
        events, identities, answer_key_ai(identities, scenarios), categories, metadata
    )
    isolated_rows = [
        {
            "event_ids": list(a.context.event_ids),
            "tier": a.assessment.tier,
            "base_tier": a.assessment.base_tier,
            "interaction_class": a.context.interaction_class,
            "reason_codes": a.assessment.reason_codes,
            "flag_reasons": a.assessment.flag_reasons,
        }
        for a in isolated
    ]
    risk_only = [score_risk(s, *risk_outcome(isolated_rows, s["event_ids"].split("|")))
                 for s in scenarios]

    print("\n" + "=" * 100)
    print("Per scenario: expected vs pipeline")
    print("=" * 100)
    header = f"{'scenario':12} {'tool':18} {'class':19} {'AI exp/got':22} {'category exp/got':58} {'tier exp/got'}"
    print(header)
    for item in per_scenario:
        s = item["scenario"]
        ai_ok = "✓" if item["ai"] == s["expected_ai_status"] else "✗"
        cat_ok = "✓" if s["expected_ai_status"] != "ai" or item["category"] == s["expected_category"] else "✗"
        r = item["risk"]
        risk_ok = "✓" if r["all"] else ("~" if r["tier"] else "✗")
        print(f"{s['scenario_id']:12} {_tool(s, identities):18} "
              f"{s['expected_interaction_class']:19} {ai_ok} {s['expected_ai_status']}/{item['ai']:<14} "
              f"{cat_ok} {s['expected_category'][:26]}/{str(item['category'])[:27]:<27} "
              f"{risk_ok} {s['expected_risk_behavior']}/{r['got_tier']}")
        if item["ai"] != s["expected_ai_status"]:
            print(f"{'':14}  AI decided by {item['ai_method']}")
        if r.get("mismatched"):
            for field, (got, want) in r["mismatched"].items():
                print(f"{'':14}  {field}: expected {want}, got {got}")

    n = len(per_scenario)
    identity_hits = sum(i["identity"] == i["scenario"]["expected_identity_outcome"]
                        for i in per_scenario)
    ai_hits = sum(i["ai"] == i["scenario"]["expected_ai_status"] for i in per_scenario)
    ai_scenarios = [i for i in per_scenario if i["scenario"]["expected_ai_status"] == "ai"]
    cat_hits = sum(i["category"] == i["scenario"]["expected_category"] for i in ai_scenarios)
    e2e_tier = sum(i["risk"]["tier"] for i in per_scenario)
    e2e_all = sum(i["risk"]["all"] for i in per_scenario)
    tiered = [i for i, s in zip(per_scenario, scenarios) if s["expected_risk_behavior"] not in NO_TIER]
    ro_tier = sum(r["tier"] for r in risk_only)
    ro_all = sum(r["all"] for r in risk_only)
    confusion = Counter(
        (i["scenario"]["expected_risk_behavior"], i["risk"]["got_tier"]) for i in per_scenario
    )

    summary = {
        "run_id": run["run_id"],
        "judge": judge_label,
        "scenarios": n,
        "contexts_saved": len(rows),
        "identity_accuracy": pct(identity_hits, n),
        "ai_status_accuracy": pct(ai_hits, n),
        "category_accuracy_on_ai_scenarios": pct(cat_hits, len(ai_scenarios)),
        "risk_end_to_end_tier_accuracy": pct(e2e_tier, n),
        "risk_end_to_end_all_fields": pct(e2e_all, n),
        "risk_end_to_end_tier_accuracy_on_tiered_scenarios": pct(
            sum(i["risk"]["tier"] for i in tiered), len(tiered)),
        "risk_only_tier_accuracy": pct(ro_tier, n),
        "risk_only_all_fields": pct(ro_all, n),
        "not_assessed_contexts": sum(r["tier"] == "not_assessed" for r in rows),
        "contexts_not_in_any_scenario": len([
            r for r in rows
            if not any(set(r["event_ids"]) & set(s["event_ids"].split("|")) for s in scenarios)
        ]),
        "tier_confusion_expected_to_got": {f"{a} -> {b}": c for (a, b), c in sorted(confusion.items())},
    }
    print("\n" + "=" * 100)
    print("Accuracy")
    print("=" * 100)
    for k, v in summary.items():
        if k != "tier_confusion_expected_to_got":
            print(f"  {k:52} {v}")
    print("  tier confusion (expected -> got):")
    for k, v in summary["tier_confusion_expected_to_got"].items():
        print(f"    {k:45} {v}")

    OUT.mkdir(exist_ok=True)
    tag = "jev" if use_real else "stand_in"
    (OUT / f"summary_{tag}.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    (OUT / f"contexts_{tag}.json").write_text(
        json.dumps([{k: r[k] for k in ("application_name", "department", "usage_purpose",
                                         "data_sensitivity_tier", "interaction_class", "tier",
                                         "base_tier", "escalation", "reason_codes", "flag_reasons",
                                         "explanation", "event_count")} for r in rows],
                   indent=2) + "\n", encoding="utf-8")
    print(f"\nWrote {OUT / f'summary_{tag}.json'} and contexts_{tag}.json")


def _tool(scenario, identities):
    ids = scenario["event_ids"].split("|")
    idx = candidate_for(ids, identities)
    return identities[idx].application_names[0][:18] if idx is not None else "?"


if __name__ == "__main__":
    main()
