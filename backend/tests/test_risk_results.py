from sqlalchemy import func, select

from app.db.tables import usage_context_assessments
from app.pipeline import Phase, Pipeline
from tests.test_default_pipeline import (
    EverythingNotFound,
    fixture_client,
    unavailable_jev,
    upload_fixture,
)
from tests.test_enrichment_fetch import html


class ServesEveryHomepage(EverythingNotFound):
    """Every Tool has a homepage, so the fake judge calls each one AI."""

    def get(self, destination):
        self.requested.append((destination.url, destination.addresses))
        return html()


def analyzed(data_dir):
    client = fixture_client(data_dir, http=ServesEveryHomepage())
    run = upload_fixture(client).json()["latest_run"]
    assert run["status"] == "succeeded"
    return client, run["run_id"]


def test_a_succeeded_run_returns_its_saved_usage_context_assessments(data_dir):
    client, run_id = analyzed(data_dir)

    page = client.get(f"/runs/{run_id}/assessments").json()

    assert page["total"] == len(page["items"]) > 0
    assert [item["context_number"] for item in page["items"]] == list(
        range(1, page["total"] + 1)
    )
    chatgpt = [item for item in page["items"] if item["application_name"] == "ChatGPT"]
    assert {(item["department"], item["tier"]) for item in chatgpt} == {
        ("Engineering", "Lower"),
        ("Finance", "Lower"),
    }
    engineering = next(item for item in chatgpt if item["department"] == "Engineering")
    assert engineering["event_count"] == len(engineering["event_ids"]) == 62
    assert engineering["facts"] == {
        "policy_status": "approved",
        "training_on_customer_data": "no",
        "admin_controls_available": "yes",
    }
    assert engineering["metadata_id"] == "meta_01"
    assert engineering["investigation_flag"] is False
    assert engineering["rule_version"] == "synthetic-demo-risk-v1"
    assert engineering["domain"] == "chatgpt.com"
    assert engineering["first_observed_at"] <= engineering["last_observed_at"]


def test_results_filter_by_tier_and_flag(data_dir):
    client, run_id = analyzed(data_dir)
    everything = client.get(f"/runs/{run_id}/assessments").json()["items"]

    lower = client.get(f"/runs/{run_id}/assessments", params={"tier": "Lower"}).json()
    flagged = client.get(f"/runs/{run_id}/assessments", params={"flagged": "true"}).json()

    assert lower["total"] == sum(item["tier"] == "Lower" for item in everything) > 0
    assert all(item["tier"] == "Lower" for item in lower["items"])
    assert flagged["total"] == sum(item["investigation_flag"] for item in everything) > 0
    assert all(item["investigation_flag"] for item in flagged["items"])


def test_results_page(data_dir):
    client, run_id = analyzed(data_dir)

    page = client.get(f"/runs/{run_id}/assessments", params={"limit": 2, "offset": 1}).json()

    assert [item["context_number"] for item in page["items"]] == [2, 3]
    assert page["limit"] == 2 and page["offset"] == 1


def test_an_older_run_keeps_its_own_results_after_reanalysis(data_dir):
    client, first_run = analyzed(data_dir)
    batch_id = client.get(f"/runs/{first_run}").json()["batch_id"]
    before = client.get(f"/runs/{first_run}/assessments").json()

    second_run = client.post(f"/batches/{batch_id}/runs").json()["run_id"]

    assert client.get(f"/runs/{first_run}/assessments").json() == before
    assert client.get(f"/runs/{second_run}/assessments").json()["total"] == before["total"]


def test_unknown_run_is_not_found(data_dir):
    client, _ = analyzed(data_dir)

    response = client.get("/runs/run_missing/assessments")

    assert response.status_code == 404
    assert response.json()["code"] == "run_not_found"


def test_a_failed_run_has_no_results(data_dir):
    client = fixture_client(data_dir, jev=unavailable_jev)
    run = upload_fixture(client).json()["latest_run"]

    response = client.get(f"/runs/{run['run_id']}/assessments")

    assert run["status"] == "failed"
    assert response.status_code == 409
    assert response.json()["code"] == "run_not_succeeded"


def test_an_invalid_tier_is_rejected(data_dir):
    client, run_id = analyzed(data_dir)

    response = client.get(f"/runs/{run_id}/assessments", params={"tier": "Critical"})

    assert response.status_code == 422


SAVED_ROW = {
    "context_number": 1,
    "tool_id": "tool:x",
    "application_name": "X",
    "domain": "x.example",
    "department": "Sales",
    "usage_purpose": "notes",
    "data_sensitivity_tier": "internal",
    "event_ids": ["e1"],
    "event_count": 1,
    "first_observed_at": "2026-09-15T00:00:00Z",
    "last_observed_at": "2026-09-15T00:00:00Z",
    "facts": {},
    "tier": "unresolved",
    "reason_codes": [],
    "unknown_facts": [],
    "investigation_flag": True,
    "flag_reasons": [],
    "rule_version": "test",
}


def test_a_save_failure_fails_the_run_and_leaves_no_rows(make_client):
    def broken_save(connection, context):
        connection.execute(usage_context_assessments.insert().values(SAVED_ROW, run_id=context.run_id))
        raise OSError("disk full")

    client = make_client()
    client.app.state.pipeline = Pipeline(
        phases=(Phase("noop", lambda context: None),), save=broken_save
    )

    run = upload_fixture(client).json()["latest_run"]

    assert run["status"] == "failed"
    assert run["failure"] == {
        "summary": "Analysis failed while saving its results.",
        "phase": "save_results",
    }
    with client.app.state.engine.connect() as connection:
        rows = connection.execute(
            select(func.count()).select_from(usage_context_assessments)
        ).scalar_one()
    assert rows == 0
