from app.api.pagination import MAX_PAGE_SIZE
from tests.test_default_pipeline import (
    EverythingNotFound,
    fixture_client,
    unavailable_jev,
    upload_fixture,
)
from tests.test_identity_fixture import FIXTURE
from tests.test_risk_results import ServesEveryHomepage


def analyzed(data_dir, *contents, http=None):
    client = fixture_client(data_dir, http=http or ServesEveryHomepage())
    for content in contents or (FIXTURE.read_bytes(),):
        run = client.post(
            "/batches", files={"file": ("activity.csv", content, "text/csv")}
        ).json()["latest_run"]
        assert run["status"] == "succeeded"
    return client


def inventory(client, **params):
    response = client.get("/applications", params={"limit": MAX_PAGE_SIZE, **params})
    assert response.status_code == 200, response.json()
    return response.json()


def overview(client, **params):
    response = client.get("/overview", params=params)
    assert response.status_code == 200, response.json()
    return response.json()


def order_key(item):
    return (
        item["application_names"][0].casefold(),
        item["domain"],
        item["run_id"],
        item["subject_kind"],
        item["subject_id"],
    )


def test_the_inventory_lists_every_application_in_a_stable_order(data_dir):
    client = analyzed(data_dir)

    body = inventory(client)
    page = client.get("/applications", params={"limit": 3, "offset": 2}).json()

    items = body["items"]
    assert body["total"] == len(items) == 10
    assert items == sorted(items, key=order_key)
    assert sum(item["matching_events"] for item in items) == 265
    assert page["items"] == items[2:5]
    assert (page["total"], page["limit"], page["offset"]) == (10, 3, 2)
    assert body["scope"]["coverage"]["state"] == "available"
    assert "applications.matching_events" in body["scope"]["count_definitions"]


def test_every_row_opens_its_run_pinned_detail(data_dir):
    client = analyzed(data_dir)

    for item in inventory(client)["items"]:
        detail = client.get(
            f"/runs/{item['run_id']}/applications/{item['subject_kind']}/{item['subject_id']}"
        )
        assert detail.status_code == 200
        summary = detail.json()["summary"]
        assert summary == {key: item[key] for key in summary}


def test_the_ai_positive_filter_agrees_with_the_overview(data_dir):
    client = analyzed(data_dir, http=EverythingNotFound())

    everything = inventory(client)["items"]
    ai = inventory(client, ai_determinations="ai")

    assert {item["ai_determination"] for item in everything} == {"ai", "non_ai", "unresolved"}
    assert ai["total"] == sum(item["ai_determination"] == "ai" for item in everything) > 0
    assert {item["ai_determination"] for item in ai["items"]} == {"ai"}
    assert ai["inventory_filters"]["ai_determinations"] == ["ai"]
    assert sum(item["matching_events"] for item in ai["items"]) == overview(client)[
        "headline"
    ]["ai_positive_events"]
    both = inventory(client, ai_determinations=["non_ai", "unresolved"])
    assert both["total"] == len(everything) - ai["total"]


def test_name_domain_and_identity_filters(data_dir):
    client = analyzed(data_dir)

    by_name = inventory(client, application="slack")["items"]
    by_domain = inventory(client, application="CHATGPT.COM")["items"]
    unresolved = inventory(client, identity_outcomes="unresolved_candidate")["items"]
    known = inventory(client, identity_outcomes="known_tool", application="cursor")["items"]

    assert [item["application_names"] for item in by_name] == [["Slack"]]
    assert [item["domain"] for item in by_domain] == ["chatgpt.com"]
    assert [(item["subject_kind"], item["application_names"]) for item in unresolved] == [
        ("candidate", ["Workbench"])
    ]
    assert [item["application_names"] for item in known] == [["Cursor"]]
    assert inventory(client, application="no-such-tool")["total"] == 0


def test_a_department_filter_counts_matching_activity_like_the_overview(data_dir):
    client = analyzed(data_dir)

    body = inventory(client, departments="Engineering")
    everything = {order_key(item): item for item in inventory(client)["items"]}

    assert 0 < body["total"] < len(everything)
    assert sum(item["matching_events"] for item in body["items"]) == overview(
        client, departments="Engineering"
    )["activity"]["events"]
    for item in body["items"]:
        assert item["event_count"] == everything[order_key(item)]["event_count"]
        assert item["matching_events"] <= item["event_count"]


def test_a_risk_tier_filter_selects_applications_through_matching_contexts(data_dir):
    client = analyzed(data_dir)

    body = inventory(client, risk_tiers="High")
    view = overview(client, risk_tiers="High")

    assert body["total"] > 0
    assert all(item["context_count"] > 0 for item in body["items"])
    assert sum(len(item["matching_context_numbers"]) for item in body["items"]) == sum(
        view["risk_distribution"].values()
    )
    assert sum(item["matching_events"] for item in body["items"]) == view["activity"]["events"]
    run_id = body["items"][0]["run_id"]
    assessments = {
        a["context_number"]: a
        for a in client.get(f"/runs/{run_id}/assessments", params={"limit": 200}).json()["items"]
    }
    for item in body["items"]:
        for number in item["matching_context_numbers"]:
            assert assessments[number]["tier"] == "High"
            assert assessments[number]["tool_id"] == item["subject_id"]


def test_applications_are_per_run_across_batches(data_dir):
    original = FIXTURE.read_bytes()
    first_row = original.split(b"\n")[1]
    changed = original.replace(first_row, first_row.replace(b"Engineering", b"Research"), 1)
    client = analyzed(data_dir, original, changed)

    body = inventory(client)
    chatgpt = [item for item in body["items"] if item["application_names"] == ["ChatGPT"]]
    workbench = [item for item in body["items"] if item["application_names"] == ["Workbench"]]

    assert body["total"] == 20
    assert len({s["run_id"] for s in body["scope"]["selections"]}) == 2
    assert len(chatgpt) == 2
    assert chatgpt[0]["subject_id"] == chatgpt[1]["subject_id"]
    assert {item["batch_id"] for item in chatgpt} == {
        s["batch_id"] for s in body["scope"]["selections"]
    }
    assert len(workbench) == 2
    assert chatgpt == sorted(chatgpt, key=lambda item: item["run_id"])


def test_pinned_runs_select_their_own_applications(data_dir):
    client = analyzed(data_dir)
    first = inventory(client)["scope"]["selections"][0]
    second = client.post(f"/batches/{first['batch_id']}/runs").json()["run_id"]

    latest = inventory(client)
    pinned = inventory(client, run_ids=first["run_id"])

    assert {item["run_id"] for item in latest["items"]} == {second}
    assert {item["run_id"] for item in pinned["items"]} == {first["run_id"]}
    assert pinned["total"] == latest["total"]
    warnings = {w["code"] for w in pinned["scope"]["coverage"]["warnings"]}
    assert "newer_successful_run" in warnings


def test_invalid_filters_are_rejected(data_dir):
    client = analyzed(data_dir)

    for params, location in (
        ({"ai_determinations": "maybe"}, ["query", "ai_determinations", 0]),
        ({"identity_outcomes": "guess"}, ["query", "identity_outcomes", 0]),
        ({"application": ""}, ["query", "application"]),
        ({"risk_tiers": "Critical"}, ["query", "risk_tiers", 0]),
        ({"name": "Slack"}, ["query", "name"]),
    ):
        response = client.get("/applications", params=params)
        assert response.status_code == 422, params
        assert response.json()["details"]["errors"][0]["location"] == location

    assert client.get("/applications", params={"run_ids": "run_missing"}).status_code == 404


def test_empty_storage_is_an_empty_inventory(client):
    response = client.get("/applications")

    assert response.status_code == 200
    body = response.json()
    assert (body["items"], body["total"]) == ([], 0)
    assert body["scope"]["coverage"]["state"] == "no_batches"


def test_a_batch_without_a_successful_run_contributes_no_applications(data_dir):
    client = fixture_client(data_dir, jev=unavailable_jev)
    upload_fixture(client)

    body = inventory(client)

    assert body["total"] == 0
    assert body["scope"]["coverage"]["state"] == "no_successful_runs"
