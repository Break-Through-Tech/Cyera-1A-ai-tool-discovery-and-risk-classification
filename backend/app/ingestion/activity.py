import csv
import io
import re
from datetime import datetime

SCHEMA_VERSION = "activity-v1"

# Second precision only, so stored timestamps share one width and sort as text.
_UTC_Z_TIMESTAMP = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z")

REQUIRED_COLUMNS = (
    "event_id",
    "timestamp",
    "employee_id",
    "department",
    "application_name",
    "domain",
)
OPTIONAL_COLUMNS = ("job_role", "event_type", "usage_purpose", "data_sensitivity_tier")


class UploadRejected(Exception):
    """The upload is invalid as a whole; ``errors`` locate each problem by line and field."""

    def __init__(self, errors: list[dict]) -> None:
        super().__init__(f"{len(errors)} validation error(s)")
        self.errors = errors


def parse_activity(content: bytes) -> list[dict[str, str | None]]:
    """Validate and normalize an uploaded activity CSV into Activity Event rows.

    Raises ``UploadRejected`` with every problem found; no partial result is returned.
    """
    if not content.strip():
        raise UploadRejected([_file_error("empty_upload")])
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise UploadRejected([_file_error("not_utf8")]) from None

    reader = csv.DictReader(io.StringIO(text))
    header_errors = _header_errors(reader.fieldnames or [])
    if header_errors:
        raise UploadRejected(header_errors)

    events = []
    errors = []
    first_line_of_event: dict[str, int] = {}
    for row in reader:
        line = reader.line_num
        field_count = sum(
            value is not None for key, value in row.items() if key is not None
        ) + len(row.get(None, []))
        if field_count != len(reader.fieldnames):
            errors.append(
                {
                    "line": line,
                    "field": None,
                    "problem": "wrong_field_count",
                    "expected": len(reader.fieldnames),
                    "actual": field_count,
                }
            )
            continue
        for column in REQUIRED_COLUMNS:
            if not (row.get(column) or "").strip():
                errors.append({"line": line, "field": column, "problem": "missing_value"})
        timestamp = row.get("timestamp") or ""
        if timestamp.strip() and not _is_utc_z_instant(timestamp):
            errors.append(
                {"line": line, "field": "timestamp", "problem": "invalid_timestamp"}
            )
        event_id = row.get("event_id") or ""
        if event_id in first_line_of_event:
            errors.append(
                {
                    "line": line,
                    "field": "event_id",
                    "problem": "duplicate_event_id",
                    "first_line": first_line_of_event[event_id],
                }
            )
        elif event_id.strip():
            first_line_of_event[event_id] = line
        events.append(
            {
                "event_id": row["event_id"],
                "occurred_at": row["timestamp"],
                "employee_id": row["employee_id"],
                "department": row["department"],
                "application_name": row["application_name"],
                "domain": row["domain"],
                **{column: row.get(column) or None for column in OPTIONAL_COLUMNS},
            }
        )
    if errors:
        raise UploadRejected(errors)
    if not events:
        raise UploadRejected([_file_error("no_events")])
    return events


def _file_error(problem: str) -> dict:
    return {"line": None, "field": None, "problem": problem}


def _header_errors(columns: list[str]) -> list[dict]:
    known = set(REQUIRED_COLUMNS) | set(OPTIONAL_COLUMNS)
    missing = [
        {"line": 1, "field": column, "problem": "missing_column"}
        for column in REQUIRED_COLUMNS
        if column not in columns
    ]
    unknown = [
        {"line": 1, "field": column, "problem": "unknown_column"}
        for column in columns
        if column not in known
    ]
    return missing + unknown


def _is_utc_z_instant(value: str) -> bool:
    if not _UTC_Z_TIMESTAMP.fullmatch(value):
        return False
    try:
        datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError:
        return False
    return True
