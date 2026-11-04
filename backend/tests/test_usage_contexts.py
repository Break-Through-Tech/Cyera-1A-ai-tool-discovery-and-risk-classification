import csv

from app.ai_determination.cascade import AiDetermination
from app.config import REPO_DIR, Settings
from app.ingestion.activity import parse_activity
from app.pipeline import Phase, Pipeline
from app.pipeline.identity import (
    CandidateIdentity,
    ToolMetadataSnapshot,
    load_registry,
    load_tool_metadata,
    resolve_identities,
)
from app.pipeline.usage_contexts import assess_usage_contexts, risk_facts
from tests.test_default_pipeline import fixture_client, upload_fixture
from tests.test_identity_fixture import FIXTURE

SCENARIOS = REPO_DIR / "data/synthetic_enterprise_activity/v1/evaluation_only/expected_scenarios.csv"


def load_scenarios():
    with SCENARIOS.open(encoding="utf-8", newline="") as stream:
        return list(csv.DictReader(stream))


def answer_key_ai(candidates, scenarios):
    """Each candidate's AI status as the scenarios label it, so only the risk step is under test."""
    statuses = []
    for candidate in candidates:
        labels = {
            s["expected_ai_status"]
            for s in scenarios
            if set(s["event_ids"].split("|")) <= set(candidate.event_ids)
        }
        assert len(labels) == 1, candidate.application_names
        statuses.append(AiDetermination(labels.pop(), "answer_key"))
    return statuses


def test_fixture_usage_contexts_match_the_expected_scenarios(tmp_path):
    settings = Settings(data_dir=tmp_path)
    registry = load_registry(settings.catalog_path, settings.registry_exclusions_path)
    metadata = load_tool_metadata(settings.tool_metadata_path)
    events = parse_activity(FIXTURE.read_bytes())
    candidates = resolve_identities("bat_fixture", events, registry, metadata)
    scenarios = load_scenarios()

    assessed = assess_usage_contexts(
        events, candidates, answer_key_ai(candidates, scenarios), metadata
    )

    actual = {
        frozenset(a.context.event_ids): (a.assessment.tier, a.assessment.investigation_flag)
        for a in assessed
    }
    expected = {
        frozenset(s["event_ids"].split("|")): (
            s["expected_risk_behavior"],
            s["expected_investigation_flag"] == "true",
        )
        for s in scenarios
        if s["expected_risk_behavior"] not in ("not_applicable", "not_assessed_ai_unresolved")
    }
    assert actual == expected


def test_contexts_keep_their_period_facts_and_rule_version(tmp_path):
    settings = Settings(data_dir=tmp_path)
    metadata = load_tool_metadata(settings.tool_metadata_path)
    events = parse_activity(FIXTURE.read_bytes())
    candidates = resolve_identities(
        "bat_fixture",
        events,
        load_registry(settings.catalog_path, settings.registry_exclusions_path),
        metadata,
    )

    assessed = assess_usage_contexts(
        events, candidates, answer_key_ai(candidates, load_scenarios()), metadata
    )

    cursor = next(a for a in assessed if a.metadata_id == "meta_02")
    assert cursor.context.department == "Engineering"
    assert cursor.context.first_observed_at <= cursor.context.last_observed_at
    assert cursor.facts == risk_facts({"approved_status": "unapproved"})
    assert cursor.assessment.flag_reasons == ["unapproved_tool"]
    assert cursor.rule_version == "synthetic-demo-risk-v1"


def candidate(event_ids, outcome="observed_tool", name="Tool", domain="tool.example"):
    return CandidateIdentity(domain, (name,), event_ids, outcome, tool_id=f"tool:{name}")


def event(event_id, department="Sales", purpose="notes", sensitivity="internal"):
    return {
        "event_id": event_id,
        "occurred_at": f"2026-09-15T0{event_id[-1]}:00:00Z",
        "department": department,
        "usage_purpose": purpose,
        "data_sensitivity_tier": sensitivity,
    }


NO_METADATA = ToolMetadataSnapshot(rows=())


def test_a_tool_without_dataset_b_facts_is_unresolved_not_medium():
    assessed = assess_usage_contexts(
        [event("e1")], [candidate(("e1",))], [AiDetermination("ai", "test")], NO_METADATA
    )

    assert [a.assessment.tier for a in assessed] == ["unresolved"]
    assert assessed[0].metadata_id is None
    assert assessed[0].assessment.flag_reasons == ["insufficient_evidence_for_tier"]


def test_non_ai_unresolved_ai_and_unresolved_identity_get_no_context():
    candidates = [
        candidate(("e1",), name="A"),
        candidate(("e2",), name="B"),
        candidate(("e3",), outcome="unresolved_candidate", name="C"),
    ]
    ai = [
        AiDetermination("non_ai", "test"),
        AiDetermination("unresolved", "test"),
        AiDetermination("ai", "test"),
    ]

    assessed = assess_usage_contexts(
        [event("e1"), event("e2"), event("e3")], candidates, ai, NO_METADATA
    )

    assert assessed == []


def test_one_tool_splits_by_department_purpose_and_sensitivity_with_blanks_unknown():
    events = [
        event("e1"),
        event("e2"),
        event("e3", department="Finance"),
        event("e4", purpose=None, sensitivity=""),
    ]

    assessed = assess_usage_contexts(
        events, [candidate(("e1", "e2", "e3", "e4"))], [AiDetermination("ai", "test")], NO_METADATA
    )

    contexts = {
        (a.context.department, a.context.usage_purpose, a.context.data_sensitivity_tier): (
            a.context.event_ids,
            a.context.first_observed_at,
            a.context.last_observed_at,
        )
        for a in assessed
    }
    assert contexts == {
        ("Sales", "notes", "internal"): (("e1", "e2"), "2026-09-15T01:00:00Z", "2026-09-15T02:00:00Z"),
        ("Finance", "notes", "internal"): (("e3",), "2026-09-15T03:00:00Z", "2026-09-15T03:00:00Z"),
        ("Sales", "unknown", "unknown"): (("e4",), "2026-09-15T04:00:00Z", "2026-09-15T04:00:00Z"),
    }


def test_default_pipeline_runs_risk_assessment_last_and_pins_the_rule_version(data_dir):
    captured = {}
    client = fixture_client(data_dir)
    pipeline = client.app.state.pipeline
    client.app.state.pipeline = Pipeline(
        phases=(*pipeline.phases, Phase("capture", lambda context: captured.update(context.results))),
        versions=pipeline.versions,
    )

    run = upload_fixture(client).json()["latest_run"]

    assert run["status"] == "succeeded"
    assert pipeline.phases[-1].name == "risk_assessment"
    assert run["versions"]["risk_assessment"] == "synthetic-demo-risk-v1"
    assessed = captured["risk_assessments"]
    assert assessed
    resolved_ai = {
        c.tool_id
        for c, ai in zip(captured["identities"], captured["ai_determinations"], strict=True)
        if ai.determination == "ai" and c.outcome != "unresolved_candidate"
    }
    assert {a.context.tool_id for a in assessed} == resolved_ai
