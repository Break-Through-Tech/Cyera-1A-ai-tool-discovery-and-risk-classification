"""Prepare the AIToolBuzz archive for NLP-based risk classification.

The source archive is expected at ``data/archive.zip`` and must contain one
CSV file. By default, this script writes ``data/ai_tools_cleaned.csv``.

Examples
--------
python data/clean_data.py
python data/clean_data.py --input C:\\path\\to\\archive.zip --output data/ai_tools_cleaned.csv
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import re
from collections import Counter
from pathlib import Path
from typing import Iterable
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from zipfile import ZipFile


REQUIRED_COLUMNS = {
    "Name",
    "Link",
    "Logo",
    "Category",
    "Primary Task",
    "Keywords",
    "Year Founded",
    "Short Description",
    "Country",
    "industry",
    "technologies",
    "Website",
    "Website Status",
}

# The selected fields are useful for the classification problem.  ``Category``
# is the compact business-function label; ``Primary Task`` remains free text.
OUTPUT_COLUMNS = [
    "tool_id",
    "Name",
    "Website",
    "Category",
    "Primary Task",
    "Short Description",
    "Keywords",
    "industry",
    "text_quality_flag",
    "duplicate_description_flag",
    "description_label_conflict_flag",
]

MIN_DESCRIPTION_LENGTH = 30
TRACKING_PARAMETERS = {
    "ref",
    "fbclid",
    "gclid",
    "mc_cid",
    "mc_eid",
    "msclkid",
    "_hsenc",
    "_hsmi",
}


def clean_text(value: str | None) -> str:
    """Trim a value and collapse whitespace without inventing missing data."""
    return " ".join((value or "").split())


def tool_id(source_link: str) -> str:
    """Make a stable unique identifier after the source listing URL is removed."""
    return hashlib.sha256(source_link.encode("utf-8")).hexdigest()


def canonicalize_website(website: str) -> str:
    """Remove tracking-only URL components while retaining the destination URL."""
    parts = urlsplit(website)
    query = [
        (key, value)
        for key, value in parse_qsl(parts.query, keep_blank_values=True)
        if key.casefold() not in TRACKING_PARAMETERS
        and not key.casefold().startswith("utm_")
    ]
    return urlunsplit(
        (
            parts.scheme.casefold(),
            parts.netloc.casefold(),
            parts.path,
            urlencode(query, doseq=True),
            "",  # URL fragments are not sent to the website and are not identity data.
        )
    )


def normalized_description(description: str) -> str:
    """Create a conservative comparison key without changing model text."""
    return re.sub(r"[^a-z0-9]+", " ", description.casefold()).strip()


def csv_member(archive: ZipFile) -> str:
    """Return the sole CSV member, or raise a clear error for malformed input."""
    members = [name for name in archive.namelist() if name.lower().endswith(".csv")]
    if len(members) != 1:
        raise ValueError(
            "Expected exactly one CSV in the archive; found "
            f"{len(members)}: {members!r}"
        )
    return members[0]


def load_rows(input_path: Path) -> Iterable[dict[str, str]]:
    """Read the CSV directly from the ZIP archive."""
    with ZipFile(input_path) as archive:
        member = csv_member(archive)
        with archive.open(member) as raw_file:
            # utf-8-sig safely handles either ordinary UTF-8 or a BOM.
            reader = csv.DictReader(io.TextIOWrapper(raw_file, encoding="utf-8-sig", newline=""))
            actual_columns = set(reader.fieldnames or [])
            missing_columns = REQUIRED_COLUMNS - actual_columns
            if missing_columns:
                raise ValueError(
                    "Input CSV is missing required columns: "
                    + ", ".join(sorted(missing_columns))
                )
            yield from reader


def clean_rows(rows: Iterable[dict[str, str]]) -> tuple[list[dict[str, str]], Counter[str]]:
    """Filter inactive/incomplete tools and deduplicate only exact source links."""
    report: Counter[str] = Counter()
    cleaned: list[dict[str, str]] = []
    seen_links: set[str] = set()
    websites: list[str] = []

    for raw_row in rows:
        report["input_rows"] += 1
        row = {column: clean_text(value) for column, value in raw_row.items()}

        # Treat ``Active`` and the one lowercase ``active`` record identically.
        if row["Website Status"].casefold() != "active":
            report["removed_non_active"] += 1
            continue

        if not row["Short Description"]:
            report["removed_missing_description"] += 1
            continue

        # These fields define the surviving record and should not be silently
        # represented as empty strings in a training dataset.
        required_values = ("Name", "Link", "Website", "Category", "Primary Task")
        if any(not row[column] for column in required_values):
            report["removed_missing_required_value"] += 1
            continue

        # Product names are not identifiers: different tools can share a name.
        # Link is the source-listing identity key and is unique in this dataset.
        if row["Link"] in seen_links:
            report["removed_duplicate_link"] += 1
            continue

        seen_links.add(row["Link"])
        website = canonicalize_website(row["Website"])
        if website != row["Website"]:
            report["canonicalized_websites"] += 1
        websites.append(website)
        cleaned.append(
            {
                "tool_id": tool_id(row["Link"]),
                "Name": row["Name"],
                "Website": website,
                "Category": row["Category"],
                "Primary Task": row["Primary Task"],
                "Short Description": row["Short Description"],
                "Keywords": row["Keywords"],
                "industry": row["industry"],
            }
        )

    description_counts = Counter(
        normalized_description(row["Short Description"]) for row in cleaned
    )
    description_categories: dict[str, set[str]] = {}
    for row in cleaned:
        description_key = normalized_description(row["Short Description"])
        description_categories.setdefault(description_key, set()).add(row["Category"])

    for row in cleaned:
        description_key = normalized_description(row["Short Description"])
        row["text_quality_flag"] = (
            "review_short" if len(row["Short Description"]) < MIN_DESCRIPTION_LENGTH else "ok"
        )
        row["duplicate_description_flag"] = (
            "review_duplicate" if description_counts[description_key] > 1 else "ok"
        )
        row["description_label_conflict_flag"] = (
            "review_label_conflict"
            if len(description_categories[description_key]) > 1
            else "ok"
        )

    report["output_rows"] = len(cleaned)
    report["website_collisions_retained"] = len(websites) - len(set(websites))
    report["categories"] = len({row["Category"] for row in cleaned})
    report["short_descriptions_flagged"] = sum(
        row["text_quality_flag"] == "review_short" for row in cleaned
    )
    report["duplicate_descriptions_flagged"] = sum(
        row["duplicate_description_flag"] == "review_duplicate" for row in cleaned
    )
    report["description_label_conflicts_flagged"] = sum(
        row["description_label_conflict_flag"] == "review_label_conflict"
        for row in cleaned
    )
    return cleaned, report


def write_csv(rows: list[dict[str, str]], output_path: Path) -> None:
    """Write a UTF-8 CSV that can be read by pandas, Excel, or standard tools."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8", newline="") as output_file:
        writer = csv.DictWriter(output_file, fieldnames=OUTPUT_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)


def write_quality_report(
    rows: list[dict[str, str]], report: Counter[str], report_path: Path
) -> None:
    """Write transparent quality metrics for each data-cleaning run."""
    description_lengths = sorted(len(row["Short Description"]) for row in rows)
    median_index = len(description_lengths) // 2
    payload = {
        "row_counts": dict(sorted(report.items())),
        "missing_optional_fields": {
            "Keywords": sum(not row["Keywords"] for row in rows),
            "industry": sum(not row["industry"] for row in rows),
        },
        "description_length_characters": {
            "min": description_lengths[0] if description_lengths else 0,
            "median": description_lengths[median_index] if description_lengths else 0,
            "max": description_lengths[-1] if description_lengths else 0,
        },
        "category_distribution": dict(sorted(Counter(row["Category"] for row in rows).items())),
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def parse_args() -> argparse.Namespace:
    repository_root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input",
        type=Path,
        default=repository_root / "data" / "archive.zip",
        help="ZIP archive containing the source CSV (default: data/archive.zip).",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=repository_root / "data" / "ai_tools_cleaned.csv",
        help="Destination for the cleaned CSV (default: data/ai_tools_cleaned.csv).",
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=repository_root / "data" / "ai_tools_quality_report.json",
        help="Destination for the quality report (default: data/ai_tools_quality_report.json).",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if not args.input.is_file():
        raise FileNotFoundError(f"Input archive not found: {args.input}")

    rows, report = clean_rows(load_rows(args.input))
    write_csv(rows, args.output)
    write_quality_report(rows, report, args.report)

    print(f"Wrote {report['output_rows']:,} cleaned tools to {args.output}")
    print(f"Wrote data-quality report to {args.report}")
    print(f"Removed inactive/unreachable tools: {report['removed_non_active']:,}")
    print(f"Removed tools without descriptions: {report['removed_missing_description']:,}")
    print(f"Removed duplicate source links: {report['removed_duplicate_link']:,}")
    print(f"Retained Website collisions: {report['website_collisions_retained']:,}")
    print(f"Canonicalized Website URLs: {report['canonicalized_websites']:,}")
    print(f"Short descriptions flagged for review: {report['short_descriptions_flagged']:,}")
    print(f"Duplicate descriptions flagged for review: {report['duplicate_descriptions_flagged']:,}")
    print(
        "Description/category conflicts flagged for review: "
        f"{report['description_label_conflicts_flagged']:,}"
    )
    print(f"Category labels available for modeling: {report['categories']}")


if __name__ == "__main__":
    main()
