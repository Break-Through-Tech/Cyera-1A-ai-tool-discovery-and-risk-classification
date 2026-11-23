import pytest

from app.api.pagination import MAX_PAGE_SIZE
from tests.test_applications_inventory import analyzed, inventory, overview
from tests.test_contexts import contexts
from tests.test_default_pipeline import EverythingNotFound
from tests.test_identity_fixture import FIXTURE
from tests.test_overview import fixture_events


def events(client, **params):
    response = client.get("/events", params={"limit": MAX_PAGE_SIZE, **params})
    assert response.status_code == 200, response.json()
    return response.json()


def total(client, **params):
    return events(client, **params, limit=1)["total"]


def all_events(client, **params):
    found, offset = [], 0
    while True:
        page = events(client, **params, offset=offset)
        found += page["items"]
        offset += page["limit"]
        if offset >= page["total"]:
            return found, page["total"]


def order_key(item):
    return (item["occurred_at"], item["batch_id"], item["event_id"])


def test_events_list_every_matching_event_in_a_stable_order(data_dir):
    client = analyzed(data_dir)

    items, count = all_events(client)
    page = client.get("/events", params={"limit": 5, "offset": 10}).json()

    supplied = {e["event_id"]: e for e in fixture_events()}
    assert count == len(items) == len(supplied) == overview(client)["activity"]["events"]
    assert items == sorted(items, key=order_key)
    assert len({(e["batch_id"], e["event_id"]) for e in items}) == count
    assert page["items"] == items[10:15]
    assert (page["total"], page["limit"], page["offset"]) == (count, 5, 10)
    sample = items[0]
    assert sample["occurred_at"] == supplied[sample["event_id"]]["timestamp"]
    assert sample["department"] == supplied[sample["event_id"]]["department"]
    assert "events" in page["scope"]["count_definitions"]
    workbench = [e for e in items if e["application_name"] == "Workbench"]
    assert {(e["subject_kind"], e["identity_outcome"], e["context_number"]) for e in workbench} == {
        ("candidate", "unresolved_candidate", None)
    }
    assert {e["subject_id"] for e in workbench} == {str(workbench[0]["candidate_number"])}


@pytest.mark.parametrize(
    "filters",
    [
        {},
        {"departments": ["Engineering", "Sales"]},
        {"categories": "unresolved"},
        {"risk_tiers": "Medium", "categories": "unresolved"},
        {"flagged": "true", "start": "2026-10-01T00:00:00Z", "end": "2026-10-08T00:00:00Z"},
        {"policy_statuses": "approved", "start": "2026-10-10T00:00:00Z"},
    ],
)
def test_event_totals_agree_with_the_overview(data_dir, filters):
    client = analyzed(data_dir, http=EverythingNotFound())

    view = overview(client, **filters)

    assert total(client, **filters) == view["activity"]["events"]
    for determination, count in view["activity"]["by_ai_determination"].items():
        assert total(client, **filters, ai_determinations=determination) == count
    for outcome, count in view["activity"]["ai_positive_by_identity"].items():
        assert total(client, **filters, ai_determinations="ai", identity_outcomes=outcome) == count
    assert total(client, **filters, identity_outcomes="unresolved_candidate") == (
        view["unresolved_stages"]["identity"]["events"]
    )
    for department in view["departments"]:
        assert total(client, **{**filters, "departments": department["department"]}) == (
            department["events"]
        )


def test_a_trend_bucket_drills_down_to_its_events(data_dir):
    client = analyzed(data_dir)
    points = overview(client)["trend"]["points"]

    for point in points[:3]:
        assert total(
            client, start=point["start"], end=point["end"], ai_determinations="ai"
        ) == point["ai_positive_events"]


def test_every_application_row_drills_down_to_its_matching_events(data_dir):
    client = analyzed(data_dir)
    scope = {"departments": "Engineering", "start": "2026-10-01T00:00:00Z"}

    for row in inventory(client, **scope)["items"]:
        subject = (
            {"tool_ids": row["subject_id"]}
            if row["subject_kind"] == "tool"
            else {"candidate_number": row["subject_id"]}
        )
        body = events(client, **scope, run_ids=row["run_id"], **subject)
        assert body["total"] == row["matching_events"], row["application_names"]
        assert {(e["subject_kind"], e["subject_id"]) for e in body["items"]} == {
            (row["subject_kind"], row["subject_id"])
        }
        assert {e["context_number"] for e in body["items"]} - {None} == set(
            row["matching_context_numbers"]
        )


def test_context_drill_down_follows_the_shared_filters(data_dir):
    client = analyzed(data_dir)
    window = {"start": "2026-10-01T00:00:00Z", "end": "2026-10-08T00:00:00Z"}

    for item in contexts(client)["items"]:
        reference = {"run_ids": item["run_id"], "context_number": item["context_number"]}
        assert total(client, **reference) == item["event_count"]
        windowed = events(client, **reference, **window)
        assert all(window["start"] <= e["occurred_at"] < window["end"] for e in windowed["items"])
        assert total(client, **reference, risk_tiers=item["tier"]) == item["event_count"]
        other = "High" if item["tier"] != "High" else "Medium"
        assert total(client, **reference, risk_tiers=other) == 0


def test_tool_ids_select_a_known_tool_across_batches(data_dir):
    original = FIXTURE.read_bytes()
    client = analyzed(data_dir, original, original.replace(b"evt_", b"alt_"))
    chatgpt = [r for r in inventory(client, application="chatgpt")["items"]]

    body = events(client, tool_ids=chatgpt[0]["subject_id"], limit=1)

    assert len(chatgpt) == 2
    assert body["total"] == sum(r["matching_events"] for r in chatgpt)
    assert total(client, tool_ids=chatgpt[0]["subject_id"], run_ids=chatgpt[0]["run_id"]) == (
        chatgpt[0]["matching_events"]
    )


def test_run_pinned_references_need_one_run_and_must_exist(data_dir):
    client = analyzed(data_dir)
    run_id = overview(client)["scope"]["selections"][0]["run_id"]

    pin = {"run_ids": run_id}
    for params, status, code, location, problem in (
        ({"context_number": 1}, 422, "invalid_request", ["context_number"], "requires_one_run_id"),
        ({"candidate_number": 1}, 422, "invalid_request", ["candidate_number"], "requires_one_run_id"),
        ({**pin, "context_number": 999}, 404, "context_not_found", ["context_number"], "not_found"),
        ({**pin, "candidate_number": 999}, 404, "candidate_not_found", ["candidate_number"], "not_found"),
        ({**pin, "context_number": 0}, 422, "invalid_request", ["context_number"], "greater_than_equal"),
        ({"ai_determinations": "maybe"}, 422, "invalid_request", ["ai_determinations", 0], "literal_error"),
        ({"identity_outcomes": "guess"}, 422, "invalid_request", ["identity_outcomes", 0], "literal_error"),
        ({"tool_ids": ""}, 422, "invalid_request", ["tool_ids", 0], "string_too_short"),
        ({"event_id": "evt_1"}, 422, "invalid_request", ["event_id"], "unknown_parameter"),
        ({"run_ids": "run_missing"}, 404, "run_not_found", ["run_ids", 0], "not_found"),
    ):
        response = client.get("/events", params=params)
        body = response.json()
        assert (response.status_code, body["code"]) == (status, code), params
        error = body["details"]["errors"][0]
        assert error == {"location": ["query", *location], "problem": problem}, params

    assert total(client, run_ids=run_id, candidate_number=1) > 0
    assert total(client, run_ids=run_id, context_number=1) > 0
    assert total(client, tool_ids="tool:missing") == 0


def test_empty_storage_lists_no_events(client):
    response = client.get("/events")

    assert response.status_code == 200
    body = response.json()
    assert (body["items"], body["total"]) == ([], 0)
    assert body["scope"]["coverage"]["state"] == "no_batches"
