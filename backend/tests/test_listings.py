import time

import pytest

from tests.test_batches import ACTIVITY_CSV, upload


def test_batch_directory_lists_newest_upload_first_with_total(client):
    older = upload(client).json()
    time.sleep(1.1)
    newer = upload(client, ACTIVITY_CSV.replace(b"evt_", b"newer_evt_")).json()

    full = client.get("/batches").json()
    second_page = client.get("/batches", params={"limit": 1, "offset": 1}).json()

    assert full["items"] == [newer, older]
    assert full["total"] == 2
    assert second_page["items"] == [older]
    assert second_page["total"] == 2


def test_empty_batch_directory_is_a_successful_empty_page(client):
    response = client.get("/batches")

    assert response.status_code == 200
    assert response.json() == {"items": [], "total": 0, "limit": 50, "offset": 0}


def test_run_history_lists_attempts_newest_first_with_total(client):
    batch_id = upload(client).json()["batch_id"]
    client.post(f"/batches/{batch_id}/runs")
    client.post(f"/batches/{batch_id}/runs")

    page = client.get(f"/batches/{batch_id}/runs", params={"limit": 2, "offset": 1})

    assert page.status_code == 200
    body = page.json()
    assert [run["attempt_number"] for run in body["items"]] == [2, 1]
    assert body["total"] == 3
    assert (body["limit"], body["offset"]) == (2, 1)


@pytest.mark.parametrize("limit", [0, 201])
def test_page_size_outside_bounds_is_rejected(client, limit):
    response = client.get("/batches", params={"limit": limit})

    assert response.status_code == 422
    assert response.json()["code"] == "invalid_request"
    assert response.json()["details"]["errors"][0]["location"] == ["query", "limit"]


def test_unknown_query_parameter_is_rejected_not_ignored(client):
    response = client.get("/batches", params={"status": "failed", "limit": 5})

    assert response.status_code == 422
    assert response.json()["code"] == "invalid_request"
    assert response.json()["details"]["errors"] == [
        {"location": ["query", "status"], "problem": "unknown_parameter"}
    ]


def test_run_history_of_unknown_batch_returns_not_found(client):
    response = client.get("/batches/bat_missing/runs")

    assert response.status_code == 404
    assert response.json()["code"] == "batch_not_found"
