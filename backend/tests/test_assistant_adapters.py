"""The assistant's query-backed tools against real stored Analysis Runs (#78).

Each tool's numbers are checked against the public listing for the same scope:
``/overview``, ``/events``, ``/applications`` and ``/contexts``.
"""

import asyncio
from dataclasses import dataclass
from urllib.parse import parse_qs, urlsplit

import pytest
from fastapi.testclient import TestClient

from app.assistant.adapters import build_tool_registry
from app.assistant.contracts import (
    AggregateEvidence,
    EventTimeRange,
    FactualClaim,
    Finding,
    GroundedAnswer,
    PinnedScope,
    RecordEvidence,
    RunReference,
    ScopeFilters,
    ToolFailure,
    ToolLimitation,
    ToolSuccess,
    validate_answer_references,
)
from app.assistant.graph import Assistant, ExecutionLimits
from app.assistant.integrations import AnswerDecision, ToolCall
from app.assistant.store import get_evidence, list_steps
from app.assistant.tools import ToolRegistry
from app.pipeline import Phase
from app.results import list_candidates
from tests.test_assistant_graph import ScriptedModel
from tests.test_batches import upload
from tests.test_default_pipeline import fixture_client, upload_fixture
from tests.test_identity_fixture import FIXTURE
from tests.test_risk_results import ServesEveryHomepage

WINDOW = EventTimeRange(start="2026-09-01T00:00:00Z", end="2026-11-01T00:00:00Z")
TOOLS = ("describe_dataset", "summarize_usage", "compare_usage", "get_risk_assessments", "get_evidence")


@dataclass(frozen=True)
class World:
    client: TestClient
    first: RunReference  # the fixture Batch's first Run, superseded by ``current``
    current: RunReference  # the fixture Batch's newer succeeded Run
    overlap: RunReference  # a second Batch repeating the fixture's first three events

    @property
    def engine(self):
        return self.client.app.state.engine

    @property
    def settings(self):
        return self.client.app.state.settings


@pytest.fixture(scope="module")
def world(tmp_path_factory) -> World:
    client = fixture_client(tmp_path_factory.mktemp("data"), http=ServesEveryHomepage())
    batch = upload_fixture(client).json()
    newer = client.post(f"/batches/{batch['batch_id']}/runs").json()
    lines = FIXTURE.read_text(encoding="utf-8").splitlines(keepends=True)
    other = upload(client, "".join(lines[:4]).encode(), "overlap.csv").json()
    for run in (batch["latest_run"], newer, other["latest_run"]):
        assert run["status"] == "succeeded"
    return World(
        client,
        RunReference(batch_id=batch["batch_id"], run_id=batch["latest_run"]["run_id"]),
        RunReference(batch_id=batch["batch_id"], run_id=newer["run_id"]),
        RunReference(batch_id=other["batch_id"], run_id=other["latest_run"]["run_id"]),
    )


@pytest.fixture(scope="module")
def registry(world) -> ToolRegistry:
    return build_tool_registry(world.engine, world.settings)


def pinned(world, *runs, event_time=WINDOW, **filters) -> PinnedScope:
    return PinnedScope(
        runs=runs or (world.current,), event_time=event_time, filters=ScopeFilters(**filters)
    )


def invoke(registry, scope, tool, **arguments):
    parsed = registry.prepare(ToolCall(tool=tool, arguments=arguments), scope, 4096)
    return asyncio.run(
        registry.invoke(
            tool,
            scope,
            parsed,
            reference_namespace="step_test",
            maximum_bytes=ExecutionLimits().max_tool_result_bytes,
        )
    )


def listing(world, path, scope, **extra) -> dict:
    """The public listing for ``scope``, built independently of the adapters."""
    f = scope.filters
    params = {
        "batch_ids": [r.batch_id for r in scope.runs],
        "run_ids": [r.run_id for r in scope.runs],
        "start": scope.event_time.start.isoformat(),
        "end": scope.event_time.end.isoformat(),
        "departments": list(f.departments),
        "categories": list(f.categories),
        "risk_tiers": list(f.risk_tiers),
        **({"flagged": str(f.flagged).lower()} if f.flagged is not None else {}),
        **extra,
    }
    response = world.client.get(path, params=params)
    assert response.status_code == 200, response.json()
    return response.json()


def every_item(world, path, scope, **extra) -> list[dict]:
    items, offset = [], 0
    while True:
        page = listing(world, path, scope, limit=200, offset=offset, **extra)
        items += page["items"]
        offset += 200
        if offset >= page["total"]:
            return items


def drilldown_total(world, evidence: AggregateEvidence) -> int:
    """Open an aggregate's drilldown reference through the public API."""
    method, _, url = evidence.drilldown_reference.partition(" ")
    assert method == "GET"
    parts = urlsplit(url)
    response = world.client.get(parts.path, params=parse_qs(parts.query))
    assert response.status_code == 200, response.json()
    return response.json()["total"]


def aggregate(result: ToolSuccess) -> AggregateEvidence:
    return next(e for e in result.evidence if isinstance(e, AggregateEvidence))


def records(result: ToolSuccess) -> list[RecordEvidence]:
    return [e for e in result.evidence if isinstance(e, RecordEvidence)]


# --- Registry ----------------------------------------------------------------------------


def test_every_query_tool_is_connected_and_retrieval_stays_unavailable(world, registry):
    assert {d.name for d in registry.descriptions()} == set(TOOLS)

    result = invoke(registry, pinned(world), "retrieve_context", query="AI policy")

    assert result == ToolLimitation(reason="unavailable", message="retrieve_context is not connected.")


# --- describe_dataset --------------------------------------------------------------------


def test_describe_dataset_matches_the_overview_for_the_same_scope(world, registry):
    scope = pinned(world)
    overview = listing(world, "/overview", scope)

    result = invoke(registry, scope, "describe_dataset")

    assert result.status == "succeeded" and result.outcome == "data"
    data = result.data
    assert data["runs"][0]["run_id"] == world.current.run_id
    assert data["runs"][0]["versions"] == overview["scope"]["coverage"]["batches"][0]["selected_run"]["versions"]
    assert {k: data["event_time"][k] for k in ("first_matching", "last_matching")} == {
        "first_matching": overview["scope"]["event_time"]["observed"]["first"],
        "last_matching": overview["scope"]["event_time"]["observed"]["last"],
    }
    activity = data["activity"]
    assert activity["events"] == overview["activity"]["events"] == 265
    assert activity["by_ai_status"] == overview["activity"]["by_ai_determination"]
    assert activity["unresolved_stages"] == overview["unresolved_stages"]
    assert activity["missing_fields"]["data_sensitivity_tier"] == {"absent": 0, "unknown": 6}
    assert {d["department"]: (d["events"], d["ai_positive_events"]) for d in data["departments"]["items"]} == {
        d["department"]: (d["events"], d["ai_positive_events"]) for d in overview["departments"]
    }
    contexts = data["usage_contexts"]
    assert contexts["by_tier"] == overview["risk_distribution"]
    assert contexts["by_policy_status"] == overview["policy_status_distribution"]
    assert contexts["flagged"] == overview["headline"]["flagged_contexts"]
    assert activity["tools"]["known_tools"] == overview["headline"]["known_ai_tools"] == 2
    assert [(r.record_type, r.record_id) for r in records(result)] == [
        ("analysis_run", world.current.run_id)
    ]
    assert aggregate(result).scope == scope


# --- summarize_usage ---------------------------------------------------------------------


SCOPES = {
    "all": {},
    "department": {"departments": ("Engineering",)},
    "category_outcome": {"categories": ("unresolved",)},
    "department_and_tier": {"departments": ("Engineering",), "risk_tiers": ("Lower",)},
    "flagged": {"flagged": True},
    "week": {"event_time": EventTimeRange(start="2026-10-01T00:00:00Z", end="2026-10-08T00:00:00Z")},
}


@pytest.mark.parametrize("variant", SCOPES)
def test_summarize_usage_totals_equal_the_listings(world, registry, variant):
    scope = pinned(world, **SCOPES[variant])
    events = every_item(world, "/events", scope)

    totals = {
        metric: invoke(registry, scope, "summarize_usage", metric=metric)
        for metric in ("event_count", "distinct_employees", "tools", "usage_contexts")
    }

    assert totals["event_count"].data["total"] == len(events) > 0
    assert totals["event_count"].data["total"] == listing(world, "/overview", scope)["activity"]["events"]
    assert totals["distinct_employees"].data["total"] == len({e["employee_id"] for e in events})
    assert totals["tools"].data["total"] == listing(world, "/applications", scope)["total"]
    assert totals["usage_contexts"].data["total"] == listing(world, "/contexts", scope)["total"]
    for result in totals.values():
        assert result.status == "succeeded" and not result.truncated
        assert drilldown_total(world, aggregate(result)) == listing(
            world, aggregate(result).query["listing"].split(" ")[1], scope
        )["total"]


def test_grouped_summaries_equal_the_overview_breakdowns(world, registry):
    scope = pinned(world)
    overview = listing(world, "/overview", scope)

    by_department = invoke(registry, scope, "summarize_usage", group_by=["department"])
    by_ai = invoke(registry, scope, "summarize_usage", group_by=["ai_status"])
    by_tier = invoke(registry, scope, "summarize_usage", metric="usage_contexts", group_by=["risk_tier"])

    assert {g["department"]: g["value"] for g in by_department.data["groups"]} == {
        d["department"]: d["events"] for d in overview["departments"]
    }
    values = [g["value"] for g in by_department.data["groups"]]
    assert values == sorted(values, reverse=True)
    assert {g["ai_status"]: g["value"] for g in by_ai.data["groups"]} == {
        k: v for k, v in overview["activity"]["by_ai_determination"].items() if v
    }
    assert {g["risk_tier"]: g["value"] for g in by_tier.data["groups"]} == {
        k: v for k, v in overview["risk_distribution"].items() if v
    }
    assert aggregate(by_tier).query["group_by"] == ["risk_tier"]
    assert any("risk_tier" in d for d in aggregate(by_tier).metric_definitions)


def test_ai_status_filter_maps_to_event_ai_determinations(world, registry):
    unresolved = pinned(world, ai_statuses=("unresolved",))
    ai = pinned(world, ai_statuses=("ai",))

    events = invoke(registry, unresolved, "summarize_usage")
    contexts = invoke(registry, unresolved, "summarize_usage", metric="usage_contexts")
    risks = invoke(registry, unresolved, "get_risk_assessments")

    assert events.data["total"] == listing(
        world, "/events", unresolved, ai_determinations="unresolved"
    )["total"] == 6
    assert aggregate(events).query["parameters"]["ai_determinations"] == ["unresolved"]
    assert drilldown_total(world, aggregate(events)) == 6
    assert contexts.outcome == risks.outcome == "no_matches"
    assert any("exist only for Tools determined AI" in q for q in contexts.qualifications)
    assert invoke(registry, ai, "summarize_usage", metric="usage_contexts").data["total"] == listing(
        world, "/contexts", ai
    )["total"]


# --- compare_usage -----------------------------------------------------------------------


def test_compare_usage_counts_each_period_like_the_events_listing(world, registry):
    scope = pinned(world)
    baseline = {"start": "2026-09-16T00:00:00Z", "end": "2026-09-23T00:00:00Z"}
    current = {"start": "2026-09-23T00:00:00Z", "end": "2026-09-30T00:00:00Z"}

    result = invoke(registry, scope, "compare_usage", baseline=baseline, current=current)

    expected = {
        name: listing(world, "/events", scope.model_copy(update={"event_time": EventTimeRange(**period)}))["total"]
        for name, period in (("baseline", baseline), ("current", current))
    }
    assert result.outcome == "data"
    assert {name: result.data[name]["value"] for name in expected} == expected
    assert result.data["baseline"]["coverage"] == result.data["current"]["coverage"] == "full"
    assert result.data["change"] == expected["current"] - expected["baseline"]
    periods = [e for e in result.evidence if isinstance(e, AggregateEvidence)]
    assert [e.query["period"] for e in periods] == ["baseline", "current"]
    assert all(e.scope == scope for e in periods)
    assert [drilldown_total(world, e) for e in periods] == [expected["baseline"], expected["current"]]


def test_an_uncovered_period_is_unknown_not_zero(world, registry):
    result = invoke(
        registry,
        pinned(world),
        "compare_usage",
        baseline={"start": "2026-09-01T00:00:00Z", "end": "2026-09-08T00:00:00Z"},
        current={"start": "2026-10-10T00:00:00Z", "end": "2026-10-20T00:00:00Z"},
    )

    assert result.data["baseline"] | {"value": None} == result.data["baseline"]
    assert result.data["baseline"]["coverage"] == "none"
    assert result.data["current"]["coverage"] == "partial"
    assert result.data["change"] is None and result.data["percent_change"] is None
    assert any("unknown, not zero" in q for q in result.qualifications)
    assert any("partly covered" in q for q in result.qualifications)
    assert any("different lengths" in q for q in result.qualifications)


# --- get_risk_assessments ----------------------------------------------------------------


@pytest.mark.parametrize(
    ("focus", "api_filters"),
    [
        ("all", {}),
        ("flagged", {"flagged": "true"}),
        ("unapproved", {"policy_statuses": "unapproved"}),
        ("unresolved", {"risk_tiers": "unresolved"}),
    ],
)
def test_risk_assessments_equal_the_contexts_listing(world, registry, focus, api_filters):
    scope = pinned(world)
    expected = listing(world, "/contexts", scope, limit=200, **api_filters)

    result = invoke(registry, scope, "get_risk_assessments", focus=focus, limit=100)

    rows = result.data["assessments"]
    assert result.data["total"] == expected["total"] == len(rows) > 0
    keys = ("run_id", "context_number", "tier", "investigation_flag", "flag_reasons", "matching_events")
    assert [{k: r[k] for k in keys} for r in rows] == [{k: c[k] for k in keys} for c in expected["items"]]
    assert [r["facts"]["policy_status"] for r in rows] == [c["policy_status"] for c in expected["items"]]
    assert [(e.run, e.record_type, e.record_id) for e in records(result)] == [
        (world.current, "usage_context", str(r["context_number"])) for r in rows
    ]
    assert drilldown_total(world, aggregate(result)) == expected["total"]


def test_risk_assessments_return_reasons_and_unknown_facts(world, registry):
    scope = pinned(world)
    stored = {
        c["context_number"]: c
        for c in world.client.get(f"/runs/{world.current.run_id}/assessments", params={"limit": 200}).json()["items"]
    }

    every = invoke(registry, scope, "get_risk_assessments", limit=100)
    missing = invoke(registry, scope, "get_risk_assessments", focus="missing_facts", limit=100)

    for row in every.data["assessments"]:
        context = stored[row["context_number"]]
        assert (row["reason_codes"], row["unknown_facts"]) == (context["reason_codes"], context["unknown_facts"])
    assert {r["context_number"] for r in missing.data["assessments"]} == {
        n for n, c in stored.items() if c["unknown_facts"]
    }
    assert every.data["counts"]["with_unknown_facts"] == missing.data["total"]


# --- Outcomes ----------------------------------------------------------------------------


def test_no_matching_records_is_a_success_with_citable_evidence(world, registry):
    scope = pinned(world, departments=("Nowhere",))
    calls = {
        "describe_dataset": {},
        "summarize_usage": {"group_by": ["category"]},
        "get_risk_assessments": {},
        "compare_usage": {
            "baseline": {"start": "2026-09-16T00:00:00Z", "end": "2026-09-23T00:00:00Z"},
            "current": {"start": "2026-09-23T00:00:00Z", "end": "2026-09-30T00:00:00Z"},
        },
    }

    for tool, arguments in calls.items():
        result = invoke(registry, scope, tool, **arguments)
        assert (result.status, result.outcome) == ("succeeded", "no_matches"), tool
        assert aggregate(result).scope == scope


@pytest.mark.parametrize("tool", TOOLS)
def test_an_unsupported_filter_value_is_a_limitation_not_dropped(world, registry, tool):
    arguments = {
        "compare_usage": {
            "baseline": {"start": "2026-09-16T00:00:00Z", "end": "2026-09-23T00:00:00Z"},
            "current": {"start": "2026-09-23T00:00:00Z", "end": "2026-09-30T00:00:00Z"},
        },
        "get_evidence": {"references": [f"analysis_run:{world.current.run_id}:{world.current.run_id}"]},
    }.get(tool, {})

    result = invoke(registry, pinned(world, categories=("Robots",)), tool, **arguments)

    assert result.status == "limited" and result.reason == "unsupported"


def test_unsupported_arguments_and_foreign_continuations_are_limitations(world, registry):
    scope = pinned(world)
    page = invoke(registry, scope, "summarize_usage", group_by=["department"], limit=2)
    other_scope = pinned(world, departments=("Sales",))

    duplicate = invoke(registry, scope, "summarize_usage", group_by=["department", "department"])
    other_arguments = invoke(
        registry, scope, "summarize_usage", group_by=["category"], continuation=page.continuation
    )
    other_scope_result = invoke(
        registry, other_scope, "summarize_usage", group_by=["department"], continuation=page.continuation
    )
    forged = invoke(registry, scope, "get_risk_assessments", continuation="0:forged")

    for result in (duplicate, other_arguments, other_scope_result, forged):
        assert result.status == "limited" and result.reason == "unsupported"


def test_previews_are_qualified_and_continue_to_the_full_population(world, registry):
    scope = pinned(world)
    full = invoke(registry, scope, "summarize_usage", group_by=["department"], limit=100)
    pages, continuation = [], None

    while True:
        page = invoke(
            registry, scope, "summarize_usage", group_by=["department"], limit=4,
            **({"continuation": continuation} if continuation else {}),
        )
        assert page.truncated
        assert any(q.startswith("Preview:") for q in page.qualifications)
        assert page.data["total"] == full.data["total"] == 265
        pages += page.data["groups"]
        continuation = page.continuation
        if continuation is None:
            break

    assert not full.truncated and full.continuation is None
    assert pages == full.data["groups"]


def test_result_size_limit_shrinks_pages_into_explicit_previews(world):
    small = build_tool_registry(world.engine, world.settings, limits=ExecutionLimits(max_tool_result_bytes=6000))
    scope = pinned(world)
    expected = listing(world, "/contexts", scope, limit=200)["items"]
    seen, continuation = [], None

    while True:
        page = invoke(
            small, scope, "get_risk_assessments", limit=100,
            **({"continuation": continuation} if continuation else {}),
        )
        assert page.truncated and page.data["returned"] < 11
        assert page.data["total"] == page.data["counts"]["total"] == 11
        assert any("Preview: Usage Contexts" in q for q in page.qualifications)
        seen += [r["context_number"] for r in page.data["assessments"]]
        continuation = page.continuation
        if continuation is None:
            break

    assert seen == [c["context_number"] for c in expected]


def test_evidence_beyond_the_size_limit_is_listed_not_silently_dropped(world):
    small = build_tool_registry(world.engine, world.settings, limits=ExecutionLimits(max_tool_result_bytes=5000))
    domains = ["chatgpt.com", "cursor.so", "slack.com", "mattermost.com", "meetoscar.com"]
    references = [f"website_capture:{world.current.run_id}:{d}" for d in domains]

    result = invoke(small, pinned(world), "get_evidence", references=references)

    assert result.truncated
    returned = [r["reference"]["domain"] for r in result.data["resolved"]]
    omitted = result.data["omitted_for_size"]
    assert 0 < len(returned) < len(domains)
    assert returned + [o.rsplit(":", 1)[1] for o in omitted] == domains
    assert any("Preview:" in q for q in result.qualifications)
    assert [e.record_id for e in records(result)] == returned


@pytest.mark.parametrize(
    ("runs", "code"),
    [
        (lambda w: (RunReference(batch_id="bat_missing", run_id=w.current.run_id),), "scope_run_not_found"),
        (lambda w: (RunReference(batch_id=w.current.batch_id, run_id="run_missing"),), "scope_run_not_found"),
        (lambda w: (RunReference(batch_id=w.current.batch_id, run_id=w.overlap.run_id),), "scope_run_batch_mismatch"),
        (
            lambda w: (
                RunReference(batch_id=w.current.batch_id, run_id=w.overlap.run_id),
                RunReference(batch_id=w.overlap.batch_id, run_id=w.current.run_id),
            ),
            "scope_run_batch_mismatch",
        ),
    ],
)
def test_a_wrong_run_fails_safely_for_every_tool(world, registry, runs, code):
    scope = PinnedScope(runs=runs(world), event_time=WINDOW)

    for tool in TOOLS:
        arguments = {"references": [f"analysis_run:{scope.runs[0].run_id}"]} if tool == "get_evidence" else {}
        if tool == "compare_usage":
            arguments = {"baseline": WINDOW.model_dump(mode="json"), "current": WINDOW.model_dump(mode="json")}
        result = invoke(registry, scope, tool, **arguments)
        assert isinstance(result, ToolFailure), tool
        assert result.code == code


def test_a_failed_run_has_no_results_to_query(make_client):
    def fail(context):
        raise RuntimeError("secret=do-not-expose")

    client = make_client(Phase("detect", fail))
    batch = upload(client).json()
    assert batch["latest_run"]["status"] == "failed"
    registry = build_tool_registry(client.app.state.engine, client.app.state.settings)
    scope = PinnedScope(
        runs=(RunReference(batch_id=batch["batch_id"], run_id=batch["latest_run"]["run_id"]),),
        event_time=WINDOW,
    )

    result = invoke(registry, scope, "summarize_usage")

    assert result == ToolFailure(
        code="scope_run_not_succeeded",
        message="A pinned Analysis Run did not succeed, so it has no results.",
    )
    assert "secret" not in result.model_dump_json()


def test_scope_warnings_are_carried_as_qualifications(world, registry):
    superseded = invoke(registry, pinned(world, world.first), "summarize_usage")
    overlapping = invoke(registry, pinned(world, world.current, world.overlap), "summarize_usage")
    single = invoke(registry, pinned(world, world.overlap), "summarize_usage")

    assert any(q.startswith("newer_successful_run:") and world.current.run_id in q for q in superseded.qualifications)
    assert any(q.startswith("exact_event_overlap:") for q in overlapping.qualifications)
    assert overlapping.data["total"] == 265 + single.data["total"]  # counted once per Batch


# --- get_evidence ------------------------------------------------------------------------


def test_record_evidence_from_every_tool_resolves_through_get_evidence(world, registry):
    scope = pinned(world)
    run_id = world.current.run_id
    described = invoke(registry, scope, "describe_dataset")
    risks = invoke(registry, scope, "get_risk_assessments", focus="flagged")
    issued = records(described) + records(risks)
    flagged = risks.data["assessments"][0]
    with world.engine.connect() as connection:
        voted = next(c for c in list_candidates(connection, run_id) if c["category"]["neighbors"])
    canonical = [
        f"tool_metadata:{run_id}:{flagged['metadata_id']}",
        f"website_capture:{run_id}:{flagged['domain']}",
        f"ai_evidence_sentence:{run_id}:{flagged['candidate_numbers'][0]}:1",
        f"category_neighbor:{run_id}:{voted['candidate_number']}:1",
    ]

    opened = invoke(registry, scope, "get_evidence", references=[e.evidence_id for e in issued] + canonical)

    assert opened.outcome == "data" and opened.data["unresolved"] == []
    returned = records(opened)
    assert [(e.run, e.record_type, e.record_id) for e in returned[: len(issued)]] == [
        (e.run, e.record_type, e.record_id) for e in issued
    ]
    assert [e.record_type for e in returned[len(issued):]] == [
        "tool_metadata", "website_capture", "ai_evidence_sentence", "category_neighbor",
    ]
    context = next(r for r in opened.data["resolved"] if r["reference"]["kind"] == "usage_context")
    api = world.client.post("/evidence/resolve", json={"reference": context["reference"]}).json()
    assert context == api
    # Evidence returned by get_evidence opens again, so citations stay resolvable.
    again = invoke(registry, scope, "get_evidence", references=[e.evidence_id for e in returned])
    assert [(e.record_type, e.record_id) for e in records(again)] == [(e.record_type, e.record_id) for e in returned]


def test_get_evidence_enforces_the_pinned_scope(world, registry):
    run_id = world.current.run_id
    week = pinned(world, event_time=EventTimeRange(start="2026-10-01T00:00:00Z", end="2026-10-08T00:00:00Z"))
    inside = every_item(world, "/events", week)[0]["event_id"]
    outside = every_item(world, "/events", pinned(world))[0]["event_id"]  # the first event, in September
    sales = next(
        c for c in listing(world, "/contexts", pinned(world), limit=200)["items"] if c["department"] == "Sales"
    )

    mixed = invoke(
        registry, week, "get_evidence",
        references=[f"activity_event:{run_id}:{inside}", f"activity_event:{run_id}:{outside}",
                    f"activity_event:{run_id}:evt_missing"],
    )
    only_outside = invoke(registry, week, "get_evidence", references=[f"activity_event:{run_id}:{outside}"])
    other_department = invoke(
        registry, pinned(world, departments=("Engineering",)), "get_evidence",
        references=[f"usage_context:{run_id}:{sales['context_number']}"],
    )
    missing = invoke(registry, week, "get_evidence", references=[f"activity_event:{run_id}:evt_missing"])

    assert [r["reference"]["event_id"] for r in mixed.data["resolved"]] == [inside]
    assert {u["status"] for u in mixed.data["unresolved"]} == {"outside_scope", "not_found"}
    assert only_outside.status == other_department.status == "limited"
    assert only_outside.reason == "unsupported"
    assert (missing.status, missing.outcome) == ("succeeded", "no_matches")


@pytest.mark.parametrize(
    ("reference", "reason"),
    [
        ("passage:governance-v1:doc:1:p1", "unavailable"),
        ("step_1:aggregate:summarize_usage", "unsupported"),
        ("event_1", "unsupported"),
        ("usage_context:run_elsewhere:1", "unsupported"),
        ("usage_context:{run_id}:0", "unsupported"),
    ],
)
def test_unresolvable_references_are_limitations(world, registry, reference, reason):
    result = invoke(
        registry, pinned(world), "get_evidence", references=[reference.format(run_id=world.current.run_id)]
    )

    assert result.status == "limited" and result.reason == reason


# --- End to end --------------------------------------------------------------------------


def test_a_briefing_turn_runs_on_real_handlers_and_persists_cited_evidence(world):
    limits = ExecutionLimits()
    scope = pinned(world)

    def open_highest_tier(context):
        risks = next(s for s in context.observations if s.tool == "get_risk_assessments")
        return ToolCall(tool="get_evidence", arguments={"references": [records(risks.outcome)[0].evidence_id]})

    def answer(context):
        summary = next(s for s in context.observations if s.tool == "summarize_usage")
        opened = context.observations[-1]
        return AnswerDecision(
            findings=(
                Finding(
                    facts=(
                        FactualClaim(
                            text=f"{summary.outcome.data['total']} matching Activity Events.",
                            evidence_ids=(aggregate(summary.outcome).evidence_id,),
                        ),
                        FactualClaim(
                            text="The highest-tier Usage Context was inspected.",
                            evidence_ids=(records(opened.outcome)[0].evidence_id,),
                        ),
                    ),
                    interpretation="The flagged context deserves review; activity alone does not "
                    "establish sensitive-data submission.",
                ),
            )
        )

    model = ScriptedModel(open_highest_tier, answer)
    assistant = Assistant(world.engine, model, build_tool_registry(world.engine, world.settings, limits=limits), limits)

    turn = asyncio.run(assistant.run_turn(question="Brief me on this Batch.", scope=scope, briefing=True))

    assert turn.status == "succeeded" and isinstance(turn.answer, GroundedAnswer)
    steps, total = list_steps(world.engine, turn.turn_id)
    assert [s.tool for s in steps] == [
        "describe_dataset", "summarize_usage", "get_risk_assessments", "get_evidence",
    ]
    assert all(s.outcome.status == "succeeded" for s in steps)
    sources = tuple(e for s in steps for e in s.outcome.evidence)
    validate_answer_references(turn.answer, sources)
    cited = [i for f in turn.answer.findings for claim in f.facts for i in claim.evidence_ids]
    for evidence_id in cited:
        stored = get_evidence(world.engine, turn.turn_id, evidence_id)
        assert stored.step_id in {s.step_id for s in steps}
        assert evidence_id.startswith(f"{stored.step_id}:")
    opened = steps[-1].outcome
    assert opened.data["resolved"][0]["reference"]["kind"] == "usage_context"
    assert opened.data["resolved"][0]["record"]["tier"] == steps[2].outcome.data["assessments"][0]["tier"]
