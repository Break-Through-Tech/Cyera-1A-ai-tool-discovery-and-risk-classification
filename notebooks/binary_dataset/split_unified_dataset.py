"""Freeze deterministic, leakage-safe train/validation/test partitions."""
import argparse
import csv
import hashlib
import json
import random
import re
import shutil
from collections import Counter, defaultdict
from pathlib import Path

from freeze_enterprise_labels import CUTOFF, ROOT

INPUT = ROOT / "data/binary_ai_dataset/v3"
OUT = ROOT / "data/binary_ai_dataset/v4"
SEED = 20261014
POLICY_VERSION = "whole-leakage-group-greedy-stratified-v1"
PARTITIONS = ("train", "validation", "test")
RATIOS = {"train": 0.70, "validation": 0.15, "test": 0.15}
FEATURE_ALLOWLIST = ["description_text"]


def sha(data):
    return hashlib.sha256(data).hexdigest()


def normalized(text):
    return " ".join(text.casefold().split())


def normalized_name(value):
    return " ".join(re.findall(r"[a-z0-9]+", (value or "").casefold()))


def _member_records(example):
    meta = example["metadata"]
    members = meta.get("members")
    if members is None:
        members = [{"example_id": example["example_id"], "source": example["source"],
                    "label": example["label"], "source_record_ids": example["source_record_ids"],
                    "metadata": meta}]
    if not isinstance(members, list) or not members:
        raise ValueError(f"missing member metadata: {example['example_id']}")
    if meta.get("member_example_ids") != [m.get("example_id") for m in members]:
        raise ValueError(f"member ID mapping mismatch: {example['example_id']}")
    return members


def validate_inputs(examples, quarantined):
    if not isinstance(examples, list) or not isinstance(quarantined, list):
        raise ValueError("v3 examples and quarantine must be lists")
    quarantined_ids = set()
    for row in quarantined:
        if not isinstance(row, dict) or not isinstance(row.get("example_id"), str):
            raise ValueError("malformed quarantined example ID")
        quarantined_ids.add(row["example_id"])
    seen_examples, seen_members, group_by_id = set(), set(), {}
    for row in examples:
        if not isinstance(row, dict):
            raise ValueError("malformed v3 example")
        eid, text, label, source, group = (row.get(k) for k in
                                           ("example_id", "description_text", "label", "source", "leakage_group_id"))
        if not isinstance(eid, str) or not eid or eid in seen_examples:
            raise ValueError("missing or duplicate example ID")
        if eid in quarantined_ids:
            raise ValueError(f"quarantined example admitted: {eid}")
        if not isinstance(text, str) or not text or row.get("description_sha256") != sha(text.encode("utf-8")):
            raise ValueError(f"invalid example description/hash: {eid}")
        if label not in {"ai", "non_ai"} or source not in {"enterprise", "aitoolbuzz", "merged"}:
            raise ValueError(f"invalid example label/source: {eid}")
        if not isinstance(group, str) or not group:
            raise ValueError(f"missing leakage group ID: {eid}")
        members = _member_records(row)
        ids = []
        for member in members:
            mid = member.get("example_id")
            if not isinstance(mid, str) or not mid or mid in seen_members:
                raise ValueError(f"missing or duplicate member ID: {eid}")
            if member.get("source") not in {"enterprise", "aitoolbuzz"} or member.get("label") != label:
                raise ValueError(f"invalid member source/label metadata: {mid}")
            record_ids = member.get("source_record_ids")
            if not isinstance(record_ids, list) or not record_ids or any(not isinstance(x, str) or not x for x in record_ids):
                raise ValueError(f"invalid member source-record IDs: {mid}")
            metadata = member.get("metadata")
            if not isinstance(metadata, dict):
                raise ValueError(f"invalid member metadata: {mid}")
            # These indicate source rows outside the supported binary pool.
            if metadata.get("trusted_eligible") is False or metadata.get("evidence_strength") in {"weak", "forced"}:
                raise ValueError(f"weak/forced enterprise member admitted: {mid}")
            ids.append(mid)
            seen_members.add(mid)
        if ids != row["metadata"]["member_example_ids"]:
            raise ValueError(f"malformed member mapping: {eid}")
        if source != "merged" and any(m["source"] != source for m in members):
            raise ValueError(f"source/member mismatch: {eid}")
        seen_examples.add(eid)
        group_by_id[eid] = group
    if not examples:
        raise ValueError("v3 eligible examples are empty")
    return group_by_id


def _profile(rows):
    profile = Counter()
    for row in rows:
        profile["examples:all"] += 1
        profile[f"example:{row['label']}"] += 1
        for member in _member_records(row):
            profile[f"member:{member['source']}:{member['label']}"] += len(member["source_record_ids"])
    return profile


def assign(examples, seed=SEED):
    """Greedily balance size, class, and source-member support without splitting groups."""
    validate_inputs(examples, [])
    groups = defaultdict(list)
    for row in examples:
        groups[row["leakage_group_id"]].append(row)
    total = _profile(examples)
    ordered = sorted(groups.items())
    rng = random.Random(seed)
    rng.shuffle(ordered)
    ordered.sort(key=lambda item: -len(item[1]))
    assigned = {name: [] for name in PARTITIONS}
    current = {name: Counter() for name in PARTITIONS}
    for group_id, rows in ordered:
        contribution = _profile(rows)
        choices = []
        for partition in PARTITIONS:
            # Minimize the change in the global, total-normalized target error.
            score = 0.0
            for key, amount in total.items():
                target = amount * RATIOS[partition]
                before = current[partition][key]
                after = before + contribution[key]
                scale = max(amount, 1)
                score += ((after - target) ** 2 - (before - target) ** 2) / (scale ** 2)
            choices.append((score, PARTITIONS.index(partition), partition))
        partition = min(choices)[2]
        assigned[partition].extend(rows)
        current[partition].update(contribution)
    return {name: sorted(rows, key=lambda row: row["example_id"]) for name, rows in assigned.items()}


def _assert_isolation(partitions, quarantined):
    qids = {row["example_id"] for row in quarantined}
    location, groups = {}, {}
    for partition, rows in partitions.items():
        for row in rows:
            if row["example_id"] in location or row["example_id"] in qids:
                raise ValueError(f"duplicate or quarantined assignment: {row['example_id']}")
            location[row["example_id"]] = partition
            groups.setdefault(row["leakage_group_id"], set()).add(partition)
    if any(len(partitions_for_group) != 1 for partitions_for_group in groups.values()):
        raise ValueError("leakage group crosses partitions")
    # Independently verify all v3 grouping constraints represented in member metadata.
    hashes, names, products = defaultdict(set), defaultdict(set), defaultdict(set)
    for partition, rows in partitions.items():
        for row in rows:
            hashes[row["description_sha256"]].add(partition)
            hashes[sha(normalized(row["description_text"]).encode())].add(partition)
            for member in _member_records(row):
                metadata = member["metadata"]
                source_rows = metadata.get("source_records", [])
                if member["source"] == "enterprise":
                    for source_row in source_rows:
                        name = normalized_name(source_row.get("product_name"))
                        product = source_row.get("product_group_id")
                        if name:
                            names[name].add(partition)
                        if product:
                            products[product].add(partition)
                else:
                    name = normalized_name(metadata.get("name"))
                    if name:
                        names[name].add(partition)
    if any(len(x) > 1 for x in (*hashes.values(), *names.values(), *products.values())):
        raise ValueError("text, same-name candidate, or product identity key crosses partitions")
    return location


def _supports(rows):
    counts = Counter()
    for row in rows:
        counts[f"examples:{row['label']}"] += 1
        for member in _member_records(row):
            counts[f"source_members:{member['source']}:{member['label']}"] += len(member["source_record_ids"])
    return dict(sorted(counts.items()))


def build(out=OUT):
    out = Path(out)
    if out.exists() or out.is_symlink():
        raise FileExistsError(f"refusing to overwrite existing output: {out}")
    manifest_bytes = (INPUT / "manifest.json").read_bytes()
    manifest = json.loads(manifest_bytes)
    if manifest.get("source_cutoff") != CUTOFF:
        raise ValueError("v3 source cutoff mismatch")
    input_hashes = {"v3_manifest.json": sha(manifest_bytes)}
    for filename, expected in manifest.get("artifact_sha256", {}).items():
        data = (INPUT / filename).read_bytes()
        if sha(data) != expected:
            raise ValueError(f"v3 artifact checksum mismatch: {filename}")
        input_hashes[f"v3_{filename}"] = sha(data)
    examples_bytes = (INPUT / "examples.json").read_bytes()
    quarantine_bytes = (INPUT / "quarantined.json").read_bytes()
    examples = json.loads(examples_bytes)
    quarantined = json.loads(quarantine_bytes)
    validate_inputs(examples, quarantined)
    partitions = assign(examples)
    location = _assert_isolation(partitions, quarantined)
    if set(location) != {row["example_id"] for row in examples}:
        raise ValueError("eligible example assignment coverage mismatch")
    if any(abs(len(partitions[name]) / len(examples) - RATIOS[name]) > 0.02 for name in PARTITIONS):
        raise ValueError("whole-group allocation is not approximately 70/15/15")
    enterprise_test = [r for r in partitions["test"] if any(m["source"] == "enterprise" for m in _member_records(r))]
    enterprise_test_classes = Counter(m["label"] for r in enterprise_test for m in _member_records(r) if m["source"] == "enterprise")
    payloads = {}
    for name, rows in partitions.items():
        with __import__("io").StringIO(newline="") as stream:
            writer = csv.writer(stream, lineterminator="\n")
            writer.writerow(["example_id", "description_text", "label"])
            writer.writerows((r["example_id"], r["description_text"], r["label"]) for r in rows)
            payloads[f"{name}.csv"] = stream.getvalue().encode("utf-8")
        metadata = [{"example_id": r["example_id"], "leakage_group_id": r["leakage_group_id"],
                     "description_sha256": r["description_sha256"], "source": r["source"],
                     "source_record_ids": r["source_record_ids"], "member_example_ids": r["metadata"]["member_example_ids"],
                     "members": _member_records(r)} for r in rows]
        payloads[f"{name}.metadata.json"] = (json.dumps(metadata, ensure_ascii=False, indent=2) + "\n").encode()
    assignment = [{"example_id": row["example_id"], "leakage_group_id": row["leakage_group_id"],
                   "partition": location[row["example_id"]]} for row in sorted(examples, key=lambda r: r["example_id"])]
    payloads["assignments.json"] = (json.dumps(assignment, ensure_ascii=False, indent=2) + "\n").encode()
    script_hash = sha(Path(__file__).read_bytes())
    summary = {"dataset_version": "binary-ai-v4", "source_cutoff": CUTOFF, "seed": SEED,
               "policy_version": POLICY_VERSION, "ratios": RATIOS, "feature_allowlist": FEATURE_ALLOWLIST,
               "input_sha256": input_hashes, "script_sha256": script_hash,
               "examples": len(examples), "quarantined_examples_excluded": len(quarantined),
               "partitions": {}, "enterprise_only_test_slice": {
                   "source_member_support": dict(sorted(enterprise_test_classes.items())),
                   "both_classes_present": all(enterprise_test_classes[c] > 0 for c in ("ai", "non_ai")),
                   "adequate_support": min(enterprise_test_classes.values(), default=0) >= 10,
                   "interpretation": "construction/quality check only; frozen test data must not select models or thresholds"},
               "evaluation_limit": "No registry/retrieval implementation; no universal or runtime previously-unseen Tool generalization claim.",
               "reuse_permission": "Private reuse scope recorded in notebooks/enterprise_products/LABELING_WORKFLOW.md; no public license claim.",
               "training_or_model_fitting": False, "threshold_selection": False,
               "source_confounding_risk": "AIToolBuzz supplies AI-only rows; enterprise supplies both classes, so source/style confounding remains."}
    for name, rows in partitions.items():
        summary["partitions"][name] = {"examples": len(rows), "groups": len({r["leakage_group_id"] for r in rows}),
                                       "achieved_ratio": len(rows) / len(examples), "support": _supports(rows)}
    payloads["manifest.json"] = b""
    out.parent.mkdir(parents=True, exist_ok=True)
    out.mkdir()
    try:
        for filename, data in payloads.items():
            with (out / filename).open("xb") as handle:
                handle.write(data)
        summary["output_sha256"] = {name: sha(data) for name, data in payloads.items() if name != "manifest.json"}
        (out / "manifest.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    except Exception:
        shutil.rmtree(out)
        raise
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("build",))
    parser.parse_args()
    print(json.dumps(build(), indent=2))


if __name__ == "__main__":
    main()
