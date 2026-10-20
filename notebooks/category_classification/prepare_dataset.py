"""Freeze a description-only AIToolBuzz category dataset and identity-grouped splits."""

from __future__ import annotations

import csv
import hashlib
import json
import re
from collections import Counter, defaultdict
from difflib import SequenceMatcher
from pathlib import Path
from urllib.parse import urlsplit

from sklearn.model_selection import StratifiedGroupKFold


ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "data/aitoolbuzz-com-16k-ai-tools-database/ai_tools_cleaned.csv"
QUALITY_REPORT = ROOT / "data/aitoolbuzz-com-16k-ai-tools-database/ai_tools_quality_report.json"
OUTPUT = ROOT / "data/category_classification/v1"
SEED = 20261014
POLICY = "description-only-identity-and-near-description-groups-v1"
SPLITS = ("train", "validation", "test")
COLUMNS = ("tool_id", "group_id", "description_text", "category")
REVIEW_COLUMNS = (
    "tool_id", "Name", "Website", "Category", "Short Description",
    "duplicate_description_group", "disposition", "reason",
)
NEAR_REVIEW_COLUMNS = (
    "left_tool_id", "right_tool_id", "left_name", "right_name",
    "left_category", "right_category", "left_description", "right_description",
    "description_similarity", "category_disagreement",
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def description_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.casefold()).strip()


def name_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.casefold())


def host_key(value: str) -> str:
    host = urlsplit(value).hostname or ""
    return host.casefold().removeprefix("www.")


def read_source() -> list[dict[str, str]]:
    with SOURCE.open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        required = {
            "tool_id", "Name", "Website", "Category", "Short Description",
            "duplicate_description_flag", "description_label_conflict_flag",
        }
        if not required.issubset(reader.fieldnames or ()):
            raise ValueError(f"Missing cleaned catalog columns: {sorted(required - set(reader.fieldnames or ()))}")
        rows = list(reader)
    ids = [row["tool_id"] for row in rows]
    if len(ids) != len(set(ids)) or any(not item for item in ids):
        raise ValueError("Cleaned catalog has missing or duplicate tool_id values")
    if any(not row["Short Description"].strip() or not row["Category"].strip() for row in rows):
        raise ValueError("Cleaned catalog has empty descriptions or categories")
    return rows


def triage_descriptions(rows: list[dict[str, str]]) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    """Retain shared-text/same-label rows; hold conflicting-label rows for review."""
    by_text: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        by_text[description_key(row["Short Description"])].append(row)

    eligible, review = [], []
    for row in rows:
        key = description_key(row["Short Description"])
        members = by_text[key]
        duplicate = len(members) > 1
        conflict = len({member["Category"] for member in members}) > 1
        if (row["duplicate_description_flag"] != "ok") != duplicate:
            raise ValueError(f"Duplicate-description flag mismatch: {row['tool_id']}")
        if (row["description_label_conflict_flag"] != "ok") != conflict:
            raise ValueError(f"Description/category conflict flag mismatch: {row['tool_id']}")
        if duplicate:
            review.append({
                **{column: row[column] for column in ("tool_id", "Name", "Website", "Category", "Short Description")},
                "duplicate_description_group": hashlib.sha256(key.encode()).hexdigest()[:16],
                "disposition": "exclude_pending_label_review" if conflict else "retain_grouped",
                "reason": "identical_description_different_categories" if conflict else "identical_description_same_category",
            })
        if not conflict:
            eligible.append(row)
    return eligible, review


def near_description_pairs(rows: list[dict[str, str]]) -> list[tuple[int, int, float]]:
    """Find strongly similar descriptions using rare shared four-word shingles."""
    texts = [description_key(row["Short Description"]) for row in rows]
    postings: dict[tuple[str, ...], list[int]] = defaultdict(list)
    for index, text in enumerate(texts):
        if len(text) < 40:
            continue
        words = text.split()
        for position in range(len(words) - 3):
            postings[tuple(words[position:position + 4])].append(index)
    candidates: set[tuple[int, int]] = set()
    for members in postings.values():
        if len(members) > 30:
            continue  # Common phrasing is not strong evidence of related text.
        for offset, left in enumerate(members):
            for right in members[offset + 1:]:
                if left != right:
                    candidates.add((min(left, right), max(left, right)))
    matched = []
    for left, right in sorted(candidates):
        if texts[left] == texts[right]:
            continue  # Exact descriptions are already grouped.
        matcher = SequenceMatcher(None, texts[left], texts[right])
        if matcher.quick_ratio() < 0.92:
            continue
        similarity = matcher.ratio()
        if similarity >= 0.92:
            matched.append((left, right, similarity))
    return matched


def identity_groups(rows: list[dict[str, str]]) -> tuple[list[str], list[tuple[int, int, float]]]:
    """Join suspected related listings without claiming they are the same Tool."""
    parent = list(range(len(rows)))

    def find(index: int) -> int:
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    def union(left: int, right: int) -> None:
        parent[find(left)] = find(right)

    seen: dict[tuple[str, str], int] = {}
    for index, row in enumerate(rows):
        keys = (
            ("description", description_key(row["Short Description"])),
            ("name", name_key(row["Name"])),
            ("host", host_key(row["Website"])),
        )
        for kind, key in keys:
            if not key:
                continue
            marker = (kind, key)
            if marker in seen:
                union(index, seen[marker])
            else:
                seen[marker] = index

    near_pairs = near_description_pairs(rows)
    for left, right, _ in near_pairs:
        union(left, right)

    members: dict[int, list[str]] = defaultdict(list)
    for index, row in enumerate(rows):
        members[find(index)].append(row["tool_id"])
    group_ids = {
        root: "group:" + hashlib.sha256("|".join(sorted(ids)).encode()).hexdigest()[:20]
        for root, ids in members.items()
    }
    return [group_ids[find(index)] for index in range(len(rows))], near_pairs


def assign_splits(rows: list[dict[str, str]], groups: list[str]) -> list[str]:
    """Reserve two of five stratified group folds for validation and final test."""
    splitter = StratifiedGroupKFold(n_splits=5, shuffle=True, random_state=SEED)
    folds = list(splitter.split([row["Short Description"] for row in rows],
                                [row["Category"] for row in rows], groups))
    assignments = ["train"] * len(rows)
    for index in folds[0][1]:
        assignments[index] = "test"
    for index in folds[1][1]:
        assignments[index] = "validation"
    partitions: dict[str, set[str]] = defaultdict(set)
    for group, partition in zip(groups, assignments):
        partitions[group].add(partition)
    if any(len(values) != 1 for values in partitions.values()):
        raise AssertionError("Identity group crossed partitions")
    categories = {row["Category"] for row in rows}
    for partition in SPLITS:
        present = {row["Category"] for row, assigned in zip(rows, assignments) if assigned == partition}
        if present != categories:
            raise ValueError(f"Missing categories in {partition}: {sorted(categories - present)}")
    return assignments


def write_csv(path: Path, fieldnames: tuple[str, ...], rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    rows = read_source()
    quality = json.loads(QUALITY_REPORT.read_text(encoding="utf-8"))
    eligible, review = triage_descriptions(rows)
    expected = quality["row_counts"]
    if len(rows) != expected["output_rows"] or len(review) != expected["duplicate_descriptions_flagged"]:
        raise ValueError("Cleaned catalog and quality report disagree")
    excluded = sum(item["disposition"] == "exclude_pending_label_review" for item in review)
    if excluded != expected["description_label_conflicts_flagged"]:
        raise ValueError("Conflict count and quality report disagree")

    groups, near_pairs = identity_groups(eligible)
    assignments = assign_splits(eligible, groups)
    OUTPUT.mkdir(parents=True, exist_ok=True)
    write_csv(OUTPUT / "description_review.csv", REVIEW_COLUMNS, review)
    write_csv(OUTPUT / "near_description_review.csv", NEAR_REVIEW_COLUMNS, [
        {
            "left_tool_id": eligible[left]["tool_id"],
            "right_tool_id": eligible[right]["tool_id"],
            "left_name": eligible[left]["Name"],
            "right_name": eligible[right]["Name"],
            "left_category": eligible[left]["Category"],
            "right_category": eligible[right]["Category"],
            "left_description": eligible[left]["Short Description"],
            "right_description": eligible[right]["Short Description"],
            "description_similarity": f"{similarity:.6f}",
            "category_disagreement": str(eligible[left]["Category"] != eligible[right]["Category"]).lower(),
        }
        for left, right, similarity in near_pairs
    ])
    split_rows = {partition: [] for partition in SPLITS}
    for row, group, partition in zip(eligible, groups, assignments):
        split_rows[partition].append({
            "tool_id": row["tool_id"], "group_id": group,
            "description_text": row["Short Description"], "category": row["Category"],
        })
    for partition in SPLITS:
        write_csv(OUTPUT / f"{partition}.csv", COLUMNS, split_rows[partition])

    manifest = {
        "dataset_id": "aitoolbuzz-category-v1",
        "source": str(SOURCE.relative_to(ROOT)).replace("\\", "/"),
        "source_sha256": sha256(SOURCE),
        "quality_report_sha256": sha256(QUALITY_REPORT),
        "policy": POLICY,
        "seed": SEED,
        "input_feature_allowlist": ["description_text"],
        "target": "category",
        "identity_group_keys": ["normalized_description", "normalized_name", "website_hostname",
                                "near_description_similarity_at_least_0.92"],
        "split_method": "StratifiedGroupKFold: fold 0 test, fold 1 validation, folds 2-4 train",
        "review_policy": "Conflicting category labels for identical normalized text are held out pending manual review; same-label duplicate text is retained in one split.",
        "counts": {
            "source_rows": len(rows), "eligible_rows": len(eligible),
            "review_rows": len(review), "conflict_rows_excluded": excluded,
            "same_label_duplicate_rows_retained": len(review) - excluded,
            "near_description_pairs_grouped": len(near_pairs),
            "near_description_pairs_with_category_disagreement": sum(
                eligible[left]["Category"] != eligible[right]["Category"]
                for left, right, _ in near_pairs
            ),
            "groups": len(set(groups)),
        },
        "partitions": {
            partition: {
                "rows": len(split_rows[partition]),
                "groups": len({row["group_id"] for row in split_rows[partition]}),
                "category_support": dict(sorted(Counter(row["category"] for row in split_rows[partition]).items())),
                "sha256": sha256(OUTPUT / f"{partition}.csv"),
            }
            for partition in SPLITS
        },
        "review_sha256": sha256(OUTPUT / "description_review.csv"),
        "near_review_sha256": sha256(OUTPUT / "near_description_review.csv"),
    }
    (OUTPUT / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(f"Prepared {len(eligible):,} eligible descriptions in {len(set(groups)):,} groups")
    for partition in SPLITS:
        print(f"{partition}: {len(split_rows[partition]):,} rows")
    print(f"Review: {len(review)} flagged rows, including {excluded} excluded conflicts")
    print(f"Near descriptions grouped: {len(near_pairs)} pairs")


if __name__ == "__main__":
    main()
