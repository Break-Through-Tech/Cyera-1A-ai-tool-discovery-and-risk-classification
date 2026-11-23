import pytest

from app.api.pagination import MAX_PAGE_SIZE
from app.scope import RISK_TIERS
from tests.test_applications_inventory import analyzed, inventory, overview
from tests.test_default_pipeline import fixture_client, unavailable_jev, upload_fixture
from tests.test_identity_fixture import FIXTURE


def contexts(client, **params):
    response = client.get("/contexts", params={"limit": MAX_PAGE_SIZE, **params})
    assert response.status_code == 200, response.json()
    return response.json()


def events_total(client, **params):
    response = client.get("/events", params={"limit": 1, **params})
    assert response.status_code == 200, response.json()
    return response.json()["total"]


def order_key(item):
    return (RISK_TIERS.index(item["tier"]), item["run_id"], item["context_number"])


def assessments(client, run_id):
    return {
        a["context_number"]: a
        for a in client.get(f"/runs/{run_id}/assessments", params={"limit": 200}).json()["items"]
    }


def test_contexts_list_every_matching_context_in_a_stable_order(data_dir):
    client = analyzed(data_dir)

    body = contexts(client)
    pages = [
        client.get("/contexts", params={"limit": 4, "offset": offset}).json()
        for offset in (0, 4, 8)
    ]

    items = body["items"]
    view = overview(client)
    assert body["total"] == len(items) == sum(view["risk_distribution"].values()) == 11
    assert items == sorted(items, key=order_key)
    assert [item for page in pages for item in page["items"]] == items
    assert {page["total"] for page in pages} == {11}
    assert all(item["matching_events"] == item["event_count"] for item in items)
    assert sum(item["event_count"] for item in items) == view["headline"]["ai_positive_events"]
    assert {"contexts", "contexts.matching_events", "matching_contexts"} <= set(
        body["scope"]["count_definitions"]
    )
    stored = assessments(client, items[0]["run_id"])
    for item in items:
        saved = stored[item["context_number"]]
        assert item["policy_status"] == saved["facts"]["policy_status"]
        assert {k: item[k] for k in item if k in saved} == {k: saved[k] for k in item if k in saved}


@pytest.mark.parametrize(
    "filters",
    [
        {"departments": "Engineering"},
        {"departments": ["Engineering", "Sales"], "flagged": "true"},
        {"risk_tiers": "Medium", "categories": "unresolved"},
        {"policy_statuses": "unknown"},
        {"start": "2026-10-01T00:00:00Z", "end": "2026-10-08T00:00:00Z"},
        {"categories": "inapplicable"},
    ],
)
def test_context_counts_agree_with_the_overview(data_dir, filters):
    client = analyzed(data_dir)

    body = contexts(client, **filters)
    view = overview(client, **filters)

    tiers = {tier: sum(i["tier"] == tier for i in body["items"]) for tier in RISK_TIERS}
    assert tiers == view["risk_distribution"]
    assert body["total"] == sum(tiers.values())
    flagged = sum(i["investigation_flag"] for i in body["items"])
    assert flagged == view["headline"]["flagged_contexts"]
    statuses = view["policy_status_distribution"]
    assert {s: sum(i["policy_status"] == s for i in body["items"]) for s in statuses} == statuses
    assert sum(i["matching_events"] for i in body["items"]) == events_total(
        client, **filters, ai_determinations="ai"
    )


def test_combined_filters_must_match_the_same_usage_context(data_dir):
    client = analyzed(data_dir)

    mismatched = contexts(client, departments="Finance", risk_tiers="Medium")
    lower = contexts(client, departments="Engineering", risk_tiers="Lower")
    flagged = contexts(client, departments="Engineering", flagged="true")

    assert (mismatched["items"], mismatched["total"]) == ([], 0)
    assert sorted(i["application_name"] for i in lower["items"]) == ["ChatGPT", "Magic Inspector"]
    assert all(
        (i["department"], i["tier"]) == ("Engineering", "Lower") for i in lower["items"]
    )
    assert [i["application_name"] for i in flagged["items"]] == ["Cursor"]


def test_an_event_time_window_counts_only_the_contexts_matching_events(data_dir):
    client = analyzed(data_dir)
    window = {"start": "2026-10-01T00:00:00Z", "end": "2026-10-08T00:00:00Z"}

    body = contexts(client, **window)

    assert 0 < body["total"] < 11
    assert any(i["matching_events"] < i["event_count"] for i in body["items"])
    for item in body["items"]:
        assert 0 < item["matching_events"] == events_total(
            client, **window, run_ids=item["run_id"], context_number=item["context_number"]
        )


def test_tool_ids_narrow_an_application_row_to_its_contexts(data_dir):
    client = analyzed(data_dir)
    rows = inventory(client, departments="Engineering", ai_determinations="ai")["items"]

    for row in rows:
        body = contexts(
            client, departments="Engineering", run_ids=row["run_id"], tool_ids=row["subject_id"]
        )
        assert sorted(i["context_number"] for i in body["items"]) == row["matching_context_numbers"]
        assert sum(i["matching_events"] for i in body["items"]) == row["matching_events"]
        assert body["context_filters"] == {"tool_ids": [row["subject_id"]]}
    assert contexts(client, tool_ids="tool:missing")["total"] == 0


def test_contexts_of_several_batches_are_per_run(data_dir):
    original = FIXTURE.read_bytes()
    client = analyzed(data_dir, original, original.replace(b"evt_", b"alt_"))

    body = contexts(client)

    assert body["total"] == 22
    assert body["items"] == sorted(body["items"], key=order_key)
    assert {i["batch_id"]: i["run_id"] for i in body["items"]} == {
        s["batch_id"]: s["run_id"] for s in body["scope"]["selections"]
    }


def test_context_detail_returns_the_full_stored_assessment(data_dir):
    client = analyzed(data_dir)
    item = contexts(client, departments="Engineering", flagged="true")["items"][0]
    run_id, number = item["run_id"], item["context_number"]
    saved = assessments(client, run_id)[number]

    response = client.get(f"/runs/{run_id}/contexts/{number}")

    assert response.status_code == 200
    body = response.json()
    assert (body["run_id"], body["batch_id"], body["context_number"]) == (
        run_id,
        item["batch_id"],
        number,
    )
    assert body["application"] == {
        "run_id": run_id,
        "subject_kind": "tool",
        "subject_id": saved["tool_id"],
        "application_name": "Cursor",
        "domain": saved["domain"],
        "category": saved["category"],
    }
    assert body["original_scope"] == {
        k: saved[k]
        for k in (
            "department",
            "usage_purpose",
            "data_sensitivity_tier",
            "first_observed_at",
            "last_observed_at",
        )
    }
    assert body["assessment"] == {
        k: saved[k]
        for k in ("metadata_id", "facts", "tier", "reason_codes", "unknown_facts", "rule_version")
    }
    assert body["investigation"] == {"flagged": True, "reasons": saved["flag_reasons"]}
    assert body["events"]["count"] == saved["event_count"] == len(saved["event_ids"])
    assert "event_ids" not in body

    drill = client.get(body["events"]["path"], params={**body["events"]["query"], "limit": 200})
    events = drill.json()
    assert events["total"] == body["events"]["count"]
    assert {e["event_id"] for e in events["items"]} == set(saved["event_ids"])
    assert {(e["context_number"], e["subject_id"]) for e in events["items"]} == {
        (number, saved["tool_id"])
    }
    detail = client.get(f"/runs/{run_id}/applications/tool/{saved['tool_id']}").json()
    assert number in [r["context_number"] for r in detail["usage_contexts"]["references"]]


def test_every_context_drills_down_to_its_events(data_dir):
    client = analyzed(data_dir)

    for item in contexts(client)["items"]:
        detail = client.get(f"/runs/{item['run_id']}/contexts/{item['context_number']}").json()
        assert events_total(client, **detail["events"]["query"]) == detail["events"]["count"]


def test_context_detail_errors(data_dir):
    client = analyzed(data_dir)
    run_id = overview(client)["scope"]["selections"][0]["run_id"]

    for path, status, code in (
        ("/runs/run_missing/contexts/1", 404, "run_not_found"),
        (f"/runs/{run_id}/contexts/999", 404, "context_not_found"),
        (f"/runs/{run_id}/contexts/0", 422, "invalid_request"),
        (f"/runs/{run_id}/contexts/one", 422, "invalid_request"),
        (f"/runs/{run_id}/contexts/-1", 422, "invalid_request"),
    ):
        response = client.get(path)
        assert (response.status_code, response.json()["code"]) == (status, code), path
    assert client.get(f"/runs/{run_id}/contexts/x").json()["details"]["errors"] == [
        {"location": ["path", "context_id"], "problem": "invalid_context_number"}
    ]


def test_a_failed_run_has_no_contexts(data_dir):
    client = fixture_client(data_dir, jev=unavailable_jev)
    run = upload_fixture(client).json()["latest_run"]

    detail = client.get(f"/runs/{run['run_id']}/contexts/1")
    pinned = client.get("/contexts", params={"run_ids": run["run_id"]})
    body = contexts(client)

    assert (detail.status_code, detail.json()["code"]) == (409, "run_not_succeeded")
    assert (pinned.status_code, pinned.json()["code"]) == (409, "run_not_succeeded")
    assert body["total"] == 0
    assert body["scope"]["coverage"]["state"] == "no_successful_runs"


def test_invalid_context_filters_are_rejected(data_dir):
    client = analyzed(data_dir)

    for params, location in (
        ({"tool_ids": ""}, ["query", "tool_ids", 0]),
        ({"risk_tiers": "Critical"}, ["query", "risk_tiers", 0]),
        ({"context_number": "1"}, ["query", "context_number"]),
        ({"limit": "0"}, ["query", "limit"]),
    ):
        response = client.get("/contexts", params=params)
        assert response.status_code == 422, params
        assert response.json()["details"]["errors"][0]["location"] == location


def test_empty_storage_lists_no_contexts(client):
    response = client.get("/contexts")

    assert response.status_code == 200
    body = response.json()
    assert (body["items"], body["total"]) == ([], 0)
    assert body["scope"]["coverage"]["state"] == "no_batches"
