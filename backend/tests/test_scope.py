import csv

import pytest
from sqlalchemy import insert

from app.config import Settings
from app.db.tables import analysis_runs
from app.pipeline import Phase, Pipeline
from app.scope import CATEGORIES
from tests.test_batches import ACTIVITY_CSV, upload
from tests.test_runs import failing

OTHER_CSV = ACTIVITY_CSV.replace(b"evt_", b"other_evt_")


def scope_of(client, **params):
    response = client.get("/overview", params=params)
    assert response.status_code == 200, response.json()
    return response.json()["scope"]


def selections(scope):
    return {(s["batch_id"], s["run_id"]) for s in scope["selections"]}


def warnings(scope, code):
    return [w for w in scope["coverage"]["warnings"] if w["code"] == code]


def error_of(response):
    return response.status_code, response.json()["code"], response.json().get("details")


def test_empty_storage_is_an_empty_scoped_result(client):
    response = client.get("/overview")

    assert response.status_code == 200
    body = response.json()
    scope = body["scope"]
    assert scope["selections"] == []
    assert scope["coverage"]["state"] == "no_batches"
    assert [w["code"] for w in scope["coverage"]["warnings"]] == ["no_batches"]
    assert scope["event_time"] == {
        "start": None,
        "end": None,
        "observed": {"first": None, "last": None},
    }
    assert set(body["headline"].values()) == {0}
    assert body["trend"] == {"bucket": None, "points": []}


def test_each_batch_contributes_its_latest_successful_run(client):
    first = upload(client).json()
    other = upload(client, OTHER_CSV).json()
    rerun = client.post(f"/batches/{first['batch_id']}/runs").json()

    scope = scope_of(client)

    assert selections(scope) == {
        (first["batch_id"], rerun["run_id"]),
        (other["batch_id"], other["latest_run"]["run_id"]),
    }
    assert scope["coverage"]["state"] == "available"
    assert {b["selected_by"] for b in scope["coverage"]["batches"]} == {"latest_success"}


def test_a_newer_failed_attempt_is_disclosed_without_replacing_the_success(make_client):
    calls = []

    def fail_after_first_run(_context):
        calls.append(None)
        if len(calls) > 1:
            raise RuntimeError("model unavailable")

    client = make_client(Phase("detect", fail_after_first_run))
    batch = upload(client).json()
    failed = client.post(f"/batches/{batch['batch_id']}/runs").json()

    scope = scope_of(client)

    assert selections(scope) == {(batch["batch_id"], batch["latest_run"]["run_id"])}
    [warning] = warnings(scope, "newer_attempt_not_succeeded")
    assert warning["batch_id"] == batch["batch_id"]
    assert warning["run_id"] == failed["run_id"]
    assert warning["details"] == {"status": "failed"}
    [coverage] = scope["coverage"]["batches"]
    assert coverage["latest_attempt"]["status"] == "failed"
    assert coverage["selected_run"]["run_id"] == batch["latest_run"]["run_id"]


def test_a_running_attempt_is_disclosed(client):
    batch = upload(client).json()
    with client.app.state.engine.begin() as connection:
        connection.execute(
            insert(analysis_runs).values(
                run_id="run_in_progress",
                batch_id=batch["batch_id"],
                attempt_number=2,
                status="running",
                started_at="2026-11-23T00:00:00Z",
                versions={},
            )
        )

    scope = scope_of(client)

    assert selections(scope) == {(batch["batch_id"], batch["latest_run"]["run_id"])}
    [warning] = warnings(scope, "newer_attempt_not_succeeded")
    assert warning["run_id"] == "run_in_progress"
    assert warning["details"] == {"status": "running"}


def test_a_batch_without_a_successful_run_contributes_no_findings(make_client):
    client = make_client(failing("classify"))
    batch = upload(client).json()

    scope = scope_of(client)

    assert scope["selections"] == []
    assert scope["coverage"]["state"] == "no_successful_runs"
    [warning] = warnings(scope, "no_successful_run")
    assert warning["batch_id"] == batch["batch_id"]
    assert warning["run_id"] == batch["latest_run"]["run_id"]
    assert scope["coverage"]["batches"][0]["selected_by"] is None


def test_run_ids_pin_an_earlier_run_and_limit_the_scope(client):
    first = upload(client).json()
    upload(client, OTHER_CSV)
    earlier = first["latest_run"]["run_id"]
    newer = client.post(f"/batches/{first['batch_id']}/runs").json()["run_id"]

    scope = scope_of(client, run_ids=[earlier])

    assert selections(scope) == {(first["batch_id"], earlier)}
    assert scope["filters"]["run_ids"] == [earlier]
    assert scope["coverage"]["batches"][0]["selected_by"] == "pinned"
    [warning] = warnings(scope, "newer_successful_run")
    assert warning["run_id"] == newer


def test_batch_ids_restrict_the_scope_and_unpinned_batches_use_their_latest_success(client):
    first = upload(client).json()
    other = upload(client, OTHER_CSV).json()
    upload(client, ACTIVITY_CSV.replace(b"evt_", b"third_evt_"))
    earlier = first["latest_run"]["run_id"]
    client.post(f"/batches/{first['batch_id']}/runs")

    only = scope_of(client, batch_ids=[other["batch_id"]])
    mixed = scope_of(client, batch_ids=[first["batch_id"], other["batch_id"]], run_ids=[earlier])

    assert selections(only) == {(other["batch_id"], other["latest_run"]["run_id"])}
    assert selections(mixed) == {
        (first["batch_id"], earlier),
        (other["batch_id"], other["latest_run"]["run_id"]),
    }


def test_unknown_references_are_not_found(client):
    batch = upload(client).json()

    missing_batch = client.get("/overview", params={"batch_ids": [batch["batch_id"], "bat_missing"]})
    missing_run = client.get("/overview", params={"run_ids": ["run_missing"]})

    assert error_of(missing_batch) == (
        404,
        "batch_not_found",
        {"errors": [{"location": ["query", "batch_ids", 1], "problem": "not_found"}]},
    )
    assert error_of(missing_run)[:2] == (404, "run_not_found")


def test_a_pinned_run_that_did_not_succeed_conflicts(make_client):
    client = make_client(failing("classify"))
    run_id = upload(client).json()["latest_run"]["run_id"]

    response = client.get("/overview", params={"run_ids": [run_id]})

    assert error_of(response) == (
        409,
        "run_not_succeeded",
        {"errors": [{"location": ["query", "run_ids", 0], "problem": "not_succeeded"}]},
    )


def test_contradictory_scopes_are_rejected(client):
    first = upload(client).json()
    other = upload(client, OTHER_CSV).json()
    newer = client.post(f"/batches/{first['batch_id']}/runs").json()["run_id"]
    earlier = first["latest_run"]["run_id"]

    two_of_one_batch = client.get("/overview", params={"run_ids": [earlier, newer]})
    outside = client.get(
        "/overview", params={"batch_ids": [other["batch_id"]], "run_ids": [earlier]}
    )

    assert error_of(two_of_one_batch) == (
        422,
        "invalid_request",
        {"errors": [{"location": ["query", "run_ids", 1], "problem": "multiple_runs_for_batch"}]},
    )
    assert error_of(outside) == (
        422,
        "invalid_request",
        {"errors": [{"location": ["query", "run_ids", 0], "problem": "outside_selected_batches"}]},
    )


@pytest.mark.parametrize(
    ("params", "location"),
    [
        ({"risk_tiers": "Critical"}, ["query", "risk_tiers", 0]),
        ({"policy_statuses": "pending"}, ["query", "policy_statuses", 0]),
        ({"categories": "Coding Assistant"}, ["query", "categories", 0]),
        ({"flagged": "maybe"}, ["query", "flagged"]),
        ({"departments": ""}, ["query", "departments", 0]),
        ({"start": "yesterday"}, ["query", "start"]),
        ({"start": "2026-09-15T00:00:00"}, ["query", "start"]),
        ({"end": "2026-09-15T00:00:00+02:00"}, ["query", "end"]),
        ({"start": "2026-09-16T00:00:00Z", "end": "2026-09-16T00:00:00Z"}, ["query", "end"]),
        ({"department": "Sales"}, ["query", "department"]),
    ],
)
def test_invalid_filters_are_rejected(client, params, location):
    upload(client)

    response = client.get("/overview", params=params)

    assert response.status_code == 422
    assert response.json()["code"] == "invalid_request"
    assert location in [error["location"] for error in response.json()["details"]["errors"]]


def test_a_valid_filter_without_matches_is_an_empty_result(client):
    upload(client)

    body = client.get("/overview", params={"departments": "Nobody"}).json()

    assert body["scope"]["filters"]["departments"] == ["Nobody"]
    assert body["scope"]["coverage"]["state"] == "available"
    assert set(body["headline"].values()) == {0}


def test_event_time_bounds_are_reported_as_whole_utc_seconds(client):
    upload(client)

    scope = scope_of(
        client, start="2026-09-15T00:00:00.000Z", end="2026-09-16T12:00:00.250+00:00"
    )

    assert scope["event_time"]["start"] == "2026-09-15T00:00:00Z"
    assert scope["event_time"]["end"] == "2026-09-16T12:00:01Z"


def test_material_version_differences_are_disclosed(client):
    upload(client)
    client.app.state.pipeline = Pipeline(
        phases=(), versions={"ai_detector": "test-detector-1", "risk_rules": "test-rules-2"}
    )
    upload(client, OTHER_CSV)

    [warning] = warnings(scope_of(client), "version_differences")

    assert warning["details"] == {"versions": ["risk_rules"]}


def test_runs_without_saved_stage_results_are_disclosed(client):
    batch = upload(client).json()

    [warning] = warnings(scope_of(client), "run_without_stage_results")

    assert warning["run_id"] == batch["latest_run"]["run_id"]


def test_category_filter_values_are_the_catalog_categories():
    with Settings(data_dir=None).catalog_path.open(encoding="utf-8", newline="") as stream:
        catalog = {row["Category"] for row in csv.DictReader(stream)}

    assert set(CATEGORIES) == catalog
