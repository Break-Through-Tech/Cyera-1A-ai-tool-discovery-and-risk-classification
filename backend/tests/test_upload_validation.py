import pytest

from tests.test_batches import upload

HEADER = (
    "event_id,timestamp,employee_id,department,job_role,application_name,domain,"
    "event_type,usage_purpose,data_sensitivity_tier"
)
VALID_ROW = "evt_1,2026-09-15T07:39:00Z,emp_1,Engineering,Engineer,Cursor,cursor.so,app_open,,"


def csv_bytes(*lines: str, header: str = HEADER) -> bytes:
    return ("\n".join([header, *lines]) + "\n").encode()


def assert_rejected(client, content: bytes, expected_errors: list[dict]) -> None:
    for _attempt in range(2):
        response = upload(client, content)

        assert response.status_code == 422
        body = response.json()
        assert body["code"] == "invalid_upload"
        assert body["details"]["errors"] == expected_errors


def test_missing_required_value_rejects_whole_upload(client):
    content = csv_bytes(
        VALID_ROW,
        "evt_2,2026-09-15T08:00:00Z,emp_2,,Agent,Slack,slack.com,app_open,,",
    )

    assert_rejected(
        client,
        content,
        [{"line": 3, "field": "department", "problem": "missing_value"}],
    )


def test_timestamps_must_be_real_utc_z_instants(client):
    content = csv_bytes(
        VALID_ROW,
        "evt_2,2026-09-15T08:00:00+02:00,emp_2,Support,,Slack,slack.com,,,",
        "evt_3,2026-09-15 08:00:00,emp_2,Support,,Slack,slack.com,,,",
        "evt_4,2026-02-30T08:00:00Z,emp_2,Support,,Slack,slack.com,,,",
    )

    assert_rejected(
        client,
        content,
        [
            {"line": line, "field": "timestamp", "problem": "invalid_timestamp"}
            for line in (3, 4, 5)
        ],
    )


@pytest.mark.parametrize(
    ("content", "problem"),
    [
        (b"", "empty_upload"),
        (csv_bytes(), "no_events"),
        (csv_bytes(VALID_ROW).replace(b"Cursor", b"Caf\xe9"), "not_utf8"),
    ],
    ids=["empty", "header-only", "latin-1"],
)
def test_file_level_problems_have_no_line(client, content, problem):
    assert_rejected(client, content, [{"line": None, "field": None, "problem": problem}])


def test_request_without_file_uses_application_error_body(client):
    response = client.post("/batches", data={"note": "no file"})

    assert response.status_code == 422
    assert response.json()["code"] == "invalid_request"
    assert response.json()["details"]["errors"] == [
        {"location": ["body", "file"], "problem": "missing"}
    ]


def test_utf8_byte_order_mark_is_accepted(client):
    response = upload(client, b"\xef\xbb\xbf" + csv_bytes(VALID_ROW))

    assert response.status_code == 201


def test_missing_and_unknown_columns_are_reported_once_on_the_header(client):
    content = csv_bytes(
        "evt_1,2026-09-15T07:39:00Z,emp_1,Engineering,Cursor,secret",
        "evt_2,2026-09-15T08:00:00Z,emp_2,Support,Slack,secret",
        header="event_id,timestamp,employee_id,department,application_name,notes",
    )

    assert_rejected(
        client,
        content,
        [
            {"line": 1, "field": "domain", "problem": "missing_column"},
            {"line": 1, "field": "notes", "problem": "unknown_column"},
        ],
    )


def test_rows_with_too_few_or_too_many_fields_get_one_error_each(client):
    content = csv_bytes(
        VALID_ROW,
        "evt_2,2026-09-15T08:00:00Z,emp_2,Support,,Slack",
        "evt_3,2026-09-15T08:00:00Z,emp_2,Support,,Slack,Inc.,slack.com,,,",
    )

    assert_rejected(
        client,
        content,
        [
            {"line": 3, "field": None, "problem": "wrong_field_count", "expected": 10, "actual": 6},
            {"line": 4, "field": None, "problem": "wrong_field_count", "expected": 10, "actual": 11},
        ],
    )


def test_duplicate_event_id_is_reported_against_its_first_line(client):
    content = csv_bytes(
        VALID_ROW,
        "evt_2,2026-09-15T08:00:00Z,emp_2,Support,,Slack,slack.com,,,",
        "evt_1,2026-09-15T09:00:00Z,emp_3,Sales,,Slack,slack.com,,,",
    )

    assert_rejected(
        client,
        content,
        [
            {
                "line": 4,
                "field": "event_id",
                "problem": "duplicate_event_id",
                "first_line": 2,
            }
        ],
    )
