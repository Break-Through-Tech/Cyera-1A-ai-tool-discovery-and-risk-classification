"""Join fetched homepages to catalog Categories to measure transfer from catalog descriptions."""

from __future__ import annotations

import csv
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path

from prepare_dataset import SOURCE, host_key


ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data/category_classification/v1"
OUT = ROOT / "data/category_classification/transfer_v1"
CAPTURES = (
    ROOT / "notebooks/ai_cascade/pool/captures.jsonl",
    ROOT / "notebooks/website_feasibility/captures/results.jsonl",
)
EXCLUSIONS = ROOT / "backend/config/known_tool_registry_exclusions.json"


def catalog_by_host() -> dict[str, list[dict[str, str]]]:
    hosts: dict[str, list[dict[str, str]]] = defaultdict(list)
    with SOURCE.open(encoding="utf-8", newline="") as stream:
        for row in csv.DictReader(stream):
            if host := host_key(row["Website"]):
                hosts[host].append(row)
    return hosts


def split_of_tool() -> dict[str, str]:
    splits = {}
    for name in ("train", "validation", "test"):
        with (DATA / f"{name}.csv").open(encoding="utf-8", newline="") as stream:
            splits.update({row["tool_id"]: name for row in csv.DictReader(stream)})
    return splits


def page_fields(capture: dict) -> dict[str, str]:
    """The same four homepage fields the backend judges, kept apart so views can be compared."""
    metadata = capture.get("metadata") or {}
    return {
        "title": capture.get("title") or "",
        "meta_description": metadata.get("description") or metadata.get("og:description") or "",
        "headings": " | ".join(capture.get("headings") or []),
        "body": capture.get("main_text") or "",
    }


def main() -> None:
    hosts = catalog_by_host()
    splits = split_of_tool()
    counts: Counter[str] = Counter()
    pages: dict[str, dict] = {}
    for path in CAPTURES:
        for line in path.open(encoding="utf-8"):
            capture = json.loads(line)
            counts["captures"] += 1
            if capture.get("outcome") != "extracted":
                counts["not_extracted"] += 1
                continue
            host = host_key(capture["url"])
            tools = hosts.get(host)
            if not tools:
                counts["host_not_in_catalog"] += 1
                continue
            if len({tool["Category"] for tool in tools}) > 1:
                counts["host_with_conflicting_categories"] += 1
                continue
            fields = page_fields(capture)
            if not any(fields.values()):
                counts["empty_page_text"] += 1
                continue
            text_chars = sum(len(value) for value in fields.values())
            if host in pages:
                counts["duplicate_host_capture"] += 1
                if pages[host]["text_chars"] >= text_chars:
                    continue
            tool_splits = sorted({splits.get(tool["tool_id"], "excluded") for tool in tools})
            pages[host] = {
                "host": host,
                "tool_ids": sorted(tool["tool_id"] for tool in tools),
                "names": sorted(tool["Name"] for tool in tools),
                "category": tools[0]["Category"],
                "catalog_split": tool_splits[0] if len(tool_splits) == 1 else "mixed",
                "capture_file": str(path.relative_to(ROOT)),
                "capture_source": capture["source"],
                "final_url": capture.get("final_url") or capture["url"],
                **fields,
                "text_chars": text_chars,
            }

    rows = sorted(pages.values(), key=lambda row: row["host"])
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / "pages.jsonl"
    path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")

    held_out = set(json.loads(EXCLUSIONS.read_text(encoding="utf-8"))["excluded_tool_ids"])
    by_split = Counter(row["catalog_split"] for row in rows)
    summary = {
        "pages_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "join": "capture url host_key == catalog Website host_key; hosts whose catalog rows disagree on Category dropped",
        "counts": dict(counts) | {"pages": len(rows)},
        "pages_by_catalog_split": dict(by_split),
        "category_support_by_split": {
            split: dict(Counter(row["category"] for row in rows if row["catalog_split"] == split))
            for split in sorted(by_split)
        },
        "capture_source": dict(Counter(row["capture_source"] for row in rows)),
        "pages_with_body_under_200_chars": sum(len(row["body"]) < 200 for row in rows),
        "registry_held_out_tools_present": sorted(
            row["host"] for row in rows if held_out & set(row["tool_ids"])
        ),
    }
    (OUT / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
