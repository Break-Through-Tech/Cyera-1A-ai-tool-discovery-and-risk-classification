from datetime import UTC, datetime


def utc_now() -> str:
    """The current time in the stored `YYYY-MM-DDTHH:MM:SSZ` form."""
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
