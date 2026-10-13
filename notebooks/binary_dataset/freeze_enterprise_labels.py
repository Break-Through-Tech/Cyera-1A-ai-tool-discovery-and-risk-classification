"""Freeze accepted enterprise v3 annotations from the pinned Git source cutoff."""
import argparse
import csv
import hashlib
import io
import json
import subprocess
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CUTOFF = "28a32b79f8f4c7ab000e2e66ba7fd21202d3dd44"
RUBRIC = "enterprise-description-only-v3"
CLEANED = "data/technology-product-categorization/products_cleaned.csv"
RUNS = "notebooks/enterprise_products/labeling_runs"
OUT = ROOT / "data/binary_ai_dataset/v1"
RECORD_FIELDS = ("source_record_number", "product_group_id", "product_name", "vendor_name",
                 "taxonomy_category", "taxonomy_sub_category", "product_description")
LABEL_FIELDS = ("annotation_id", "description_sha256", "ai_status", "ai_type", "evidence_strength",
                "forced_decision", "ai_type_evidence_strength", "ai_type_forced_decision", "rationale",
                "ai_type_rationale", "evidence_spans", "ai_type_evidence_spans")


def sha(data):
    return hashlib.sha256(data).hexdigest()


def git_file(path, cutoff=CUTOFF):
    try:
        return subprocess.check_output(["git", "show", f"{cutoff}:{path}"], cwd=ROOT)
    except subprocess.CalledProcessError as exc:
        raise ValueError(f"missing pinned source artifact {path}") from exc


def json_bytes(data, path):
    try:
        return json.loads(data)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid JSON artifact: {path}") from exc


def csv_rows(data, path):
    reader = csv.DictReader(io.StringIO(data.decode("utf-8"), newline=""))
    if tuple(reader.fieldnames or ()) != RECORD_FIELDS:
        raise ValueError(f"cleaned source schema mismatch: {path}")
    return list(reader)


def accepted_exports(cutoff=CUTOFF):
    paths = subprocess.check_output(["git", "ls-tree", "-r", "--name-only", cutoff, RUNS], cwd=ROOT, text=True).splitlines()
    exports = sorted(p for p in paths if p.endswith("/description_labels.json"))
    accepted = []
    for path in exports:
        base = path.removesuffix("description_labels.json")
        record_path = base + "record_labels.json"
        validation_path = base + "FINAL_VALIDATION.json"
        parent_path = base + "PARENT_ACCEPTANCE.json"
        if record_path not in paths or (validation_path not in paths and parent_path not in paths):
            continue
        validation = json_bytes(git_file(validation_path, cutoff), validation_path) if validation_path in paths else {}
        parent = json_bytes(git_file(parent_path, cutoff), parent_path) if parent_path in paths else {}
        for receipt_path, receipt in ((validation_path, validation), (parent_path, parent)):
            if not receipt_path or not receipt:
                continue
            for field in ("files", "export_hashes", "run_file_sha256"):
                for relpath, expected_hash in receipt.get(field, {}).items():
                    artifact = f"{base}{relpath}"
                    if artifact not in paths or sha(git_file(artifact, cutoff)) != expected_hash:
                        raise ValueError(f"acceptance {field} hash mismatch: {artifact}")
        manifest_path = f"{base}manifest.json"
        if manifest_path not in paths:
            raise ValueError(f"accepted export manifest missing: {manifest_path}")
        manifest = json_bytes(git_file(manifest_path, cutoff), manifest_path)
        registered = manifest.get("exports", {})
        if not {"description_labels.json", "record_labels.json"} <= set(registered):
            raise ValueError(f"accepted exports are not registered in {manifest_path}")
        for relpath, expected_hash in registered.items():
            artifact = f"{base}{relpath}"
            if artifact not in paths or sha(git_file(artifact, cutoff)) != expected_hash:
                raise ValueError(f"manifest export hash mismatch: {artifact}")
        status = validation.get("status", "")
        parent_ok = (parent.get("accepted") is True or parent.get("status") in {"finalized", "finalized_with_documented_hash_receipt_timing_deviation"}
                     or isinstance(parent.get("report"), dict))
        if status not in {"passed", "accepted calibration; stopped for approval"} and not parent_ok:
            continue
        if not parent_ok:
            raise ValueError(f"export lacks parent acceptance: {parent_path}")
        if status and status not in {"passed", "accepted calibration; stopped for approval"}:
            raise ValueError(f"export validation not accepted: {validation_path}: {status}")
        accepted.append((base, path, record_path, validation_path if validation_path in paths else None,
                         parent_path if parent_path in paths else None, paths))
    return accepted


def _label_valid(label, text):
    if not isinstance(label, dict):
        raise ValueError("annotation must be a JSON object")
    required = set(LABEL_FIELDS)
    if set(label) not in (required, required | {"product_description"}):
        raise ValueError("annotation fields differ from the finalized v3 schema")
    if not isinstance(label["annotation_id"], str) or not label["annotation_id"].strip():
        raise ValueError("annotation_id must be a nonempty string")
    if not isinstance(label["description_sha256"], str) or label["description_sha256"] != sha(text.encode("utf-8")):
        raise ValueError("description hash does not match exact source text")
    if label.get("product_description", text) != text:
        raise ValueError("exported description differs from source")
    if (not isinstance(label["ai_status"], str) or label["ai_status"] not in {"ai", "non_ai"}
            or not isinstance(label["evidence_strength"], str) or label["evidence_strength"] not in {"supported", "weak"}):
        raise ValueError("invalid binary annotation")
    if type(label["forced_decision"]) is not bool or label["forced_decision"] != (label["evidence_strength"] == "weak"):
        raise ValueError("binary weak/forced flags disagree")
    _nonblank(label["rationale"], "rationale")
    _quotes(label["evidence_spans"], text, "evidence_spans")
    if label["ai_status"] == "non_ai":
        if any(label[k] is not None for k in ("ai_type", "ai_type_evidence_strength", "ai_type_forced_decision", "ai_type_rationale", "ai_type_evidence_spans")):
            raise ValueError("non-AI subtype metadata must be null")
    else:
        if (not isinstance(label["ai_type"], str) or label["ai_type"] not in {"ai_native", "ai_enabled"}
                or not isinstance(label["ai_type_evidence_strength"], str)
                or label["ai_type_evidence_strength"] not in {"supported", "weak"}):
            raise ValueError("AI label has invalid subtype metadata")
        if type(label["ai_type_forced_decision"]) is not bool or label["ai_type_forced_decision"] != (label["ai_type_evidence_strength"] == "weak"):
            raise ValueError("subtype weak/forced flags disagree")
        _nonblank(label["ai_type_rationale"], "ai_type_rationale")
        _quotes(label["ai_type_evidence_spans"], text, "ai_type_evidence_spans")


def _nonblank(value, field):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a nonempty string")


def _quotes(spans, text, field):
    if not isinstance(spans, list) or not spans or any(not isinstance(span, str) or not span.strip() for span in spans):
        raise ValueError(f"{field} must be a nonempty list of strings")
    if any(span not in text for span in spans):
        raise ValueError(f"{field} quotation is not an exact source substring")


def _same_annotation(left, right):
    """Compare all persisted annotation fields except the batch-specific annotation ID."""
    return ({key: value for key, value in left.items() if key != "annotation_id"}
            == {key: value for key, value in right.items() if key != "annotation_id"})


def build_freeze(cutoff=CUTOFF):
    source = git_file(CLEANED, cutoff)
    rows = csv_rows(source, CLEANED)
    by_id = {r["source_record_number"]: r for r in rows}
    if len(by_id) != len(rows):
        raise ValueError("duplicate source record number in cleaned input")
    texts = defaultdict(list)
    for row in rows:
        texts[row["product_description"]].append(row)
    by_hash = {}
    for text in texts:
        digest = sha(text.encode("utf-8"))
        if digest in by_hash and by_hash[digest] != text:
            raise ValueError("SHA-256 collision for unequal descriptions")
        by_hash[digest] = text

    annotations, record_rows, refs = {}, {}, {}
    duplicate_exports = 0
    provenance = []
    for base, label_path, record_path, validation_path, parent_path, paths in accepted_exports(cutoff):
        receipt_path = parent_path or validation_path
        label_bytes, record_bytes = git_file(label_path, cutoff), git_file(record_path, cutoff)
        labels = json_bytes(label_bytes, label_path)
        joined = json_bytes(record_bytes, record_path)
        if not isinstance(labels, list) or not isinstance(joined, list):
            raise ValueError(f"expected annotation arrays: {base}")
        batch_labels = {}
        for label in labels:
            aid = label.get("annotation_id")
            digest = label.get("description_sha256")
            text = by_hash.get(digest)
            if not aid or text is None:
                raise ValueError(f"unknown annotation ID or source description in {label_path}")
            _label_valid(label, text)
            if label.get("product_description", text) != text:
                raise ValueError("label text differs from cleaned source")
            if digest in annotations:
                previous = annotations[digest]
                if not _same_annotation(previous, label):
                    raise ValueError(f"conflicting finalized annotations: {digest}")
                duplicate_exports += 1
                continue
            batch_labels[aid] = (digest, label)
            annotations[digest] = label
            refs[digest] = {"label_export": label_path, "record_export": record_path,
                            "acceptance_receipt": receipt_path, "label_sha256": sha(json.dumps(label, ensure_ascii=False, sort_keys=True).encode()),
                            "label_file_sha256": sha(label_bytes), "record_file_sha256": sha(record_bytes)}
        seen_in_batch = set()
        for item in joined:
            ref = str(item.get("source_record_number", ""))
            aid = item.get("annotation_id")
            if aid not in batch_labels or ref not in by_id or ref in seen_in_batch:
                raise ValueError(f"invalid record-label mapping in {record_path}: {ref}")
            seen_in_batch.add(ref)
            digest, label = batch_labels[aid]
            source_row = by_id[ref]
            if source_row["product_description"] != by_hash[digest] or item.get("description_sha256") != digest:
                raise ValueError(f"record mapping text/hash mismatch: {record_path}: {ref}")
            if any(item.get(k) != source_row[k] for k in ("source_record_number", "product_group_id", "product_description")):
                raise ValueError(f"record mapping provenance mismatch: {record_path}: {ref}")
            if ref in record_rows:
                raise ValueError(f"source record labeled in multiple exports: {ref}")
            record_rows[ref] = {**source_row, **{k: label.get(k) for k in LABEL_FIELDS},
                                "trusted_eligible": label["evidence_strength"] == "supported",
                                "exclusion_reason": "" if label["evidence_strength"] == "supported" else "binary_weak_or_forced",
                                "provenance_label_export": label_path}
        if seen_in_batch != {str(x.get("source_record_number")) for x in joined}:
            raise ValueError(f"duplicate rows in record export: {record_path}")
        batch_digests = {digest for digest, _ in batch_labels.values()}
        expected_batch_refs = {ref for ref, row in by_id.items()
                               if sha(row["product_description"].encode("utf-8")) in batch_digests}
        if seen_in_batch != expected_batch_refs:
            raise ValueError(f"finalized description-to-source-row coverage mismatch: {record_path}")
        receipt_path = parent_path or validation_path
        receipt_bytes = git_file(receipt_path, cutoff)
        receipt = json_bytes(receipt_bytes, receipt_path)
        acceptance = receipt.get("acceptance", {})
        pinned_keys = ("batch_id", "timestamp", "models", "model", "actual_model", "requested_models",
                       "rubric_id", "rubric_sha256", "prompt_hashes", "workflow_run_id")
        run_root = base.split("/batches/")[0].split("/lanes/")[0].rstrip("/")
        if "/lanes/" in base:
            run_root = base.split("/lanes/")[0]
        references = []
        model_records = []
        candidate_dirs = [base.rstrip("/")]
        parent_dir = Path(base.rstrip("/")).parent
        while str(parent_dir) != "." and str(parent_dir).startswith(RUNS):
            candidate_dirs.append(str(parent_dir))
            if str(parent_dir) == run_root:
                break
            parent_dir = parent_dir.parent
        for directory in dict.fromkeys(candidate_dirs):
            for name in ("manifest.json", "PREPARATION_RECEIPT.json", "DUAL_ACCOUNT_PLAN.json"):
                candidate = f"{directory}/{name}"
                if candidate not in paths:
                    continue
                data = git_file(candidate, cutoff)
                references.append({"path": candidate, "sha256": sha(data)})
                parsed = json_bytes(data, candidate)
                stages = parsed.get("stages", {})
                if stages:
                    model_records.extend({"stage": stage, "model_id": info.get("model_id"),
                                          "receipt": candidate} for stage, info in stages.items())
                for key in ("models", "model", "actual_model", "requested_models", "rubric_id", "rubric_sha256"):
                    if parsed.get(key) is not None:
                        model_records.append({key: parsed[key], "receipt": candidate})
        for candidate in paths:
            if candidate.startswith(run_root + "/runtime/") and candidate.rsplit("/", 1)[-1] in {
                    "CURSOR_ONLY_RESUME_RECEIPT.json", "OVERNIGHT_BOTH_LANES_AUTHORIZATION.json"}:
                data = git_file(candidate, cutoff)
                references.append({"path": candidate, "sha256": sha(data)})
        for candidate in (validation_path, parent_path):
            if candidate and all(x["path"] != candidate for x in references):
                references.append({"path": candidate, "sha256": sha(git_file(candidate, cutoff))})
        provenance.append({"label_export": label_path, "record_export": record_path,
                           "acceptance_receipt": receipt_path, "model_rubric_provenance": model_records,
                           "reproduction_references": references,
                           "description_count": len(labels), "row_count": len(joined),
                           "label_sha256": sha(label_bytes), "record_sha256": sha(record_bytes),
                           "receipt_sha256": sha(receipt_bytes)})

    expected_record_refs = {ref for ref, row in by_id.items()
                             if sha(row["product_description"].encode("utf-8")) in annotations}
    if set(record_rows) != expected_record_refs:
        raise ValueError("finalized annotation rows do not exactly cover their source descriptions")

    supported_counts = Counter(x["ai_status"] for x in annotations.values() if x["evidence_strength"] == "supported")
    all_counts = Counter(x["ai_status"] for x in annotations.values())
    subtype_counts = Counter(x["ai_type"] or "null" for x in annotations.values())
    excluded = Counter(x["exclusion_reason"] for x in record_rows.values() if not x["trusted_eligible"])
    groups = {row["product_group_id"] for row in record_rows.values()}
    result = {
        "description_annotations": [{**label, "description_sha256": d, "product_description": by_hash[d],
                                          "trusted_eligible": label["evidence_strength"] == "supported",
                                          "exclusion_reason": "" if label["evidence_strength"] == "supported" else "binary_weak_or_forced",
                                          "provenance": refs[d]} for d, label in sorted(annotations.items())],
        "record_rows": [record_rows[x] for x in sorted(record_rows, key=int)],
        "provenance": provenance,
        "summary": {"source_cutoff": cutoff, "source_records": len(rows), "source_distinct_descriptions": len(texts),
                    "finalized_distinct_descriptions": len(annotations), "finalized_rows": len(record_rows),
                    "finalized_groups": len(groups), "unlabelled_distinct_descriptions": len(texts)-len(annotations),
                    "unlabelled_rows": len(rows)-len(record_rows), "binary_counts_including_weak": dict(all_counts),
                    "supported_binary_counts": dict(supported_counts), "subtype_counts_including_weak": dict(subtype_counts),
                    "weak_subtype_descriptions": sum(x["ai_type_evidence_strength"] == "weak" for x in annotations.values()),
                    "weak_or_forced_descriptions": sum(x["evidence_strength"] == "weak" for x in annotations.values()),
                    "weak_or_forced_rows": sum(not x["trusted_eligible"] for x in record_rows.values()),
                    "exclusion_counts": dict(excluded), "duplicate_exports_not_recounters": duplicate_exports,
                    "rubric_id": RUBRIC, "cleaned_input_sha256": sha(source),
                    "raw_source_sha256": sha(git_file("data/technology-product-categorization/products.csv", cutoff)),
                    "rubric_sha256": sha(git_file("notebooks/enterprise_products/LABELING_WORKFLOW.md", cutoff)),
                    "provenance": provenance}}
    return result


def write_freeze(out=OUT, cutoff=CUTOFF):
    out = Path(out)
    if out.is_symlink() or (out.exists() and not out.is_dir()):
        raise ValueError(f"output path cannot alias a file or symlink: {out}")
    if out.exists() and any(out.iterdir()):
        raise FileExistsError(f"refusing to overwrite generated dataset artifacts: {out}")
    result = build_freeze(cutoff)
    out.mkdir(parents=True, exist_ok=True)
    desc_path, rows_path = out / "enterprise_descriptions.json", out / "enterprise_records.csv"
    desc_path.write_text(json.dumps(result["description_annotations"], ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    fields = list(RECORD_FIELDS) + list(LABEL_FIELDS) + ["trusted_eligible", "exclusion_reason", "provenance_label_export"]
    with rows_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields, lineterminator="\n", extrasaction="ignore")
        writer.writeheader()
        for row in result["record_rows"]:
            writer.writerow({**row, "evidence_spans": json.dumps(row["evidence_spans"], ensure_ascii=False),
                             "ai_type_evidence_spans": json.dumps(row["ai_type_evidence_spans"], ensure_ascii=False)})
    manifest = {**result["summary"], "preparation_script_sha256": sha(Path(__file__).read_bytes()),
                "selection_policy_version": "accepted-v3-exports-1",
                "normalization_policy_version": "exact-cleaned-text-utf8-sha256-1",
                "deduplication_policy_version": "exact-description-sha256-1",
                "split_policy_version": None, "feature_policy": "description-only; metadata and labels are not features",
                "artifacts": {desc_path.name: sha(desc_path.read_bytes()), rows_path.name: sha(rows_path.read_bytes())}}
    (out / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["build"])
    parser.add_argument("--cutoff", default=CUTOFF)
    parser.add_argument("--out", type=Path, default=OUT)
    args = parser.parse_args()
    print(json.dumps(write_freeze(args.out, args.cutoff), indent=2))

if __name__ == "__main__":
    main()
