"""Build binary-ai-v5: complete enterprise v3 labels plus AIToolBuzz, carrying v4 partitions forward."""
import argparse
import csv
import hashlib
import io
import json
import random
import shutil
import subprocess
from collections import Counter, defaultdict
from pathlib import Path

import freeze_enterprise_labels as freeze
import review_dataset_leakage as leakage
import split_unified_dataset as split
from build_unified_dataset import TOOLBUZZ, normalize_for_matching, read_toolbuzz

ROOT = freeze.ROOT
CUTOFF = "7f72140a7205525b01758f6b1e462c11893c9387"
RUNS = freeze.RUNS
DUAL_RUN = f"{RUNS}/description-v3-dual-account-20261012T193400Z"
RELEASE = f"{DUAL_RUN}/runtime/record-level-release-20261021"
# Batches whose semantic holds were resolved record-by-record in RELEASE.
HELD_BATCHES = {f"{DUAL_RUN}/lanes/cursor/batches/batch-025", f"{DUAL_RUN}/lanes/cursor/batches/batch-031",
                f"{DUAL_RUN}/lanes/codex/batches/batch-023", f"{DUAL_RUN}/lanes/codex/batches/batch-030"}
SUPERSEDING_SUFFIX = "-parent-integration"
ACCEPTED_STATUSES = {"passed", "accepted", "accepted calibration; stopped for approval", "finalized",
                     "finalized_with_documented_hash_receipt_timing_deviation", "finalized_parent_integration_copy"}
RECEIPTS = ("PARENT_ACCEPTANCE.json", "PARENT_VALIDATION.json", "FINAL_VALIDATION.json")
V1 = ROOT / "data/binary_ai_dataset/v1"
V2 = ROOT / "data/binary_ai_dataset/v2"
V4 = ROOT / "data/binary_ai_dataset/v4"
OUT = ROOT / "data/binary_ai_dataset/v5"
SEED = 20261022
POLICY_VERSION = "v4-carry-forward-then-whole-leakage-group-greedy-stratified-v1"
SELECTION_POLICY = "unified-v5: supported enterprise binary labels from all accepted v3 exports plus all nonblank AIToolBuzz Short Description rows labeled ai"


def sha(data):
    return hashlib.sha256(data).hexdigest()


def git_file(path, cutoff=CUTOFF):
    return freeze.git_file(path, cutoff)


def git_json(path, cutoff=CUTOFF):
    return freeze.json_bytes(git_file(path, cutoff), path)


def git_paths(cutoff=CUTOFF):
    return set(subprocess.check_output(["git", "ls-tree", "-r", "--name-only", cutoff, RUNS],
                                       cwd=ROOT, text=True).splitlines())


def receipt_accepts(receipt):
    if receipt.get("status") == "semantic_acceptance_hold":
        return False
    return (receipt.get("status") in ACCEPTED_STATUSES or receipt.get("accepted") is True
            or isinstance(receipt.get("report"), dict))


def select_exports(paths, cutoff=CUTOFF):
    """Return accepted batch export directories, preferring parent-integration copies over their originals."""
    dirs = sorted(p.removesuffix("/description_labels.json") for p in paths
                  if p.endswith("/description_labels.json") and "/runtime/" not in p and "/agents/" not in p)
    selected, skipped = [], []
    for base in dirs:
        if base + SUPERSEDING_SUFFIX in dirs:
            skipped.append({"export": base, "reason": f"superseded_by_{base}{SUPERSEDING_SUFFIX}"})
            continue
        if base in HELD_BATCHES:
            skipped.append({"export": base, "reason": "semantic_hold_resolved_by_record_level_release"})
            continue
        if f"{base}/record_labels.json" not in paths:
            raise ValueError(f"export missing record_labels.json: {base}")
        receipts = {name: git_json(f"{base}/{name}", cutoff) for name in RECEIPTS if f"{base}/{name}" in paths}
        if any(r.get("status") == "semantic_acceptance_hold" for r in receipts.values()):
            raise ValueError(f"export still on semantic hold: {base}")
        if not any(receipt_accepts(r) for r in receipts.values()):
            raise ValueError(f"export lacks an accepting receipt: {base}")
        selected.append((base, sorted(name for name, r in receipts.items() if receipt_accepts(r))))
    return selected, skipped


def collect_labels(by_hash, by_id, cutoff=CUTOFF):
    """Join every accepted annotation to its exact source rows; fail on conflicts or incomplete coverage."""
    paths = git_paths(cutoff)
    exports, skipped = select_exports(paths, cutoff)
    annotations, record_rows, provenance = {}, {}, []

    def add(digest, label, rows, source):
        text = by_hash.get(digest)
        if text is None:
            raise ValueError(f"unknown description hash in {source['label_export']}")
        label = {k: label[k] for k in freeze.LABEL_FIELDS}
        freeze._label_valid(label, text)
        if digest in annotations:
            if not freeze._same_annotation(annotations[digest][0], label):
                raise ValueError(f"conflicting accepted annotations: {digest}")
        else:
            annotations[digest] = (label, source)
        for row in rows:
            ref = str(row["source_record_number"])
            source_row = by_id.get(ref)
            if source_row is None or source_row["product_description"] != text or row["description_sha256"] != digest:
                raise ValueError(f"record mapping text/hash mismatch: {source['label_export']}: {ref}")
            if row["product_group_id"] != source_row["product_group_id"]:
                raise ValueError(f"record mapping product group mismatch: {ref}")
            if ref in record_rows and record_rows[ref] != digest:
                raise ValueError(f"source record labeled with two descriptions: {ref}")
            record_rows[ref] = digest

    for base, receipts in exports:
        label_path, record_path = f"{base}/description_labels.json", f"{base}/record_labels.json"
        label_bytes, record_bytes = git_file(label_path, cutoff), git_file(record_path, cutoff)
        labels, joined = freeze.json_bytes(label_bytes, label_path), freeze.json_bytes(record_bytes, record_path)
        rows_by_aid = defaultdict(list)
        for row in joined:
            rows_by_aid[row["annotation_id"]].append(row)
        if set(rows_by_aid) != {l["annotation_id"] for l in labels}:
            raise ValueError(f"record/annotation ID mismatch: {base}")
        source = {"label_export": label_path, "record_export": record_path,
                  "acceptance_receipts": [f"{base}/{r}" for r in receipts]}
        for label in labels:
            add(label["description_sha256"], label, rows_by_aid[label["annotation_id"]], source)
        provenance.append({**source, "description_count": len(labels), "row_count": len(joined),
                           "label_sha256": sha(label_bytes), "record_sha256": sha(record_bytes)})

    receipt = git_json(f"{RELEASE}/RELEASE_RECEIPT.json", cutoff)
    for name, expected in receipt["output_hashes"].items():
        if sha(git_file(f"{RELEASE}/{name}", cutoff)) != expected:
            raise ValueError(f"record-level release hash mismatch: {name}")
    released = git_json(f"{RELEASE}/released_record_labels.json", cutoff)
    quarantined = git_json(f"{RELEASE}/quarantined_records.json", cutoff)
    release_source = {"label_export": f"{RELEASE}/released_record_labels.json",
                      "record_export": f"{RELEASE}/released_record_labels.json",
                      "acceptance_receipts": [f"{RELEASE}/RELEASE_RECEIPT.json"]}
    released_by_hash = defaultdict(list)
    for row in released:
        released_by_hash[row["description_sha256"]].append(row)
    for digest, rows in released_by_hash.items():
        add(digest, rows[0], rows, release_source)
    provenance.append({**release_source, "description_count": len(released_by_hash), "row_count": len(released)})

    quarantined_hashes = {q["original_record"]["description_sha256"] for q in quarantined}
    if quarantined_hashes & set(annotations):
        raise ValueError("quarantined description also has an accepted label")
    if set(annotations) | quarantined_hashes != set(by_hash):
        missing = set(by_hash) - set(annotations) - quarantined_hashes
        raise ValueError(f"{len(missing)} source descriptions lack an accepted label or quarantine")
    expected_rows = {ref for ref, row in by_id.items() if sha(row["product_description"].encode()) in annotations}
    if set(record_rows) != expected_rows:
        raise ValueError("accepted labels do not exactly cover their source rows")
    return annotations, record_rows, quarantined, provenance, skipped


def enterprise_examples(annotations, record_rows, by_id):
    members = defaultdict(list)
    for ref, digest in record_rows.items():
        members[digest].append(by_id[ref])
    examples = []
    for digest, (label, source) in sorted(annotations.items()):
        if label["evidence_strength"] != "supported":
            continue
        rows = sorted(members[digest], key=lambda r: int(r["source_record_number"]))
        text = rows[0]["product_description"]
        examples.append({"example_id": f"enterprise-description:{digest}", "source": "enterprise",
                         "source_record_ids": [f"enterprise-row:{r['source_record_number']}" for r in rows],
                         "description_text": text, "description_sha256": digest,
                         "matching_normalized_text": normalize_for_matching(text), "label": label["ai_status"],
                         "metadata": {"annotation_id": label["annotation_id"], "source_records": [
                             {"source_record_number": r["source_record_number"], "product_group_id": r["product_group_id"],
                              "product_name": r["product_name"], "vendor_name": r["vendor_name"],
                              "taxonomy_category": r["taxonomy_category"],
                              "taxonomy_sub_category": r["taxonomy_sub_category"]} for r in rows],
                             "label_provenance": source}})
    return examples


def toolbuzz_examples(data):
    examples, excluded = [], 0
    for number, row in enumerate(read_toolbuzz(data), 1):
        text = row["Short Description"]
        if not text.strip():
            excluded += 1
            continue
        record_id = f"aitoolbuzz-row:{number:05d}"
        examples.append({"example_id": record_id, "source": "aitoolbuzz", "source_record_ids": [record_id],
                         "description_text": text, "description_sha256": sha(text.encode("utf-8")),
                         "matching_normalized_text": normalize_for_matching(text), "label": "ai",
                         "metadata": {"name": row["Name"], "link": row["Link"], "logo": row["Logo"],
                                      "category": row["Category"], "primary_task": row["Primary Task"],
                                      "keywords": row["Keywords"], "year_founded": row["Year Founded"],
                                      "country": row["Country"], "industry": row["industry"],
                                      "technologies": row["technologies"], "website": row["Website"],
                                      "website_status": row["Website Status"]}})
    return examples, excluded


def v4_member_partitions(v4=V4):
    manifest = json.loads((v4 / "manifest.json").read_bytes())
    for name, expected in manifest["output_sha256"].items():
        if sha((v4 / name).read_bytes()) != expected:
            raise ValueError(f"v4 artifact checksum mismatch: {name}")
    location = {}
    for partition in split.PARTITIONS:
        for row in json.loads((v4 / f"{partition}.metadata.json").read_bytes()):
            for member in row["member_example_ids"]:
                location[member] = partition
    return location, manifest


def carry_forward_assign(examples, v4_location, seed=SEED):
    """Keep every group that contains v4 members in its v4 partition; greedily place wholly new groups."""
    groups = defaultdict(list)
    for row in examples:
        groups[row["leakage_group_id"]].append(row)
    assigned = {name: [] for name in split.PARTITIONS}
    current = {name: Counter() for name in split.PARTITIONS}
    new_groups, bridging = [], []
    for group_id, rows in sorted(groups.items()):
        parts = {v4_location[m] for r in rows for m in r["metadata"]["member_example_ids"] if m in v4_location}
        if len(parts) > 1:
            bridging.append({"leakage_group_id": group_id, "v4_partitions": sorted(parts),
                             "example_ids": sorted(r["example_id"] for r in rows)})
        elif parts:
            partition = parts.pop()
            assigned[partition].extend(rows)
            current[partition].update(split._profile(rows))
        else:
            new_groups.append((group_id, rows))
    if bridging:
        raise ValueError(f"{len(bridging)} v5 leakage groups join v4 groups from different partitions: {bridging[:3]}")
    total = split._profile(examples)
    rng = random.Random(seed)
    rng.shuffle(new_groups)
    new_groups.sort(key=lambda item: -len(item[1]))
    for group_id, rows in new_groups:
        contribution = split._profile(rows)
        choices = []
        for partition in split.PARTITIONS:
            score = 0.0
            for key, amount in total.items():
                target = amount * split.RATIOS[partition]
                before = current[partition][key]
                after = before + contribution[key]
                score += ((after - target) ** 2 - (before - target) ** 2) / (max(amount, 1) ** 2)
            choices.append((score, split.PARTITIONS.index(partition), partition))
        partition = min(choices)[2]
        assigned[partition].extend(rows)
        current[partition].update(contribution)
    return {name: sorted(rows, key=lambda r: r["example_id"]) for name, rows in assigned.items()}


def is_new_in_v5(row, v4_location):
    return not any(m in v4_location for m in row["metadata"]["member_example_ids"])


def _json(value):
    return (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode()


def build(out=OUT, cutoff=CUTOFF):
    out = Path(out)
    if out.exists() or out.is_symlink():
        raise FileExistsError(f"refusing to overwrite existing output: {out}")

    cleaned = git_file(freeze.CLEANED, cutoff)
    v1_manifest = json.loads((V1 / "manifest.json").read_bytes())
    if sha(cleaned) != v1_manifest["cleaned_input_sha256"]:
        raise ValueError("cleaned enterprise input changed since v1")
    rows = freeze.csv_rows(cleaned, freeze.CLEANED)
    by_id = {r["source_record_number"]: r for r in rows}
    by_hash = {sha(r["product_description"].encode("utf-8")): r["product_description"] for r in rows}
    annotations, record_rows, quarantined, provenance, skipped = collect_labels(by_hash, by_id, cutoff)

    toolbuzz = git_file(TOOLBUZZ, cutoff)
    v2_manifest = json.loads((V2 / "manifest.json").read_bytes())
    if sha(toolbuzz) != v2_manifest["input_sha256"]["aitoolbuzz_csv"]:
        raise ValueError("AIToolBuzz input changed since v2")
    ent = enterprise_examples(annotations, record_rows, by_id)
    tb, tb_excluded = toolbuzz_examples(toolbuzz)
    review = leakage.analyze(ent + tb)
    examples, review_quarantined = review["examples"], review["quarantined"]
    split.validate_inputs(examples, review_quarantined)

    v4_location, v4_manifest = v4_member_partitions()
    partitions = carry_forward_assign(examples, v4_location)
    location = split._assert_isolation(partitions, review_quarantined)
    if set(location) != {r["example_id"] for r in examples}:
        raise ValueError("eligible example assignment coverage mismatch")
    v5_members = {m for r in examples for m in r["metadata"]["member_example_ids"]}
    dropped_v4 = sorted(set(v4_location) - v5_members)
    moved_v4 = sorted(m for r in examples for m in r["metadata"]["member_example_ids"]
                      if m in v4_location and v4_location[m] != location[r["example_id"]])
    if dropped_v4 or moved_v4:
        raise ValueError(f"v4 members dropped ({len(dropped_v4)}) or moved ({len(moved_v4)})")

    by_desc = defaultdict(list)
    for ref, digest in record_rows.items():
        by_desc[digest].append(ref)
    description_rows = [{**label, "product_description": by_hash[d], "trusted_eligible": label["evidence_strength"] == "supported",
                         "exclusion_reason": "" if label["evidence_strength"] == "supported" else "binary_weak_or_forced",
                         "provenance": source} for d, (label, source) in sorted(annotations.items())]
    with io.StringIO(newline="") as stream:
        fields = list(freeze.RECORD_FIELDS) + list(freeze.LABEL_FIELDS) + ["trusted_eligible", "exclusion_reason", "provenance_label_export"]
        writer = csv.DictWriter(stream, fieldnames=fields, lineterminator="\n", extrasaction="ignore")
        writer.writeheader()
        for ref in sorted(record_rows, key=int):
            label, source = annotations[record_rows[ref]]
            writer.writerow({**by_id[ref], **label, "evidence_spans": json.dumps(label["evidence_spans"], ensure_ascii=False),
                             "ai_type_evidence_spans": json.dumps(label["ai_type_evidence_spans"], ensure_ascii=False),
                             "trusted_eligible": label["evidence_strength"] == "supported",
                             "exclusion_reason": "" if label["evidence_strength"] == "supported" else "binary_weak_or_forced",
                             "provenance_label_export": source["label_export"]})
        records_csv = stream.getvalue().encode("utf-8")

    payloads = {"enterprise_descriptions.json": _json(description_rows), "enterprise_records.csv": records_csv,
                "enterprise_quarantined_records.json": _json(quarantined),
                "quarantined.json": _json(review_quarantined), "duplicate_audit.json": _json(review["duplicate_audit"]),
                "identity_review.json": _json(review["identity_review"]), "conflicts.json": _json(review["conflicts"])}
    for name, part_rows in partitions.items():
        with io.StringIO(newline="") as stream:
            writer = csv.writer(stream, lineterminator="\n")
            writer.writerow(["example_id", "description_text", "label"])
            writer.writerows((r["example_id"], r["description_text"], r["label"]) for r in part_rows)
            payloads[f"{name}.csv"] = stream.getvalue().encode("utf-8")
        payloads[f"{name}.metadata.json"] = _json([
            {"example_id": r["example_id"], "leakage_group_id": r["leakage_group_id"],
             "description_sha256": r["description_sha256"], "source": r["source"],
             "source_record_ids": r["source_record_ids"], "member_example_ids": r["metadata"]["member_example_ids"],
             "new_in_v5": is_new_in_v5(r, v4_location), "members": split._member_records(r)} for r in part_rows])
    payloads["assignments.json"] = _json([
        {"example_id": r["example_id"], "leakage_group_id": r["leakage_group_id"], "partition": location[r["example_id"]],
         "new_in_v5": is_new_in_v5(r, v4_location)} for r in sorted(examples, key=lambda r: r["example_id"])])

    labels = [label for label, _ in annotations.values()]

    def slice_support(part_rows, new_only):
        chosen = [r for r in part_rows if not new_only or is_new_in_v5(r, v4_location)]
        return {"examples": len(chosen), "support": split._supports(chosen)}

    summary = {
        "dataset_version": "binary-ai-v5", "source_cutoff": cutoff, "seed": SEED, "policy_version": POLICY_VERSION,
        "selection_policy_version": SELECTION_POLICY, "ratios": split.RATIOS, "feature_allowlist": split.FEATURE_ALLOWLIST,
        "rubric_id": freeze.RUBRIC, "script_sha256": sha(Path(__file__).read_bytes()),
        "input_sha256": {"cleaned_enterprise_csv": sha(cleaned), "aitoolbuzz_csv": sha(toolbuzz),
                         "v4_manifest.json": sha((V4 / "manifest.json").read_bytes())},
        "enterprise_labels": {
            "source_records": len(rows), "source_distinct_descriptions": len(by_hash),
            "accepted_distinct_descriptions": len(annotations), "accepted_rows": len(record_rows),
            "quarantined_descriptions": len(quarantined),
            "binary_counts_including_weak": dict(Counter(l["ai_status"] for l in labels)),
            "supported_binary_counts": dict(Counter(l["ai_status"] for l in labels if l["evidence_strength"] == "supported")),
            "weak_or_forced_binary_counts": dict(Counter(l["ai_status"] for l in labels if l["evidence_strength"] == "weak")),
            "subtype_counts_including_weak": dict(Counter(l["ai_type"] or "null" for l in labels)),
            "label_exports": provenance, "skipped_exports": skipped},
        "aitoolbuzz_examples": len(tb), "aitoolbuzz_excluded_empty_description": tb_excluded,
        "leakage_review": {k: v for k, v in review["summary"].items() if k != "source_cutoff"},
        "examples": len(examples), "quarantined_examples_excluded": len(review_quarantined),
        "v4_carry_forward": {"v4_members": len(v4_location), "v4_members_retained_in_same_partition": len(v4_location),
                             "new_in_v5_examples": sum(is_new_in_v5(r, v4_location) for r in examples)},
        "partitions": {name: {"examples": len(part_rows), "groups": len({r["leakage_group_id"] for r in part_rows}),
                              "achieved_ratio": len(part_rows) / len(examples), "support": split._supports(part_rows),
                              "new_in_v5": slice_support(part_rows, True)} for name, part_rows in partitions.items()},
        "test_reuse_note": "v4 test members were used once to score the frozen v4 model; only new_in_v5 test examples are previously unscored.",
        "evaluation_limit": v4_manifest["evaluation_limit"], "reuse_permission": v4_manifest["reuse_permission"],
        "source_confounding_risk": v4_manifest["source_confounding_risk"],
        "training_or_model_fitting": False, "threshold_selection": False,
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    out.mkdir()
    try:
        for name, data in payloads.items():
            with (out / name).open("xb") as handle:
                handle.write(data)
        summary["output_sha256"] = {name: sha(data) for name, data in payloads.items()}
        (out / "manifest.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    except Exception:
        shutil.rmtree(out)
        raise
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("build",))
    parser.add_argument("--out", type=Path, default=OUT)
    args = parser.parse_args()
    summary = build(args.out)
    print(json.dumps({k: v for k, v in summary.items() if k not in {"enterprise_labels", "output_sha256"}}, indent=2))


if __name__ == "__main__":
    main()
