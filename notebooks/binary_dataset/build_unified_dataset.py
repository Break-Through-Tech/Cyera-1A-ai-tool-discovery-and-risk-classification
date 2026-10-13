"""Build the offline enterprise + AIToolBuzz binary example dataset."""
import argparse
import csv
import hashlib
import io
import json
import subprocess
from collections import Counter, defaultdict
from pathlib import Path

from freeze_enterprise_labels import CUTOFF, ROOT

TOOLBUZZ = "data/aitoolbuzz-com-16k-ai-tools-database/Complete AI Tools Dataset 2025 - 16763 Tools from AIToolBuzz.csv"
ENTERPRISE = ROOT / "data/binary_ai_dataset/v1"
OUT = ROOT / "data/binary_ai_dataset/v2"
TOOLBUZZ_FIELDS = ("Name", "Link", "Logo", "Category", "Primary Task", "Keywords", "Year Founded",
                   "Short Description", "Country", "industry", "technologies", "Website", "Website Status")
FEATURE_ALLOWLIST = ["description_text"]
NORMALIZATION_POLICY = "matching-v1: Unicode casefold; trim and collapse whitespace; punctuation retained; metadata only"
SELECTION_POLICY = "unified-v1: supported enterprise binary labels plus all nonblank AIToolBuzz Short Description rows labeled ai"
DEDUP_POLICY = "candidate-v1: retain source records; enterprise exact descriptions have one example with all record memberships; no cross-source deduplication"


def sha(data):
    return hashlib.sha256(data).hexdigest()


def pinned_file(path, cutoff=CUTOFF):
    try:
        return subprocess.check_output(["git", "show", f"{cutoff}:{path}"], cwd=ROOT)
    except subprocess.CalledProcessError as exc:
        raise ValueError(f"missing pinned input: {path}") from exc


def normalize_for_matching(text):
    return " ".join(text.casefold().split())


def read_toolbuzz(data):
    try:
        reader = csv.reader(io.StringIO(data.decode("utf-8-sig"), newline=""), strict=True)
        fields = next(reader)
        if tuple(fields) != TOOLBUZZ_FIELDS:
            raise ValueError("AIToolBuzz CSV schema mismatch")
        rows = []
        for record_number, row in enumerate(reader, 1):
            if len(row) != len(TOOLBUZZ_FIELDS):
                raise ValueError(f"AIToolBuzz CSV row width mismatch at source record {record_number}")
            rows.append(dict(zip(TOOLBUZZ_FIELDS, row)))
        return rows
    except (UnicodeDecodeError, csv.Error, StopIteration) as exc:
        raise ValueError("invalid AIToolBuzz CSV") from exc


def _enterprise_examples(descriptions_path, records_path, manifest_path):
    manifest = json.loads(manifest_path)
    if manifest.get("source_cutoff") != CUTOFF:
        raise ValueError("enterprise freeze source cutoff mismatch")
    if manifest.get("artifacts", {}).get("enterprise_descriptions.json") != sha(descriptions_path):
        raise ValueError("enterprise descriptions checksum mismatch")
    if manifest.get("artifacts", {}).get("enterprise_records.csv") != sha(records_path):
        raise ValueError("enterprise records checksum mismatch")
    descriptions = json.loads(descriptions_path)
    by_hash = {}
    for item in descriptions:
        text = item.get("product_description")
        digest = item.get("description_sha256")
        if not isinstance(text, str) or not text or sha(text.encode("utf-8")) != digest:
            raise ValueError("invalid enterprise description/hash")
        if digest in by_hash:
            raise ValueError("duplicate enterprise description annotation")
        if item.get("trusted_eligible") is not True:
            continue
        if item.get("ai_status") not in {"ai", "non_ai"} or item.get("evidence_strength") != "supported":
            raise ValueError("trusted enterprise label is not supported binary")
        by_hash[digest] = {"text": text, "label": item["ai_status"], "annotation_id": item["annotation_id"],
                           "provenance": item["provenance"]}

    grouped_records = defaultdict(list)
    reader = csv.DictReader(io.StringIO(records_path.decode("utf-8"), newline=""))
    required = {"source_record_number", "product_group_id", "product_name", "vendor_name", "taxonomy_category",
                "taxonomy_sub_category", "product_description", "description_sha256", "ai_status", "trusted_eligible"}
    if not required <= set(reader.fieldnames or ()):
        raise ValueError("enterprise record schema mismatch")
    seen_ids = set()
    for row in reader:
        rid = row["source_record_number"]
        if not rid or rid in seen_ids:
            raise ValueError("duplicate or empty enterprise source record ID")
        seen_ids.add(rid)
        if row["trusted_eligible"] != "True":
            continue
        item = by_hash.get(row["description_sha256"])
        if item is None or row["product_description"] != item["text"] or row["ai_status"] != item["label"]:
            raise ValueError(f"enterprise record does not match trusted annotation: {rid}")
        grouped_records[row["description_sha256"]].append(row)
    if set(grouped_records) != set(by_hash):
        raise ValueError("trusted enterprise description/record coverage mismatch")
    expected_memberships = manifest.get("finalized_rows", 0) - manifest.get("weak_or_forced_rows", 0)
    if sum(map(len, grouped_records.values())) != expected_memberships:
        raise ValueError("trusted enterprise record membership count mismatch")

    examples = []
    for digest, item in sorted(by_hash.items()):
        members = sorted(grouped_records[digest], key=lambda x: int(x["source_record_number"]))
        examples.append({"example_id": f"enterprise-description:{digest}", "source": "enterprise",
                         "source_record_ids": [f"enterprise-row:{r['source_record_number']}" for r in members],
                         "description_text": item["text"], "description_sha256": digest,
                         "matching_normalized_text": normalize_for_matching(item["text"]), "label": item["label"],
                         "metadata": {"annotation_id": item["annotation_id"], "source_records": [
                             {"source_record_number": r["source_record_number"], "product_group_id": r["product_group_id"],
                              "product_name": r["product_name"], "vendor_name": r["vendor_name"],
                              "taxonomy_category": r["taxonomy_category"],
                              "taxonomy_sub_category": r["taxonomy_sub_category"]} for r in members],
                             "label_provenance": item["provenance"]}})
    return examples, len(seen_ids)


def build_dataset(toolbuzz_bytes, descriptions_bytes, records_bytes, enterprise_manifest_bytes, cutoff=CUTOFF):
    if cutoff != CUTOFF:
        raise ValueError("dataset source cutoff is pinned and cannot be overridden")
    examples, enterprise_records = _enterprise_examples(descriptions_bytes, records_bytes, enterprise_manifest_bytes)
    rows = read_toolbuzz(toolbuzz_bytes)
    excluded = []
    for number, row in enumerate(rows, 1):
        text = row["Short Description"]
        record_id = f"aitoolbuzz-row:{number:05d}"
        if not text.strip():
            excluded.append({"source_record_id": record_id, "reason": "empty_description", "metadata": {
                "name": row["Name"], "link": row["Link"], "website": row["Website"], "category": row["Category"]}})
            continue
        digest = sha(text.encode("utf-8"))
        examples.append({"example_id": record_id, "source": "aitoolbuzz", "source_record_ids": [record_id],
                         "description_text": text, "description_sha256": digest,
                         "matching_normalized_text": normalize_for_matching(text), "label": "ai",
                         "metadata": {"name": row["Name"], "link": row["Link"], "logo": row["Logo"],
                                      "category": row["Category"], "primary_task": row["Primary Task"],
                                      "keywords": row["Keywords"], "year_founded": row["Year Founded"],
                                      "country": row["Country"], "industry": row["industry"],
                                      "technologies": row["technologies"], "website": row["Website"],
                                      "website_status": row["Website Status"]}})
    counts = Counter((row["source"], row["label"]) for row in examples)
    summary = {"source_cutoff": cutoff, "examples": len(examples),
               "source_records": {"enterprise": enterprise_records, "aitoolbuzz": len(rows)},
               "examples_by_source_and_class": {f"{s}:{c}": counts[s, c] for s in ("enterprise", "aitoolbuzz") for c in ("ai", "non_ai")},
               "excluded_by_source_and_reason": {"aitoolbuzz:empty_description": len(excluded)},
               "aitoolbuzz_usable_description_rows": len(rows) - len(excluded),
               "aitoolbuzz_distinct_usable_exact_descriptions": len({x["description_sha256"] for x in examples if x["source"] == "aitoolbuzz"}),
               "enterprise_distinct_trusted_descriptions": sum(x["source"] == "enterprise" for x in examples),
               "enterprise_record_memberships": sum(len(x["source_record_ids"]) for x in examples if x["source"] == "enterprise"),
               "input_schema": {"aitoolbuzz_csv": list(TOOLBUZZ_FIELDS),
                                "enterprise_description_fields": ["product_description", "description_sha256",
                                                                   "ai_status", "evidence_strength", "trusted_eligible"],
                                "enterprise_record_fields": ["source_record_number", "product_group_id",
                                                             "product_name", "vendor_name", "taxonomy_category",
                                                             "taxonomy_sub_category", "product_description",
                                                             "description_sha256", "ai_status", "trusted_eligible"]},
               "feature_allowlist": FEATURE_ALLOWLIST, "selection_policy_version": SELECTION_POLICY,
               "normalization_policy_version": NORMALIZATION_POLICY, "deduplication_policy_version": DEDUP_POLICY,
               "partition_assignment": "not assigned in this phase"}
    return {"examples": examples, "exclusions": excluded, "summary": summary}


def write_dataset(out=OUT, cutoff=CUTOFF):
    if cutoff != CUTOFF:
        raise ValueError("dataset source cutoff is pinned and cannot be overridden")
    out = Path(out)
    if out.exists() or out.is_symlink():
        raise FileExistsError(f"refusing to overwrite existing output: {out}")
    inputs = {"aitoolbuzz_csv": pinned_file(TOOLBUZZ, cutoff),
              "enterprise_descriptions.json": (ENTERPRISE / "enterprise_descriptions.json").read_bytes(),
              "enterprise_records.csv": (ENTERPRISE / "enterprise_records.csv").read_bytes(),
              "enterprise_manifest.json": (ENTERPRISE / "manifest.json").read_bytes()}
    result = build_dataset(inputs["aitoolbuzz_csv"], inputs["enterprise_descriptions.json"],
                           inputs["enterprise_records.csv"], inputs["enterprise_manifest.json"], cutoff)
    payloads = {"examples.json": (json.dumps(result["examples"], ensure_ascii=False, indent=2) + "\n").encode(),
                "exclusions.json": (json.dumps(result["exclusions"], ensure_ascii=False, indent=2) + "\n").encode()}
    manifest = {**result["summary"], "input_sha256": {name: sha(data) for name, data in inputs.items()},
                "artifact_sha256": {name: sha(data) for name, data in payloads.items()}}
    payloads["manifest.json"] = (json.dumps(manifest, ensure_ascii=False, indent=2) + "\n").encode()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.mkdir()
    try:
        for name, data in payloads.items():
            with (out / name).open("xb") as handle:
                handle.write(data)
    except Exception:
        for child in out.iterdir():
            child.unlink()
        out.rmdir()
        raise
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("build",))
    args = parser.parse_args()
    if args.command == "build":
        print(json.dumps(write_dataset(), indent=2))


if __name__ == "__main__":
    main()
