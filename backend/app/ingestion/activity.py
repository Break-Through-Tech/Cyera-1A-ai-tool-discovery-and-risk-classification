import csv
import io

SCHEMA_VERSION = "activity-v1"

OPTIONAL_COLUMNS = ("job_role", "event_type", "usage_purpose", "data_sensitivity_tier")


def parse_activity(content: bytes) -> list[dict[str, str | None]]:
    """Normalize an uploaded activity CSV into Activity Event rows."""
    reader = csv.DictReader(io.StringIO(content.decode("utf-8")))
    events = []
    for row in reader:
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
    return events
