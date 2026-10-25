import hashlib

ACTIVITY_CSV = (
    b"event_id,timestamp,employee_id,department,job_role,application_name,domain,"
    b"event_type,usage_purpose,data_sensitivity_tier\n"
    b"evt_2,2026-09-16T10:00:00Z,emp_2,Support,Agent,Slack,slack.com,app_open,"
    b"team_messaging,internal\n"
    b"evt_1,2026-09-15T07:39:00Z,emp_1,Engineering,Engineer,Cursor,cursor.so,app_open,"
    b"software_development,internal\n"
    b"evt_3,2026-09-15T12:00:00Z,emp_1,Engineering,Engineer,ChatGPT,chatgpt.com,"
    b"browser_visit,,\n"
)


def upload(client, content: bytes = ACTIVITY_CSV, filename: str = "activity.csv"):
    return client.post("/batches", files={"file": (filename, content, "text/csv")})


def test_valid_upload_creates_batch_with_activity_period_and_event_count(client):
    response = upload(client)

    assert response.status_code == 201
    batch = response.json()
    assert batch["batch_id"]
    assert batch["original_filename"] == "activity.csv"
    assert batch["sha256"] == hashlib.sha256(ACTIVITY_CSV).hexdigest()
    assert batch["event_count"] == 3
    assert batch["activity_period"] == {
        "start": "2026-09-15T07:39:00Z",
        "end": "2026-09-16T10:00:00Z",
    }


def test_batch_survives_application_restart(make_client):
    created = upload(make_client()).json()

    response = make_client().get(f"/batches/{created['batch_id']}")

    assert response.status_code == 200
    assert response.json() == created


def test_byte_identical_upload_reopens_existing_batch(client):
    created = upload(client).json()

    response = upload(client, filename="renamed-copy.csv")

    assert response.status_code == 200
    assert response.json() == created


def test_unknown_batch_returns_not_found(client):
    response = client.get("/batches/bat_missing")

    assert response.status_code == 404
    assert response.json()["code"] == "batch_not_found"
