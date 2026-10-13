"""Small integrity helper for the enterprise-description-only-v3 calibration."""

import csv
import hashlib
import json
import secrets
import shutil
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
DEFAULT_INPUTS = {
    "raw": ROOT / "data/technology-product-categorization/products.csv",
    "cleaned": ROOT / "data/technology-product-categorization/products_cleaned.csv",
    "cleaning_report": ROOT / "data/technology-product-categorization/cleaning_report.json",
    "rubric": HERE / "LABELING_WORKFLOW.md",
}
RECORD_FIELDS = ("source_record_number", "product_group_id", "product_name", "vendor_name",
                 "taxonomy_category", "taxonomy_sub_category", "product_description")
FIELDS = ("annotation_id", "description_sha256", "ai_status", "ai_type", "evidence_strength",
          "forced_decision", "ai_type_evidence_strength", "ai_type_forced_decision", "rationale",
          "ai_type_rationale", "evidence_spans", "ai_type_evidence_spans")
LABEL_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "required": list(FIELDS),
    "properties": {
        "annotation_id": {"type": "string"}, "description_sha256": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
        "ai_status": {"enum": ["ai", "non_ai"]},
        "ai_type": {"type": ["string", "null"], "enum": ["ai_native", "ai_enabled", None]},
        "evidence_strength": {"enum": ["supported", "weak"]}, "forced_decision": {"type": "boolean"},
        "ai_type_evidence_strength": {"type": ["string", "null"], "enum": ["supported", "weak", None]},
        "ai_type_forced_decision": {"type": ["boolean", "null"]},
        "rationale": {"type": "string", "minLength": 1}, "ai_type_rationale": {"type": ["string", "null"]},
        "evidence_spans": {"type": "array", "items": {"type": "string", "minLength": 1}, "minItems": 1},
        "ai_type_evidence_spans": {"type": ["array", "null"], "items": {"type": "string", "minLength": 1}},
        "conflict_response": {"type": "string", "minLength": 1},
    },
}


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def file_hash(path):
    return sha256(Path(path).read_bytes())


def _json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def load_rows(path):
    with Path(path).open(encoding="utf-8", newline="") as stream:
        reader = csv.DictReader(stream)
        if tuple(reader.fieldnames or ()) != RECORD_FIELDS:
            raise ValueError("cleaned input fields differ from the pinned record schema")
        rows = list(reader)
    refs = [row["source_record_number"] for row in rows]
    if not all(refs) or len(refs) != len(set(refs)):
        raise ValueError("cleaned input has missing or duplicate source record references")
    return rows


def freeze_run(run_dir, inputs=None, expected=(1438, 1406, 1391)):
    """Freeze source artifacts to a new run; expected=None permits small test fixtures."""
    inputs = {**DEFAULT_INPUTS, **(inputs or {})}
    run_dir = Path(run_dir)
    if run_dir.exists():
        raise FileExistsError(f"run directory already exists: {run_dir}")
    files = {key: Path(value) for key, value in inputs.items()}
    if not {"raw", "cleaned", "cleaning_report", "rubric"}.issubset(files):
        raise ValueError("raw, cleaned, cleaning_report and rubric inputs are required")
    for name, path in files.items():
        if not path.is_file():
            raise FileNotFoundError(f"missing {name} input: {path}")
    prompt_hashes = {name.removeprefix("prompt_"): file_hash(path)
                     for name, path in files.items() if name.startswith("prompt_")}
    if not {"labeler", "blind"}.issubset(prompt_hashes):
        raise ValueError("freeze the independent labeler and blind prompts")
    raw_hash, cleaned_hash = file_hash(files["raw"]), file_hash(files["cleaned"])
    report = _json(files["cleaning_report"])
    if report.get("source", {}).get("sha256") != raw_hash:
        raise ValueError("cleaning report source hash does not match raw input")
    if report.get("output", {}).get("sha256") != cleaned_hash:
        raise ValueError("cleaning report output hash does not match cleaned input")
    rows = load_rows(files["cleaned"])
    groups = {row["product_group_id"] for row in rows}
    unique_texts = {row["product_description"] for row in rows}
    if report.get("retained_records") != len(rows):
        raise ValueError("cleaning report retained count does not match cleaned input")
    if report.get("retained_product_groups") != len(groups):
        raise ValueError("cleaning report product-group count does not match cleaned input")
    if report.get("input_records") != report.get("retained_records", 0) + report.get("excluded_records", 0):
        raise ValueError("cleaning report input/retained/excluded counts do not reconcile")
    if expected is not None and (len(rows), len(groups), len(unique_texts)) != tuple(expected):
        raise ValueError(f"unexpected retained/group/description counts: {len(rows)}/{len(groups)}/{len(unique_texts)}")
    run_dir.mkdir(parents=True)
    input_dir = run_dir / "inputs"
    input_dir.mkdir()
    artifacts = {}
    for name, path in files.items():
        dest = input_dir / f"{name}{path.suffix}"
        shutil.copyfile(path, dest)
        artifacts[name] = {"path": str(dest.relative_to(run_dir)), "sha256": file_hash(dest)}
    manifest = {
        "rubric_id": "enterprise-description-only-v3", "run_id": run_dir.name,
        "counts": {"source_input_records": report["input_records"],
                   "cleaner_excluded_records": report["excluded_records"],
                   "records": len(rows), "product_groups": len(groups), "distinct_descriptions": len(unique_texts)},
        "inputs": artifacts, "code_sha256": file_hash(Path(__file__)),
        "prompt_hashes": prompt_hashes,
        "stages": {},
    }
    (run_dir / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest


def _verified_manifest(run_dir):
    run_dir = Path(run_dir)
    manifest = _json(run_dir / "manifest.json")
    for category in ("prepared_artifacts", "selection_artifact"):
        for relpath, digest in manifest.get(category, {}).items():
            path = run_dir / relpath
            if not path.is_file() or file_hash(path) != digest:
                raise ValueError(f"{category.replace('_', ' ')} tampered: {relpath}")
    for name, entry in manifest["inputs"].items():
        path = run_dir / entry["path"]
        if not path.is_file() or file_hash(path) != entry["sha256"]:
            raise ValueError(f"immutable input tampered: {name}")
    for category in ("checkpoints", "exports"):
        for relpath, digest in manifest.get(category, {}).items():
            path = run_dir / relpath
            if not path.is_file() or file_hash(path) != digest:
                raise ValueError(f"{category[:-1]} tampered: {relpath}")
    if file_hash(Path(__file__)) != manifest["code_sha256"]:
        raise ValueError("helper code differs from pinned code hash")
    return manifest


def prepare_packets(run_dir):
    """Create description-only packets and parent-only full row join map."""
    run_dir = Path(run_dir)
    manifest = _verified_manifest(run_dir)
    packet_path, join_path = run_dir / "description_packets.json", run_dir / "parent_join_map.json"
    prepared = manifest.get("prepared_artifacts", {})
    if prepared:
        expected = {"description_packets.json", "parent_join_map.json"}
        if set(prepared) != expected:
            raise ValueError("prepared artifacts registration is incomplete")
        return _json(packet_path), _json(join_path)
    if packet_path.exists() or join_path.exists():
        raise ValueError("unregistered prepared artifacts exist; refusing to replace them")
    rows = load_rows(run_dir / manifest["inputs"]["cleaned"]["path"])
    by_digest = {}
    for row in rows:
        text = row["product_description"]
        digest = sha256(text.encode("utf-8"))
        if digest in by_digest and by_digest[digest]["description"] != text:
            raise ValueError("SHA-256 collision between unequal descriptions")
        if digest not in by_digest:
            by_digest[digest] = {"annotation_id": "ann_" + secrets.token_hex(12),
                                 "description_sha256": digest, "description": text,
                                 "source_record_references": []}
        by_digest[digest]["source_record_references"].append(row["source_record_number"])
    packets = sorted(by_digest.values(), key=lambda x: x["annotation_id"])
    # references are permitted packet provenance; no other row columns leave this join map.
    join_map = [{"annotation_id": item["annotation_id"], "description_sha256": item["description_sha256"],
                 "source_record_references": item["source_record_references"],
                 "rows": [row for row in rows if row["source_record_number"] in item["source_record_references"]]}
                for item in packets]
    _write_json(run_dir / "description_packets.json", packets)
    _write_json(run_dir / "parent_join_map.json", join_map)
    manifest["prepared_artifacts"] = {name: file_hash(run_dir / name)
                                      for name in ("description_packets.json", "parent_join_map.json")}
    (run_dir / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return packets, join_map


def select_descriptions(run_dir, selections, expected=20):
    """Persist the parent's explicit calibration selection; never choose examples heuristically."""
    run_dir = Path(run_dir)
    manifest = _verified_manifest(run_dir)
    if (run_dir / "selection.json").exists():
        raise ValueError("selection is immutable once written")
    packets = _json(run_dir / "description_packets.json")
    by_id = {p["annotation_id"]: p for p in packets}
    chosen = [item["annotation_id"] for item in selections]
    if len(chosen) != len(set(chosen)) or not set(chosen) <= set(by_id):
        raise ValueError("selection contains duplicate or unknown annotation IDs")
    if expected is not None and len(chosen) != expected:
        raise ValueError(f"expected {expected} selected descriptions, got {len(chosen)}")
    for item in selections:
        if set(item["source_record_references"]) != set(by_id[item["annotation_id"]]["source_record_references"]):
            raise ValueError("selection source references must cover the exact-text description group")
    selected = {"annotation_ids": chosen,
                "source_record_references": sorted(ref for item in selections for ref in item["source_record_references"])}
    _write_json(run_dir / "selection.json", selected)
    manifest["selection_artifact"] = {"selection.json": file_hash(run_dir / "selection.json")}
    (run_dir / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return selected


def _stage_prompt_hash(manifest, stage):
    prompts = manifest["prompt_hashes"]
    role = "blind" if stage == "reconciliation" and stage not in prompts else stage
    return prompts.get(role)


def assign_stage(run_dir, stage, annotation_ids, prompt_hash, model_id, batch_id):
    """Bind exact assigned IDs and provenance before an agent is invoked."""
    if stage not in {"labeler", "blind", "reconciliation"}:
        raise ValueError("invalid stage")
    run_dir = Path(run_dir)
    manifest = _verified_manifest(run_dir)
    packets = _json(run_dir / "description_packets.json")
    ids = [p["annotation_id"] for p in packets]
    selection_path = run_dir / "selection.json"
    if not selection_path.is_file():
        raise ValueError("parent must persist explicit selection before stage assignment")
    selected_ids = set(_json(selection_path)["annotation_ids"])
    if stage in {"labeler", "blind"} and set(annotation_ids) != selected_ids:
        raise ValueError("independent stage assignment must exactly cover selected descriptions")
    if prompt_hash != _stage_prompt_hash(manifest, stage):
        raise ValueError("stage prompt hash does not match its frozen role prompt")
    if not model_id or not batch_id:
        raise ValueError("model_id and batch_id provenance are required")
    if len(annotation_ids) != len(set(annotation_ids)) or not set(annotation_ids) <= set(ids):
        raise ValueError("assignment has duplicate or unknown annotation IDs")
    if stage == "reconciliation" and not annotation_ids:
        raise ValueError("reconciliation assignment cannot be empty")
    receipt = {"stage": stage, "run_id": manifest["run_id"], "batch_id": batch_id,
               "rubric_id": manifest["rubric_id"], "rubric_sha256": manifest["inputs"]["rubric"]["sha256"],
               "prompt_sha256": prompt_hash, "model_id": model_id,
               "assigned_annotation_ids": list(annotation_ids)}
    stages = manifest["stages"]
    if stage in stages:
        raise ValueError(f"stage already assigned: {stage}")
    stages[stage] = receipt
    (run_dir / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return receipt


def validate_handoff(records, packets, assigned_ids, stage):
    expected = set(assigned_ids)
    ids = [item.get("annotation_id") for item in records]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate annotation IDs")
    if set(ids) != expected:
        raise ValueError(f"handoff coverage mismatch; missing={sorted(expected-set(ids))}, extra={sorted(set(ids)-expected)}")
    known = {item["annotation_id"]: item for item in packets}
    for item in records:
        aid = item["annotation_id"]
        if aid not in known:
            raise ValueError(f"unknown annotation ID: {aid}")
        if set(item) - set(LABEL_SCHEMA["properties"]):
            raise ValueError("unexpected output fields")
        if any(field not in item for field in FIELDS):
            raise ValueError(f"missing output field for {aid}")
        source = known[aid]
        if item["description_sha256"] != source["description_sha256"]:
            raise ValueError(f"description hash mismatch for {aid}")
        if type(item["forced_decision"]) is not bool:
            raise ValueError("forced_decision must be a JSON boolean")
        if item["evidence_strength"] not in {"supported", "weak"} or item["forced_decision"] != (item["evidence_strength"] == "weak"):
            raise ValueError("binary weak/forced flags are inconsistent")
        if item["ai_status"] not in {"ai", "non_ai"}:
            raise ValueError("invalid ai_status")
        _nonblank(item["rationale"], "rationale")
        _quotes(item["evidence_spans"], source["description"], "evidence_spans")
        if item["ai_status"] == "non_ai":
            if any(item[f] is not None for f in ("ai_type", "ai_type_evidence_strength", "ai_type_forced_decision", "ai_type_rationale", "ai_type_evidence_spans")):
                raise ValueError("non_ai subtype fields must be null")
        else:
            if item["ai_type"] not in {"ai_native", "ai_enabled"}:
                raise ValueError("ai labels require an applicable subtype")
            if item["ai_type_evidence_strength"] not in {"supported", "weak"}:
                raise ValueError("invalid subtype evidence strength")
            if type(item["ai_type_forced_decision"]) is not bool or item["ai_type_forced_decision"] != (item["ai_type_evidence_strength"] == "weak"):
                raise ValueError("subtype weak/forced flags are inconsistent")
            _nonblank(item["ai_type_rationale"], "ai_type_rationale")
            _quotes(item["ai_type_evidence_spans"], source["description"], "ai_type_evidence_spans")
        if stage == "reconciliation":
            _nonblank(item.get("conflict_response"), "conflict_response")
        elif "conflict_response" in item:
            raise ValueError("conflict_response is only valid for reconciliation")
    return records


def _nonblank(value, field):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a nonempty string")


def _quotes(spans, text, field):
    if not isinstance(spans, list) or not spans:
        raise ValueError(f"{field} must contain at least one quotation")
    for quote in spans:
        if not isinstance(quote, str) or not quote.strip() or quote not in text:
            raise ValueError(f"{field} contains blank or non-exact quotation")


def save_checkpoint(run_dir, stage, annotation_id, record):
    """Write one validated result using exclusive creation for resume-safe checkpointing."""
    run_dir = Path(run_dir)
    manifest = _verified_manifest(run_dir)
    receipt = manifest["stages"].get(stage)
    if not receipt or annotation_id not in receipt["assigned_annotation_ids"]:
        raise ValueError("checkpoint is outside the assigned stage")
    packets = _json(run_dir / "description_packets.json")
    validate_handoff([record], packets, [annotation_id], stage)
    folder = run_dir / "stages" / stage
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{annotation_id}.json"
    with path.open("x", encoding="utf-8") as stream:
        json.dump(record, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    manifest.setdefault("checkpoints", {})[str(path.relative_to(run_dir))] = file_hash(path)
    (run_dir / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return path


def load_stage(run_dir, stage):
    run_dir = Path(run_dir)
    manifest = _verified_manifest(run_dir)
    receipt = manifest["stages"].get(stage)
    if not receipt:
        raise ValueError(f"missing stage receipt: {stage}")
    folder = run_dir / "stages" / stage
    actual = {str(path.relative_to(run_dir)) for path in folder.rglob("*.json")} if folder.exists() else set()
    registered = {path for path in manifest.get("checkpoints", {})
                  if Path(path).parent == Path("stages") / stage and Path(path).suffix == ".json"}
    if actual != registered:
        raise ValueError(f"unregistered checkpoint in {stage} stage")
    records = [json.loads((run_dir / path).read_text(encoding="utf-8")) for path in sorted(registered)]
    packets = _json(run_dir / "description_packets.json")
    validate_handoff(records, packets, receipt["assigned_annotation_ids"], stage)
    return records


def compare(labeler, blind, reconciliation_ids=()):
    """Return reconciliation routes; structural defects are errors, not fallback labels."""
    routed = set(reconciliation_ids)
    lmap, bmap = ({r["annotation_id"]: r for r in rs} for rs in (labeler, blind))
    if set(lmap) != set(bmap):
        raise ValueError("labeler/blind coverage differs")
    for aid in lmap:
        a, b = lmap[aid], bmap[aid]
        if a["description_sha256"] != b["description_sha256"]:
            raise ValueError(f"independent description hash mismatch: {aid}")
        if (a["ai_status"] != b["ai_status"] or a["ai_type"] != b["ai_type"] or
            a["evidence_strength"] == "weak" or b["evidence_strength"] == "weak" or
            a["forced_decision"] or b["forced_decision"] or
            a["ai_type_evidence_strength"] == "weak" or b["ai_type_evidence_strength"] == "weak" or
            a["ai_type_forced_decision"] is True or b["ai_type_forced_decision"] is True):
            routed.add(aid)
    if routed - set(lmap):
        raise ValueError("reconciliation contains unknown IDs")
    return sorted(routed)


def _validate_stage_receipt(manifest, stage):
    receipt = manifest["stages"].get(stage)
    if (not receipt or receipt.get("stage") != stage or
            receipt.get("run_id") != manifest["run_id"] or receipt.get("rubric_id") != manifest["rubric_id"] or
            receipt.get("rubric_sha256") != manifest["inputs"]["rubric"]["sha256"] or
            receipt.get("prompt_sha256") != _stage_prompt_hash(manifest, stage) or
            not receipt.get("model_id") or not receipt.get("batch_id")):
        raise ValueError(f"invalid {stage} provenance receipt")
    return receipt


def finalize_run(run_dir, reconciliation_ids):
    """Finalize after reconciliation for every mechanically required or parent-routed ID."""
    run_dir = Path(run_dir)
    manifest = _verified_manifest(run_dir)
    if manifest.get("exports"):
        raise ValueError("finalized exports are immutable")
    all_packets = _json(run_dir / "description_packets.json")
    selection = _json(run_dir / "selection.json")
    all_ids = set(selection["annotation_ids"])
    packets = [p for p in all_packets if p["annotation_id"] in all_ids]
    if set(manifest["stages"].get("labeler", {}).get("assigned_annotation_ids", [])) != all_ids:
        raise ValueError("labeler assignment must cover selected descriptions")
    if set(manifest["stages"].get("blind", {}).get("assigned_annotation_ids", [])) != all_ids:
        raise ValueError("blind assignment must cover selected descriptions")
    for stage in ("labeler", "blind"):
        receipt = _validate_stage_receipt(manifest, stage)
        if set(receipt["assigned_annotation_ids"]) != all_ids:
            raise ValueError(f"{stage} assignment must cover selected descriptions")
    labeler, blind = load_stage(run_dir, "labeler"), load_stage(run_dir, "blind")
    required_route = compare(labeler, blind)
    parent_route = list(reconciliation_ids)
    if len(parent_route) != len(set(parent_route)):
        raise ValueError("reconciliation routing contains duplicate IDs")
    if set(parent_route) - all_ids:
        raise ValueError("reconciliation routing contains unknown IDs")
    if not set(required_route) <= set(parent_route):
        raise ValueError(f"parent reconciliation routing cannot omit required IDs: {required_route}")
    routed_ids = sorted(parent_route)
    if routed_ids:
        receipt = _validate_stage_receipt(manifest, "reconciliation")
        reconciliation = load_stage(run_dir, "reconciliation")
        if set(receipt["assigned_annotation_ids"]) != set(routed_ids):
            raise ValueError("reconciliation assignment differs from parent routing")
        final_map = {r["annotation_id"]: r for r in reconciliation}
    else:
        if "reconciliation" in manifest["stages"]:
            raise ValueError("reconciliation routing mismatch: unexpected reconciliation stage")
        final_map = {}
    lmap, bmap = ({r["annotation_id"]: r for r in rs} for rs in (labeler, blind))
    for packet in packets:
        aid = packet["annotation_id"]
        final_map.setdefault(aid, lmap[aid])
    join_map = [entry for entry in _json(run_dir / "parent_join_map.json") if entry["annotation_id"] in all_ids]
    descriptions = []
    records = []
    ledger = []
    review = []
    for p in packets:
        aid = p["annotation_id"]
        final = final_map[aid]
        descriptions.append({"product_description": p["description"], **{k: final[k] for k in FIELDS}})
        ledger.append({"annotation_id": aid, "description_sha256": p["description_sha256"],
                       "source_record_references": p["source_record_references"], "labeler": lmap[aid],
                       "blind": bmap[aid], "reconciliation": final if aid in routed_ids else None,
                       "final": final})
        if aid in routed_ids or final["evidence_strength"] == "weak" or final["forced_decision"] or final["ai_type_evidence_strength"] == "weak":
            review.append({"annotation_id": aid, "source_record_references": p["source_record_references"],
                           "binary_conflict": lmap[aid]["ai_status"] != bmap[aid]["ai_status"],
                           "subtype_conflict": lmap[aid]["ai_type"] != bmap[aid]["ai_type"],
                           "original_weak_or_forced": any(x["evidence_strength"] == "weak" or x["forced_decision"] or x["ai_type_evidence_strength"] == "weak" or x["ai_type_forced_decision"] is True for x in (lmap[aid], bmap[aid])),
                           "final_evidence_strength": final["evidence_strength"], "final_forced_decision": final["forced_decision"],
                           "final_ai_type_evidence_strength": final["ai_type_evidence_strength"],
                           "final_ai_type_forced_decision": final["ai_type_forced_decision"]})
    byid = {p["annotation_id"]: p for p in packets}
    for entry in join_map:
        result = final_map[entry["annotation_id"]]
        for row in entry["rows"]:
            if row["product_description"] != byid[entry["annotation_id"]]["description"]:
                raise ValueError("join map text differs from frozen description")
            records.append({"source_record_number": row["source_record_number"], "product_group_id": row["product_group_id"],
                            "product_description": row["product_description"], **{k: result[k] for k in FIELDS}})
    expected_refs = set(selection["source_record_references"])
    if set(r["source_record_number"] for r in records) != expected_refs or len(records) != len(expected_refs):
        raise ValueError("final selected-record coverage mismatch")
    _write_json(run_dir / "description_labels.json", descriptions)
    _write_json(run_dir / "record_labels.json", records)
    _write_json(run_dir / "review_ledger.json", ledger)
    _write_json(run_dir / "review_queue.json", review)
    candidates = [r for r in records if r["ai_status"] == "non_ai" and r["evidence_strength"] == "supported" and not r["forced_decision"]]
    _write_csv(run_dir / "non_ai_candidates.csv", candidates)
    original_differences = sum(lmap[aid]["ai_status"] != bmap[aid]["ai_status"] or
                               lmap[aid]["ai_type"] != bmap[aid]["ai_type"] for aid in all_ids)
    report = {"source_input_records": manifest["counts"]["source_input_records"],
              "cleaner_excluded_records": manifest["counts"]["cleaner_excluded_records"],
              "retained_source_records": manifest["counts"]["records"],
              "selected_descriptions": len(packets), "selected_records": len(records),
              "remaining_distinct_descriptions": manifest["counts"]["distinct_descriptions"] - len(packets),
              "remaining_source_records": manifest["counts"]["records"] - len(records),
              "coverage_claim": "selected calibration only; not full dataset coverage",
              "binary_counts": dict(Counter(r["ai_status"] for r in descriptions)),
              "subtype_counts": dict(Counter(r["ai_type"] for r in descriptions)),
              "binary_weak_count": sum(r["evidence_strength"] == "weak" for r in descriptions),
              "binary_forced_count": sum(r["forced_decision"] for r in descriptions),
              "subtype_weak_count": sum(r["ai_type_evidence_strength"] == "weak" for r in descriptions),
              "subtype_forced_count": sum(r["ai_type_forced_decision"] is True for r in descriptions),
              "trusted_negative_records": len(candidates), "reconciliation_count": len(routed_ids),
              "required_reconciliation_count": len(required_route),
              "parent_reconciliation_count": len(routed_ids),
              "independent_binary_or_subtype_differences": original_differences,
              "duplicate_records_within_selected_descriptions": len(records) - len(packets),
              "within_group_different_descriptions": _within_group_differences(
                  [{"product_group_id": r["product_group_id"], "product_description": r["product_description"]}
                   for r in records])}
    _write_json(run_dir / "calibration_report.json", report)
    manifest["exports"] = {name: file_hash(run_dir / name) for name in
                           ("description_labels.json", "record_labels.json", "review_ledger.json",
                            "review_queue.json", "non_ai_candidates.csv", "calibration_report.json")}
    (run_dir / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return report


def _within_group_differences(rows):
    groups = defaultdict(set)
    for row in rows:
        groups[row["product_group_id"]].add(row["product_description"])
    return sum(len(texts) > 1 for texts in groups.values())


def _write_json(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _write_csv(path, rows):
    fields = ("source_record_number", "product_group_id", "product_description", *FIELDS)
    with Path(path).open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
