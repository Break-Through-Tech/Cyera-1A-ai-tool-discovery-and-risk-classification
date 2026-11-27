"""Validate the cleaned AIToolBuzz schema and preserve citable listing text."""

import csv
import io
import json
import re
from dataclasses import asdict
from hashlib import sha256
from urllib.parse import urlsplit

from .corpus import CatalogMetadata, Passage


COLUMNS = (
    "tool_id", "Name", "Website", "Category", "Primary Task", "Short Description",
    "Keywords", "industry", "text_quality_flag", "duplicate_description_flag",
    "description_label_conflict_flag",
)
REQUIRED = COLUMNS[:6]
FLAGS = {
    "text_quality_flag": {"ok", "review_short"},
    "duplicate_description_flag": {"ok", "review_duplicate"},
    "description_label_conflict_flag": {"ok", "review_label_conflict"},
}
TOOL_ID = re.compile(r"[0-9a-f]{64}")


def digest_json(value) -> str:
    """Fingerprint a JSON value independently of mapping insertion order."""
    return sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


def load_catalog(data: bytes, source_path: str) -> tuple[Passage, ...]:
    """Validate the entire CSV before yielding any eligible catalog evidence."""
    reader = csv.DictReader(io.StringIO(data.decode("utf-8-sig"), newline=""), strict=True)
    if tuple(reader.fieldnames or ()) != COLUMNS:
        raise ValueError("Unexpected cleaned catalog CSV columns.")
    passages = []
    seen_ids = set()
    for number, row in enumerate(reader, 1):
        if set(row) != set(COLUMNS) or any(value is None for value in row.values()):
            raise ValueError(f"Malformed catalog record {number}.")
        for field in REQUIRED:
            if not row[field].strip():
                raise ValueError(f"Catalog record {number} is missing {field}.")
        tool_id = row["tool_id"]
        if not TOOL_ID.fullmatch(tool_id):
            raise ValueError(f"Invalid tool ID in catalog record {number}.")
        if tool_id in seen_ids:
            raise ValueError(f"Duplicate tool ID in catalog record {number}.")
        seen_ids.add(tool_id)
        for field, allowed in FLAGS.items():
            if row[field] not in allowed:
                raise ValueError(f"Invalid {field} in catalog record {number}.")
        website = row["Website"].strip()
        try:
            url = urlsplit(website)
            hostname = url.hostname
            if url.scheme not in {"http", "https"} or not hostname or url.username is not None:
                raise ValueError
        except ValueError:
            raise ValueError(f"Invalid website URL in catalog record {number}.") from None

        metadata = CatalogMetadata(
            f"aitoolbuzz:{tool_id}", tool_id, website, hostname,
            row["Category"].strip(), row["Primary Task"].strip(),
            row["Keywords"].strip() or None, row["industry"].strip() or None,
            *(row[field] for field in FLAGS),
        )
        heading, description = row["Name"].strip(), row["Short Description"]
        passages.append(Passage(
            digest_json([metadata.record_id, "description"])[:16],
            source_path, heading, "tool_evidence",
            digest_json([heading, description, asdict(metadata)]), description, metadata,
        ))
    return tuple(passages)


def catalog_details(metadata: CatalogMetadata) -> str:
    return "\n".join(
        f"{key.replace('_', ' ').capitalize()}: {value}"
        for key, value in asdict(metadata).items()
        if value is not None
    )
