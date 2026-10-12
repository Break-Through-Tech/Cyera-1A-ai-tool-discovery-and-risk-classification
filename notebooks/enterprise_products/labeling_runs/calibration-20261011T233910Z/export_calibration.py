"""Export the completed calibration only; never alter the cleaned dataset."""
import csv
import hashlib
import html
import json
import sys
from collections import Counter
from pathlib import Path

from check_stage import check

ROOT = Path(__file__).resolve().parent
HOLDS = {
    "enterprise-0f6d79bef9eee30125b960bb4136df7959d235719365b35fd15cf280ae814d15": "TRIRIGA source-description claim is not an official-site claim; v11.6 new AI monitoring is not mapped to this historical bridge/subscription item.",
    "enterprise-a305a1fcde5d9fac8e8ddeed05650ea3e0ea9a10ad3e24114eeefe1cd7f51491": "Alfabet historical/deployment inclusion of current AI help assistant is unverified; AI portfolio governance does not itself establish AI use.",
}


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def eligible(row, hold=None):
    binary = row["evidence_strength"] == "supported" and not row["forced_decision"] and not hold
    subtype = binary and row["ai_status"] == "ai" and row["ai_type_evidence_strength"] == "supported" and not row["ai_type_forced_decision"]
    return bool(binary), bool(subtype)


def assemble(refs, batches):
    histories, finals = {}, {}
    for batch, ids in batches.items():
        stages = {}
        for stage in ("labeler", "blind", "evidence"):
            data = json.loads(Path(refs[f"{stage}-{batch}"]).read_text())
            check(data, stage, ids)
            stages[stage] = {row["product_group_id"]: row for row in data["records"]}
        flagged = [gid for gid, row in stages["evidence"].items() if row["needs_adjudication"]]
        for stage in ("adjudicator", "finalcheck"):
            if not flagged:
                continue
            data = json.loads(Path(refs[f"{stage}-{batch}"]).read_text())
            check(data, stage, flagged)
            stages[stage] = {row["product_group_id"]: row for row in data["records"]}
        for gid in ids:
            assert gid not in finals, "duplicate batch membership"
            history = {stage: rows[gid] for stage, rows in stages.items() if gid in rows}
            row = history.get("finalcheck", history["evidence"])
            assert not row["structural_blocker"] and not row["grouping_conflict"], "blocked group cannot be exported"
            assert not row["needs_adjudication"], "unfinished stage routing"
            finals[gid], histories[gid] = row, history
    return finals, histories


def write_csv(path, rows, fields):
    with path.open("w", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def resource_usage():
    children, captures, research_calls = [], {}, Counter()
    seen = set()
    for folder in ("runtime", "runtime-recovery", "runtime-verification", "runtime-completed"):
        status = json.loads((ROOT / folder / "status.json").read_text())
        for child in status["steps"]:
            session = child["sessionFile"]
            if session in seen:
                continue
            seen.add(session)
            events = [json.loads(line) for line in Path(session).read_text().splitlines()]
            usage, cost, calls = Counter(), 0.0, Counter()
            for event in events:
                message = event.get("message", {})
                if message.get("role") == "assistant":
                    reported = message.get("usage", {})
                    for key in ("input", "output", "cacheRead", "cacheWrite", "totalTokens"):
                        usage[key] += reported.get(key, 0)
                    cost += reported.get("cost", {}).get("total", 0)
                content = message.get("content", [])
                for block in content if isinstance(content, list) else []:
                    if block.get("type") == "toolCall":
                        calls[block["name"]] += 1
            models = {event["message"].get("model") for event in events if event.get("message", {}).get("role") == "assistant"}
            assert models == {"gpt-6-luna"}, "unexpected model substitution"
            prompts = [event["message"].get("content") for event in events if event.get("message", {}).get("role") == "user"]
            prompt_hash = hashlib.sha256(json.dumps(prompts, sort_keys=True).encode()).hexdigest()
            children.append({"run_id": child["runId"], "stage": child["workflowKey"], "workflow_run_id": status["runId"], "state": child["status"], "session": session, "prompt_sha256": prompt_hash, "duration_ms": child.get("durationMs"), "reported_usage": dict(usage), "reported_cost_usd": cost, "tool_calls": dict(calls)})
            research_calls.update({key: calls[key] for key in ("web_search", "source_check", "fetch_content", "get_search_content")})
    for pattern in ("*/retained_pages/*.json", "*/retained_recovery_pages/*.json", "*/retained_verification_pages/*.json"):
        for path in ROOT.glob(pattern):
            page = json.loads(path.read_text())
            if page.get("content"):
                captures.setdefault(page["url"], []).append({"path": str(path.relative_to(ROOT)), "sha256": digest(path), "captured_at": page.get("captured_at"), "content_sha256": hashlib.sha256(page["content"].encode()).hexdigest()})
    totals = Counter()
    for row in children:
        totals.update(row["reported_usage"])
    initial_audit = json.loads((ROOT / "handoffs/resource_audit.json").read_text())
    initial_group_counts = Counter()
    for lane in initial_audit["actual_counts_by_lane"].values():
        for counts in lane.values():
            initial_group_counts.update(counts)
    return {"children": children, "reported_usage": dict(totals), "reported_tokens": totals["totalTokens"], "reported_cost_usd": sum(row["reported_cost_usd"] for row in children), "research_tool_calls": dict(research_calls), "initial_group_attributed_research_counts": dict(initial_group_counts), "adjudication_additional_discovery": {"tool_calls": 1, "product_queries": 4, "new_page_fetches": 0}, "cost_caveat": "Provider/harness telemetry only, not an invoice; excludes parent orchestration and search-provider charges. Includes stopped/failed children and recovery overhead. Total tokens include cached reads."}, captures


def render_flagged_html(out, queue, ledger):
    cards = []
    for row in queue:
        sources = "".join(f'<li><a href="{html.escape(source["url"], quote=True)}">{html.escape(source["url"])}</a><blockquote>{html.escape(source["excerpt"])}</blockquote><p>{html.escape(source["applicability"])}</p></li>' for source in row["sources"])
        cards.append(f'<article><h2>{html.escape(row["product_name"])} — {html.escape(row["ai_status"] + (" / " + row["ai_type"] if row["ai_type"] else ""))}</h2><p><b>User review:</b> {html.escape(row["user_review_disposition"])}</p><p><b>Why flagged:</b> {html.escape(row["review_reasons"])}</p><p><b>Final rationale:</b> {html.escape(row["final_rationale"])}</p><details><summary>First-pass labels and evidence</summary><p>{html.escape(row["first_pass_summary"])}</p><ul>{sources}</ul></details></article>')
    page = """<!doctype html><html lang=\"en\"><meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width,initial-scale=1\"><title>Reviewed calibration cases</title><style>body{font:16px/1.55 system-ui,sans-serif;max-width:1000px;margin:2rem auto;padding:0 1rem;color:#182433;background:#f4f7fa}header,article{background:#fff;border:1px solid #d8e0e8;border-radius:10px;padding:1rem 1.25rem;margin:1rem 0}h1{margin:.2rem 0}article h2{font-size:1.2rem}details{border-top:1px solid #ddd;padding-top:.7rem}summary{cursor:pointer;font-weight:700}blockquote{border-left:3px solid #ccd6df;padding-left:.8rem;color:#425466}a{overflow-wrap:anywhere}.note{background:#fff4dc;padding:.9rem;border-left:4px solid #b87918}</style><header><h1>Reviewed flagged calibration cases</h1><p>All 16 flagged cases were reviewed by the user. Original Luna judgments were accepted except Evercoast Managed Services, which the user directed to ai / ai_enabled.</p><p class=\"note\">Human review is recorded separately. Weak/forced evidence flags remain unchanged and continue to exclude those cases from trusted training/evaluation. Source-stage judgments are preserved.</p></header>""" + "".join(cards) + "</html>"
    (out / "flagged_cases.html").write_text(page)


def export():
    manifest = json.loads((ROOT / "manifest.json").read_text())
    user_review = json.loads((ROOT / "user_review_decisions.json").read_text())
    reviewed = set(user_review["reviewed_groups"])
    overrides = user_review["overrides"]
    repo = Path(manifest["repository"])
    live_input_drift = {}
    for name, expected in manifest["input_sha256"].items():
        assert digest(ROOT / "inputs" / Path(name).name) == expected, f"modified frozen input: {name}"
        live_digest = digest(repo / name)
        if live_digest != expected:
            live_input_drift[name] = {"pinned_sha256": expected, "current_sha256": live_digest}
    assert set(live_input_drift) <= {"notebooks/enterprise_products/LABELING_WORKFLOW.md"}, "unexpected live input drift"
    completed = json.loads((ROOT / "runtime-completed/status.json").read_text())
    assert completed["state"] == "complete", "workflow unfinished"
    result = completed["workflow"]["value"]
    assert not result["blockedGroupIds"], "structural blockers unresolved"
    packets = {batch: json.loads((ROOT / f"inputs/batch-{batch}.json").read_text())["groups"] for batch in ("01", "02")}
    batches = {batch: [row["product_group_id"] for row in groups] for batch, groups in packets.items()}
    finals, histories = assemble(result["artifactPaths"], batches)
    assert set(finals) == set(manifest["selected_group_ids"]) and len(finals) == 20
    assert reviewed <= set(finals), "user review references unknown group"
    assert set(overrides) <= reviewed and len(reviewed) == 16, "review/override coverage changed"
    assert finals == assemble(result["artifactPaths"], batches)[0], "resume changed completed judgments"
    with (ROOT / "inputs/products_cleaned.csv").open(newline="") as file:
        records = list(csv.DictReader(file))
    selected = [row for row in records if row["product_group_id"] in finals]
    assert len(records) == manifest["source_records"] and len({r["product_group_id"] for r in records}) == manifest["source_groups"]
    assert len(selected) == 21 and {int(r["source_record_number"]) for r in selected} == set(manifest["selected_source_record_numbers"])
    metadata = {group["product_group_id"]: group["records"][0] for groups in packets.values() for group in groups}
    resources, captures = resource_usage()
    initial_run_ids = {child["workflowKey"]: child["runId"] for child in json.loads((ROOT / "runtime-recovery/status.json").read_text())["steps"]}
    stage_run_ids = {**initial_run_ids, **result["childRunIds"]}
    children_by_id = {child["run_id"]: child for child in resources["children"]}
    labels, ledger, queue, reviewed_page = [], [], [], []
    for gid in manifest["selected_group_ids"]:
        row, hold = dict(finals[gid]), HOLDS.get(gid)
        user_decision = None
        if gid in reviewed:
            user_decision = {"disposition": "user_override" if gid in overrides else "accepted_original_luna_judgment", "original_luna_label": {key: finals[gid][key] for key in ("ai_status", "ai_type")}, "parent_hold_disposition": "accepted_by_user_review" if hold and gid not in overrides else ("retained_as_evidence_uncertainty" if hold else None)}
        if gid in overrides:
            override = overrides[gid]
            assert override["ai_status"] == "ai" and override["ai_type"] in ("ai_native", "ai_enabled")
            row["ai_status"], row["ai_type"] = override["ai_status"], override["ai_type"]
            row["evidence_strength"], row["forced_decision"] = "weak", True
            row["ai_type_evidence_strength"], row["ai_type_forced_decision"] = "weak", True
            row["rationale"] = override["rationale"]
            row["ai_type_rationale"] = "User-directed ai_enabled subtype. The source-record managed-services product is not linked to the distinct AI-featured Evercoast products in the retained evidence; subtype evidence remains weak/forced."
            row["issues"] = list(row["issues"]) + ["User reviewed and overrode the binary/subtype to ai / ai_enabled; product-feature applicability evidence remains unresolved."]
        active_hold = hold and (gid not in reviewed or gid in overrides)
        binary_ok, subtype_ok = eligible(row, active_hold)
        members = [int(r["source_record_number"]) for r in selected if r["product_group_id"] == gid]
        entry = {"product_group_id": gid, "product_name": metadata[gid]["product_name"], "vendor_name": metadata[gid]["vendor_name"], **{key: row[key] for key in ("ai_status", "ai_type", "evidence_strength", "forced_decision", "ai_type_evidence_strength", "ai_type_forced_decision")}, "trusted_binary_eligible": binary_ok, "trusted_subtype_eligible": subtype_ok, "parent_acceptance_hold": hold or "", "parent_hold_disposition": user_decision["parent_hold_disposition"] if user_decision else ("active" if hold else "none"), "user_review_disposition": user_decision["disposition"] if user_decision else "not reviewed", "review_reference": f"product_ai_review.jsonl#{gid}"}
        labels.append(entry)
        source_captures = {}
        for judgment in histories[gid].values():
            for source in judgment["sources"]:
                if source["source_type"] == "source_dataset":
                    continue
                assert captures.get(source["url"]), f"missing actual source capture: {source['url']}"
                source_captures[source["url"]] = captures[source["url"]]
        ledger.append({"product_group_id": gid, "source_record_numbers": members, "user_review_decision": user_decision, "override_rationale": overrides[gid]["rationale"] if gid in overrides else None, "model": manifest["model"], "thinking": manifest["thinking"], "rubric_sha256": manifest["input_sha256"]["notebooks/enterprise_products/LABELING_WORKFLOW.md"], "input_sha256": manifest["input_sha256"], "stages": histories[gid], "stage_artifacts": {stage: {"path": result["artifactPaths"][f"{stage}-{batch}"], "sha256": digest(Path(result["artifactPaths"][f"{stage}-{batch}"])), "run_id": stage_run_ids[f"{stage}-{batch}"], "prompt_sha256": children_by_id[stage_run_ids[f"{stage}-{batch}"]]["prompt_sha256"], "session": children_by_id[stage_run_ids[f"{stage}-{batch}"]]["session"]} for batch, ids in batches.items() if gid in ids for stage in histories[gid]}, "source_captures": source_captures, "accepted_annotation": entry, "user_review_record_reference": "../user_review_decisions.json" if user_decision else None, "parent_acceptance_reference": "../PARENT_ACCEPTANCE.md"})
        review_row = {**entry, "final_rationale": row["rationale"], "first_pass_summary": "Labeler: " + histories[gid]["labeler"]["ai_status"] + (" / " + str(histories[gid]["labeler"]["ai_type"]) if histories[gid]["labeler"]["ai_type"] else "") + "; blind: " + histories[gid]["blind"]["ai_status"] + (" / " + str(histories[gid]["blind"]["ai_type"]) if histories[gid]["blind"]["ai_type"] else ""), "sources": row["sources"], "review_reasons": " | ".join(([hold] if hold else []) + row["issues"]) or "Weak/forced judgment"}
        if user_decision:
            reviewed_page.append(review_row)
        if not binary_ok or (row["ai_status"] == "ai" and not subtype_ok):
            queue.append(review_row)
    report = {"scope": "Partial 20-group calibration only; not a full-dataset export", "groups": len(labels), "records": len(selected), "source_groups": manifest["source_groups"], "source_records": manifest["source_records"], "remaining_groups": manifest["source_groups"] - len(labels), "binary_distribution": dict(Counter(r["ai_status"] for r in labels)), "ai_type_distribution": dict(Counter(r["ai_type"] for r in labels if r["ai_type"])), "model_supported_binary": sum(r["evidence_strength"] == "supported" and not r["forced_decision"] for r in labels), "forced_binary": sum(r["forced_decision"] for r in labels), "forced_subtype": sum(bool(r["ai_type_forced_decision"]) for r in labels), "parent_binary_holds": len(HOLDS), "parent_holds_accepted_by_user": sum(gid in reviewed and gid in HOLDS and gid not in overrides for gid in finals), "user_reviewed_groups": len(reviewed), "user_override_groups": len(overrides), "trusted_binary_eligible": sum(r["trusted_binary_eligible"] for r in labels), "trusted_subtype_eligible": sum(r["trusted_subtype_eligible"] for r in labels), "review_queue_groups": len(queue), "adjudicated_groups": sum("adjudicator" in h for h in histories.values()), "binary_disagreements": sum(h["labeler"]["ai_status"] != h["blind"]["ai_status"] for h in histories.values()), "subtype_disagreements": sum(h["labeler"]["ai_status"] == h["blind"]["ai_status"] == "ai" and h["labeler"]["ai_type"] != h["blind"]["ai_type"] for h in histories.values()), "structural_blockers": [], "resources": resources, "source_head": manifest["head"], "pinned_rubric_sha256": manifest["input_sha256"]["notebooks/enterprise_products/LABELING_WORKFLOW.md"], "current_rubric_sha256": digest(repo / "notebooks/enterprise_products/LABELING_WORKFLOW.md"), "live_input_drift": live_input_drift, "model": manifest["model"], "thinking": manifest["thinking"], "input_sha256": manifest["input_sha256"], "verification_continuation_elapsed_minutes": (completed["endedAt"] - completed["startedAt"]) / 60000, "projection_caveat": "Recovery overhead, cached tokens, evidence holds and the deliberately diverse 20-group sample make a full-run cost/duration forecast unreliable; no invoice-based budget established.", "protocol_notes": "See ../PARENT_ACCEPTANCE.md and ../handoffs/resource_audit.json; initial four-round waivers retained, later mixed-group search disclosed, counters in model ledgers are not necessarily new-stage usage.", "next_action": "Pause for explicit user approval before remaining groups; never silently change evidence/time/inclusion rules."}
    out = ROOT / "exports"
    out.mkdir(exist_ok=True)
    fields = list(labels[0])
    write_csv(out / "product_ai_labels.csv", labels, fields)
    propagated = [{"source_record_number": r["source_record_number"], **next(item for item in labels if item["product_group_id"] == r["product_group_id"])} for r in selected]
    assert len({r["source_record_number"] for r in propagated}) == len(propagated)
    write_csv(out / "product_ai_record_labels.csv", propagated, ["source_record_number", *fields])
    write_csv(out / "product_ai_review_queue.csv", queue, [*fields, "final_rationale", "first_pass_summary", "sources", "review_reasons"])
    render_flagged_html(out, reviewed_page, ledger)
    (out / "product_ai_review.jsonl").write_text("".join(json.dumps(entry, ensure_ascii=False) + "\n" for entry in ledger))
    (out / "product_ai_labeling_report.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({key: value for key, value in report.items() if key not in ("resources", "input_sha256")}, indent=2))
    print("Child reported tokens:", resources["reported_tokens"], "reported telemetry USD:", resources["reported_cost_usd"])


def self_test():
    row = {"evidence_strength": "supported", "forced_decision": False, "ai_status": "ai", "ai_type_evidence_strength": "supported", "ai_type_forced_decision": False}
    assert eligible(row) == (True, True)
    assert eligible(row, "parent hold") == (False, False)
    assert eligible({**row, "evidence_strength": "weak", "forced_decision": True}) == (False, False)
    assert eligible({**row, "ai_type_forced_decision": True}) == (True, False)
    assert eligible({**row, "ai_status": "non_ai"}) == (True, False)
    assert eligible({**row, "evidence_strength": "weak", "forced_decision": True, "ai_type_evidence_strength": "weak", "ai_type_forced_decision": True}) == (False, False)
    print("Trusted-use self-check: six cases passed, including user override preserving evidence exclusions. Export also asserts pinned inputs, exact stage coverage, deterministic resume and unique record propagation.")


if __name__ == "__main__":
    self_test() if sys.argv[1:] == ["--self-test"] else export()
