import csv
import io
from collections import Counter
from datetime import date

import pytest
from sqlalchemy import func, select

from app.db.tables import usage_context_assessments
from app.overview import bucket_size, bucket_start
from app.scope import Filters, context_conditions, resolve_scope, scoped_events
from tests.test_default_pipeline import fixture_client, upload_fixture
from tests.test_identity_fixture import FIXTURE
from tests.test_risk_results import ServesEveryHomepage

HEADER = (
    "event_id,timestamp,employee_id,department,job_role,application_name,domain,"
    "event_type,usage_purpose,data_sensitivity_tier\n"
)


def analyzed(data_dir, *contents):
    client = fixture_client(data_dir, http=ServesEveryHomepage())
    if not contents:
        contents = (FIXTURE.read_bytes(),)
    for content in contents:
        run = client.post(
            "/batches", files={"file": ("activity.csv", content, "text/csv")}
        ).json()["latest_run"]
        assert run["status"] == "succeeded"
    return client


def overview(client, **params):
    response = client.get("/overview", params=params)
    assert response.status_code == 200, response.json()
    return response.json()


def fixture_events():
    return list(csv.DictReader(io.StringIO(FIXTURE.read_text(encoding="utf-8"))))


def chatgpt_activity(*rows):
    return (
        HEADER
        + "".join(
            f"{event_id},{timestamp},emp_1,Finance,Analyst,ChatGPT,chatgpt.com,"
            "app_open,research,internal\n"
            for event_id, timestamp in rows
        )
    ).encode()


def test_overview_reports_the_fixture_run(data_dir):
    client = analyzed(data_dir)

    body = overview(client)

    run_id = body["scope"]["selections"][0]["run_id"]
    contexts = client.get(f"/runs/{run_id}/assessments", params={"limit": 200}).json()["items"]
    assert body["headline"] == {
        "known_ai_tools": 2,
        "ai_positive_events": 259,
        "ai_unresolved_events": 6,
        "flagged_contexts": sum(c["investigation_flag"] for c in contexts),
    }
    assert body["activity"] == {
        "events": len(fixture_events()),
        "by_ai_determination": {"ai": 259, "non_ai": 0, "unresolved": 6},
        "ai_positive_by_identity": {
            "known_tool": 127,
            "observed_tool": 132,
            "unresolved_candidate": 0,
        },
    }
    assert body["unresolved_stages"] == {
        "identity": {"events": 6, "candidates": 1},
        "ai_determination": {"events": 6, "candidates": 1},
        "category": {"events": 132, "candidates": 7},
    }
    assert body["risk_distribution"] == {
        tier: sum(c["tier"] == tier for c in contexts)
        for tier in ("High", "Medium", "Lower", "unresolved")
    }
    assert body["policy_status_distribution"] == {"approved": 7, "unapproved": 3, "unknown": 1}
    assert body["categories"] == [
        {"outcome": "assigned", "category": "Communication And Support", "ai_positive_events": 95},
        {"outcome": "assigned", "category": "Technology And Development", "ai_positive_events": 32},
        {"outcome": "unresolved", "category": None, "ai_positive_events": 132},
    ]
    departments = {d["department"]: d for d in body["departments"]}
    assert {name: d["events"] for name, d in departments.items()} == Counter(
        e["department"] for e in fixture_events()
    )
    assert departments["Operations"]["ai_positive_events"] == 0
    assert departments["Sales"]["flagged_contexts"] == 1
    assert body["batches"] == [
        {
            "batch_id": body["scope"]["selections"][0]["batch_id"],
            "run_id": run_id,
            "events": 265,
            "ai_positive_events": 259,
            "known_ai_tools": 2,
            "observed_ai_tools": 7,
            "flagged_contexts": 4,
        }
    ]
    trend = body["trend"]
    assert trend["bucket"] == "day"
    assert [p["start"][:10] for p in trend["points"]][:2] == ["2026-09-15", "2026-09-16"]
    assert trend["points"][-1]["end"] == "2026-10-15T00:00:00Z"
    assert all(p["covered"] for p in trend["points"])
    assert sum(p["ai_positive_events"] for p in trend["points"]) == 259
    assert sum(p["known_ai_tools_first_observed"] for p in trend["points"]) == 2
    assert body["scope"]["event_time"]["observed"] == {
        "first": "2026-09-15T07:39:00Z",
        "last": max(e["timestamp"] for e in fixture_events()),
    }
    assert {"headline.known_ai_tools", "trend", "matching_activity"} <= set(
        body["scope"]["count_definitions"]
    )


def test_combined_context_filters_must_match_the_same_usage_context(data_dir):
    client = analyzed(data_dir)

    # Finance has activity and other departments have Medium contexts, but no Finance context is Medium.
    mismatched = overview(client, departments="Finance", risk_tiers="Medium")
    engineering_lower = overview(client, departments="Engineering", risk_tiers="Lower")
    engineering_flagged = overview(client, departments="Engineering", flagged="true")

    assert mismatched["headline"] == {
        "known_ai_tools": 0,
        "ai_positive_events": 0,
        "ai_unresolved_events": 0,
        "flagged_contexts": 0,
    }
    assert sum(mismatched["risk_distribution"].values()) == 0
    assert engineering_lower["risk_distribution"]["Lower"] == 2  # ChatGPT and Magic Inspector
    assert engineering_lower["headline"]["ai_positive_events"] == 62 + 8
    assert engineering_flagged["headline"]["flagged_contexts"] == 1  # Cursor
    assert engineering_flagged["headline"]["ai_positive_events"] == 32
    assert engineering_flagged["headline"]["known_ai_tools"] == 1


def test_event_time_window_selects_activity_and_contexts_with_matching_events(data_dir):
    client = analyzed(data_dir)
    start, end = "2026-10-01T00:00:00Z", "2026-10-08T00:00:00Z"
    in_window = {e["event_id"]: e for e in fixture_events() if start <= e["timestamp"] < end}
    run_id = overview(client)["scope"]["selections"][0]["run_id"]
    contexts = client.get(f"/runs/{run_id}/assessments", params={"limit": 200}).json()["items"]
    touched = [c for c in contexts if set(c["event_ids"]) & set(in_window)]

    body = overview(client, start=start, end=end)

    assert body["activity"]["events"] == len(in_window)
    assert sum(body["risk_distribution"].values()) == len(touched) < len(contexts)
    assert body["headline"]["flagged_contexts"] == sum(c["investigation_flag"] for c in touched)
    assert body["scope"]["event_time"]["observed"] == {
        "first": min(e["timestamp"] for e in in_window.values()),
        "last": max(e["timestamp"] for e in in_window.values()),
    }
    assert [p["start"][:10] for p in body["trend"]["points"]] == [
        f"2026-10-0{day}" for day in range(1, 8)
    ]


@pytest.mark.parametrize(
    ("category", "ai_positive", "ai_unresolved", "contexts"),
    [
        ("Technology And Development", 32, 0, 1),
        ("unresolved", 132, 0, 8),
        ("inapplicable", 0, 6, 0),
    ],
)
def test_category_filter_selects_categories_and_outcomes(
    data_dir, category, ai_positive, ai_unresolved, contexts
):
    client = analyzed(data_dir)

    body = overview(client, categories=category)

    assert body["headline"]["ai_positive_events"] == ai_positive
    assert body["headline"]["ai_unresolved_events"] == ai_unresolved
    assert sum(body["risk_distribution"].values()) == contexts


def test_policy_status_filter_includes_unknown(data_dir):
    client = analyzed(data_dir)

    body = overview(client, policy_statuses="unknown")

    assert body["policy_status_distribution"] == {"approved": 0, "unapproved": 0, "unknown": 1}
    assert body["risk_distribution"]["unresolved"] == 1
    assert body["headline"]["ai_positive_events"] == 3  # Open Canvas AI


@pytest.mark.parametrize(
    "filters",
    [
        Filters(),
        Filters(departments=("Engineering", "Sales")),
        Filters(risk_tiers=("Medium",), categories=("unresolved",)),
        Filters(flagged=True, start="2026-10-01T00:00:00Z", end="2026-10-08T00:00:00Z"),
        Filters(policy_statuses=("approved",), start="2026-10-10T00:00:00Z"),
    ],
)
def test_matching_events_and_matching_contexts_agree(data_dir, filters):
    client = analyzed(data_dir)
    table = usage_context_assessments

    with client.app.state.engine.connect() as connection:
        scope = resolve_scope(connection, filters)
        events = scoped_events(scope)
        in_contexts = events.c.context_number.is_not(None)
        from_events = set(
            connection.execute(
                select(events.c.run_id, events.c.context_number).where(in_contexts).distinct()
            ).all()
        )
        from_contexts = set(
            connection.execute(
                select(table.c.run_id, table.c.context_number).where(*context_conditions(scope))
            ).all()
        )
        events_in_contexts = connection.execute(
            select(func.count()).select_from(events).where(in_contexts)
        ).scalar_one()
        # Both helpers in one statement share their CTEs.
        joined = connection.execute(
            select(func.count())
            .select_from(events)
            .join(
                table,
                (table.c.run_id == events.c.run_id)
                & (table.c.context_number == events.c.context_number),
            )
            .where(*context_conditions(scope))
        ).scalar_one()

    assert from_events == from_contexts
    assert joined == events_in_contexts


def test_cross_batch_counts_known_tools_once_and_discloses_overlap(data_dir):
    original = FIXTURE.read_bytes()
    first_row = original.split(b"\n")[1]
    changed = original.replace(first_row, first_row.replace(b"Engineering", b"Research"), 1)
    client = analyzed(data_dir, original, changed)

    body = overview(client)

    assert len(body["scope"]["selections"]) == 2
    assert body["headline"]["known_ai_tools"] == 2
    assert body["headline"]["ai_positive_events"] == 2 * 259
    assert [b["observed_ai_tools"] for b in body["batches"]] == [7, 7]
    warnings = {w["code"]: w for w in body["scope"]["coverage"]["warnings"]}
    assert warnings["exact_event_overlap"]["details"]["event_id_count"] == 264
    assert len(warnings["exact_event_overlap"]["details"]["event_ids"]) == 20
    assert warnings["conflicting_event_ids"]["details"]["event_ids"] == ["evt_000001"]
    assert sorted(warnings["conflicting_event_ids"]["details"]["batch_ids"]) == sorted(
        s["batch_id"] for s in body["scope"]["selections"]
    )


def test_trend_leaves_uncovered_periods_null_rather_than_zero(data_dir):
    client = analyzed(
        data_dir,
        chatgpt_activity(("a1", "2026-09-01T10:00:00Z"), ("a2", "2026-09-02T10:00:00Z")),
        chatgpt_activity(("b1", "2026-09-05T10:00:00Z")),
    )

    points = overview(client)["trend"]["points"]

    assert [(p["start"][:10], p["covered"], p["ai_positive_events"]) for p in points] == [
        ("2026-09-01", True, 1),
        ("2026-09-02", True, 1),
        ("2026-09-03", False, None),
        ("2026-09-04", False, None),
        ("2026-09-05", True, 1),
    ]
    assert [p["known_ai_tools_first_observed"] for p in points] == [1, 0, None, None, 0]


def test_trend_buckets_adapt_to_the_range():
    first = date(2026, 1, 1)

    assert bucket_size(first, date(2026, 3, 3)) == "day"  # 62 days
    assert bucket_size(first, date(2026, 3, 4)) == "week"
    assert bucket_size(first, date(2027, 1, 1)) == "week"  # 366 days
    assert bucket_size(first, date(2027, 1, 2)) == "month"
    assert bucket_start(date(2026, 9, 17), "week") == date(2026, 9, 14)  # Monday
    assert bucket_start(date(2026, 9, 17), "month") == date(2026, 9, 1)


def test_overview_of_one_selected_batch(data_dir):
    client = analyzed(
        data_dir,
        FIXTURE.read_bytes(),
        chatgpt_activity(("a1", "2026-09-01T10:00:00Z")),
    )
    small = next(
        b for b in overview(client)["scope"]["coverage"]["batches"] if b["event_count"] == 1
    )

    body = overview(client, batch_ids=small["batch_id"])

    assert [s["batch_id"] for s in body["scope"]["selections"]] == [small["batch_id"]]
    assert body["activity"]["events"] == 1
    assert body["headline"]["known_ai_tools"] == 1
    assert body["scope"]["coverage"]["warnings"] == []
