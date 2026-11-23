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

    Normalization is limited to spellings that cannot change meaning: header names match
    ignoring surrounding whitespace and case, and values lose surrounding whitespace (an
    optional value left empty is absent). Values are otherwise kept as supplied; the
    stored upload itself is never rewritten.

    Raises ``UploadRejected`` with every problem found; no partial result is returned.
    """
    if not content.strip():
        raise UploadRejected([_file_error("empty_upload")])
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise UploadRejected([_file_error("not_utf8")]) from None

    reader = csv.DictReader(io.StringIO(text))
    try:
        return _parse_rows(reader)
    except csv.Error:
        # The csv module's message can quote input, so only the line where parsing
        # failed is reported (DictReader's own line_num lags until a row completes).
        raise UploadRejected(
            [{"line": reader.reader.line_num, "field": None, "problem": "malformed_csv"}]
        ) from None


def _parse_rows(reader: csv.DictReader) -> list[dict[str, str | None]]:
    reader.fieldnames = [_column_name(column) for column in reader.fieldnames or []]
    header_errors = _header_errors(reader.fieldnames)
    if header_errors:
        raise UploadRejected(header_errors)

    events = []
    errors = []
    first_line_of_event: dict[str, int] = {}
    for raw_row in reader:
        line = reader.line_num
        field_count = sum(
            value is not None for key, value in raw_row.items() if key is not None
        ) + len(raw_row.get(None, []))
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
        row = {column: value.strip() for column, value in raw_row.items()}
        for column in REQUIRED_COLUMNS:
            if not row[column]:
                errors.append({"line": line, "field": column, "problem": "missing_value"})
        if row["timestamp"] and not _is_utc_z_instant(row["timestamp"]):
            errors.append(
                {"line": line, "field": "timestamp", "problem": "invalid_timestamp"}
            )
        event_id = row["event_id"]
        if event_id in first_line_of_event:
            errors.append(
                {
                    "line": line,
                    "field": "event_id",
                    "problem": "duplicate_event_id",
                    "first_line": first_line_of_event[event_id],
                }
            )
        elif event_id:
            first_line_of_event[event_id] = line
        events.append(
            {
                "event_id": event_id,
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


def _column_name(raw: str) -> str:
    return raw.strip().casefold()


def _header_errors(columns: list[str]) -> list[dict]:
    known = set(REQUIRED_COLUMNS) | set(OPTIONAL_COLUMNS)
    duplicated = [
        {"line": 1, "field": column, "problem": "duplicate_column"}
        for column in dict.fromkeys(columns)
        if column in known and columns.count(column) > 1
    ]
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
    return missing + unknown + duplicated


def _is_utc_z_instant(value: str) -> bool:
    if not _UTC_Z_TIMESTAMP.fullmatch(value):
        return False
    try:
        datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError:
        return False
    return True
