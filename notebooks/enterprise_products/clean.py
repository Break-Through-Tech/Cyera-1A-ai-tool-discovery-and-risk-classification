#!/usr/bin/env python3
"""Build a separate, reproducible view using the reviewed enterprise cleaning rules."""

import csv
import hashlib
import io
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

import eda
from eda import FIELDS, INPUT, ROOT, load_rows, norm

OUTPUT = INPUT.with_name("products_cleaned.csv")
REPORT = INPUT.with_name("cleaning_report.json")
EXPECTED_SHA256 = "afe7cdbcbf82d9b11f579eb6dce000815a04a301410636e2942036f072fc7aa1"
RULE_VERSION = "enterprise-products-cleaning-v1"
# Only reviewed records are excluded; a word such as 'support' does not disqualify software.
REVIEWED_EXCLUSIONS = {
    ("signature services", "qliktech inc"): "reviewed_consulting_support_package",
    ("hyperion bi analysis fee", "kurt steckel"): "reviewed_fee_entry",
}
OUTPUT_FIELDS = ("source_record_number", "product_group_id", *FIELDS)


def normalize_text(value):
    return value.replace("\r\n", "\n").replace("\r", "\n").strip()


def clean_rows(rows):
    cleaned = []
    excluded = []
    changes = Counter()
    groups = defaultdict(list)
    for row in rows:
        number = row["source_record_number"]
        values = {field: normalize_text(row[field]) for field in FIELDS}
        for field in FIELDS[:-1]:
            if not values[field]:
                raise ValueError(f"logical source record {number}: missing {field}")
        key = (norm(values["product_name"]), norm(values["vendor_name"]))
        reasons = []
        description = values["product_description"]
        if not description:
            reasons.append("missing_description")
        if norm(description) == "need product description":
            reasons.append("placeholder_description")
        if "\ufffd" in description:
            reasons.append("replacement_character_in_description")
        if key in REVIEWED_EXCLUSIONS:
            reasons.append(REVIEWED_EXCLUSIONS[key])
        if reasons:
            excluded.append({"source_record_number": number,
                             "product_name": row["product_name"],
                             "vendor_name": row["vendor_name"], "reasons": reasons})
            continue
        # Grouping is a source-scoped assumption, not a verified cross-source Tool identity.
        group_id = "enterprise-" + hashlib.sha256(
            json.dumps(key, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        result = {"source_record_number": number, "product_group_id": group_id, **values}
        cleaned.append(result)
        groups[group_id].append(result)
        changes.update(field for field in FIELDS if values[field] != row[field])

    repeated = []
    for group_id, members in sorted(groups.items()):
        if len(members) > 1:
            memberships = sorted({(row["taxonomy_category"], row["taxonomy_sub_category"])
                                  for row in members})
            repeated.append({"product_group_id": group_id,
                             "source_record_numbers": sorted(row["source_record_number"] for row in members),
                             "memberships": [{"category": category, "subcategory": subcategory}
                                             for category, subcategory in memberships]})
    summary = {
        "input_records": len(rows), "retained_records": len(cleaned),
        "excluded_records": len(excluded),
        "exclusion_reason_counts": dict(sorted(Counter(reason for row in excluded
                                                       for reason in row["reasons"]).items())),
        "exclusion_counts_may_overlap": True,
        "excluded_source_records": excluded,
        "normalized_retained_values_by_field": dict(sorted(changes.items())),
        "retained_product_groups": len(groups),
        "repeated_product_groups": repeated,
        "category_record_counts": dict(sorted(Counter(row["taxonomy_category"] for row in cleaned).items())),
        "subcategory_record_counts": dict(sorted(Counter(row["taxonomy_sub_category"] for row in cleaned).items())),
    }
    return cleaned, summary


def write_outputs(input_path=INPUT, output_path=OUTPUT, report_path=REPORT):
    paths = [Path(path).resolve() for path in (input_path, output_path, report_path)]
    for index, path in enumerate(paths):
        for other in paths[index + 1:]:
            if path == other or (path.exists() and other.exists() and path.samefile(other)):
                raise ValueError("input, cleaned CSV, and report must refer to different files")
    input_path, output_path, report_path = paths
    source_bytes = input_path.read_bytes()
    source_hash = hashlib.sha256(source_bytes).hexdigest()
    if input_path == INPUT.resolve() and source_hash != EXPECTED_SHA256:
        raise ValueError(f"input snapshot checksum mismatch: {source_hash}")
    rows = load_rows(input_path)
    cleaned, report = clean_rows(rows)
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=OUTPUT_FIELDS, lineterminator="\n")
    writer.writeheader()
    writer.writerows(cleaned)
    output_bytes = buffer.getvalue().encode("utf-8")
    report.update({
        "rule_version": RULE_VERSION,
        "source": {"path": str(input_path.relative_to(ROOT)) if input_path.is_relative_to(ROOT) else str(input_path),
                   "sha256": source_hash, "record_reference": "one-based logical CSV data record, excluding header"},
        "output": {"path": str(output_path.relative_to(ROOT)) if output_path.is_relative_to(ROOT) else str(output_path),
                   "sha256": hashlib.sha256(output_bytes).hexdigest(), "fields": list(OUTPUT_FIELDS)},
        "code_sha256": {"clean.py": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                        "eda.py": hashlib.sha256(Path(eda.__file__).read_bytes()).hexdigest()},
        "rules": {
            "normalization": "Trim outer whitespace and convert CRLF/CR to LF; preserve internal spacing, punctuation and Unicode.",
            "reviewed_exclusions": [{"product_name_key": key[0], "vendor_name_key": key[1], "reason": reason}
                                    for key, reason in sorted(REVIEWED_EXCLUSIONS.items())],
            "grouping": "NFKC/case-folded, whitespace-collapsed product name plus vendor, following the reviewed multi-category assumption. Retain every eligible row and category/subcategory pair.",
        },
        "limitations": [
            "The cleaned view is not an AI/non-AI labeled dataset; source taxonomy is not mapped to AIToolBuzz.",
            "Only the two specifically reviewed fee/service entries are excluded; other service-name cues need review, not automatic deletion.",
            "Group IDs are source-scoped grouping clues, not confirmed identity across datasets or vendors.",
            "Shared descriptions across different product groups still need leakage review before freezing partitions.",
            "No encoding repair, fuzzy deduplication, AI-role labels, training splits or model features are produced.",
            "Source reuse permission remains unresolved before training or redistribution.",
        ],
    })
    for path in (output_path, report_path):
        path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(output_bytes)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


if __name__ == "__main__":
    try:
        result = write_outputs()
    except (OSError, UnicodeError, csv.Error, ValueError) as error:
        print(f"Cleaning failed: {error}", file=sys.stderr)
        raise SystemExit(1)
    print(f"Retained {result['retained_records']} of {result['input_records']} records; "
          f"excluded {result['excluded_records']}; {result['retained_product_groups']} product groups.")
    print(f"Wrote {OUTPUT} and {REPORT}")
