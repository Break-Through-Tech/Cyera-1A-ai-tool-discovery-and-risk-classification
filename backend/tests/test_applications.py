from app.ai_determination.cascade import AiDetermination, EvidenceSource
from app.applications import get_application, list_application_summaries
from app.category.classify import CategoryClassification
from app.pipeline import Phase, Pipeline
from app.pipeline.identity import CandidateIdentity
from app.pipeline.risk import RiskFacts, assess
from app.pipeline.usage_contexts import ContextAssessment, UsageContext
from app.results import save_assessments, save_stage_results
from tests.test_default_pipeline import fixture_client, unavailable_jev, upload_fixture
from tests.test_risk_results import ServesEveryHomepage


def analyzed(data_dir, http=None):
    client = fixture_client(data_dir, http=http)
    run = upload_fixture(client).json()["latest_run"]
    assert run["status"] == "succeeded"
    return client, run["run_id"]


def summaries_of(client, run_id):
    with client.app.state.engine.connect() as connection:
        return list_application_summaries(connection, [run_id])


def subject_named(client, run_id, name):
    summary = next(s for s in summaries_of(client, run_id) if name in s.application_names)
    return f"/runs/{run_id}/applications/{summary.subject_kind}/{summary.subject_id}"


def test_every_candidate_belongs_to_exactly_one_application(data_dir):
    client, run_id = analyzed(data_dir)

    summaries = summaries_of(client, run_id)
    contexts = client.get(f"/runs/{run_id}/assessments").json()["total"]

    numbers = [n for s in summaries for n in s.candidate_numbers]
    assert numbers == list(range(1, 11))
    assert sum(s.event_count for s in summaries) == 265
    assert sum(s.context_count for s in summaries) == contexts
    kinds = {s.application_names[0]: (s.subject_kind, s.identity_outcome) for s in summaries}
    assert kinds["Workbench"] == ("candidate", "unresolved_candidate")
    assert kinds["Slack"] == ("tool", "observed_tool")
    assert all(s.risk_outcome == "inapplicable" for s in summaries if s.context_count == 0)


def test_a_resolved_ai_tool_shows_its_determinations_contexts_and_tiers(data_dir):
    client, run_id = analyzed(data_dir, http=ServesEveryHomepage())

    response = client.get(subject_named(client, run_id, "ChatGPT"))

    assert response.status_code == 200
    detail = response.json()
    assert detail["summary"]["subject_kind"] == "tool"
    assert detail["summary"]["subject_id"].startswith("aitoolbuzz:")
    assert detail["summary"]["ai_determination"] == "ai"
    assert detail["identity"]["outcome"] == "known_tool"
    assert detail["identity"]["basis"] == "exact_root_domain"
    assert len(detail["identity"]["catalog_tool_ids"]) == 1
    [candidate] = detail["candidates"]
    ai = candidate["ai_determination"]
    assert ai["determination"] == "ai"
    assert ai["stage"] == "jev_judge"
    assert ai["source"]["kind"] == "homepage"
    assert ai["probabilities"]["ai"] >= 0.4
    category = candidate["category_classification"]
    assert (category["outcome"], category["method"]) == ("assigned", "catalog")
    assert detail["summary"]["category"] == category["category"]

    contexts = detail["usage_contexts"]
    assert contexts["outcome"] == "applicable" and contexts["reason"] is None
    assert contexts["count"] == len(contexts["references"]) == 2
    assert contexts["departments"] == ["Engineering", "Finance"]
    assert contexts["event_count"] == detail["activity"]["event_count"]
    assert {ref["tier"] for ref in contexts["references"]} == {"Lower"}
    assessments = client.get(f"/runs/{run_id}/assessments").json()["items"]
    numbers = {ref["context_number"] for ref in contexts["references"]}
    assert {a["application_name"] for a in assessments if a["context_number"] in numbers} == {
        "ChatGPT"
    }
    assert detail["policy_status"] == {
        "outcome": "applicable",
        "reason": None,
        "statuses": ["approved"],
    }
    assert detail["risk"]["outcome"] == "assessed"
    assert detail["risk"]["highest_tier"] == "Lower"
    assert detail["risk"]["tier_counts"] == {"Lower": 2}
    assert detail["risk"]["investigation_flag"] is False
    assert detail["risk"]["rule_versions"] == ["synthetic-demo-risk-v1"]


def test_a_flagged_tool_explains_why(data_dir):
    client, run_id = analyzed(data_dir, http=ServesEveryHomepage())
    flagged = next(s for s in summaries_of(client, run_id) if s.investigation_flag)

    detail = client.get(
        f"/runs/{run_id}/applications/tool/{flagged.subject_id}"
    ).json()

    assert detail["risk"]["investigation_flag"] is True
    assert detail["risk"]["flag_reasons"]
    assert any(ref["flag_reasons"] for ref in detail["usage_contexts"]["references"])


def test_a_non_ai_tool_has_determinations_but_no_context_or_tier(data_dir):
    client, run_id = analyzed(data_dir)

    detail = client.get(subject_named(client, run_id, "Slack")).json()

    assert detail["summary"]["ai_determination"] == "non_ai"
    assert detail["summary"]["highest_tier"] is None
    [candidate] = detail["candidates"]
    assert candidate["ai_determination"]["stage"] == "keyword_gate"
    assert candidate["category_classification"]["outcome"] == "inapplicable"
    assert candidate["category_classification"]["reason"] == "ai_determination_non_ai"
    assert detail["activity"]["event_count"] == detail["summary"]["event_count"] > 0
    assert detail["usage_contexts"]["outcome"] == "inapplicable"
    assert detail["usage_contexts"]["reason"] == "ai_determination_non_ai"
    assert detail["usage_contexts"]["references"] == []
    assert detail["policy_status"] == {
        "outcome": "inapplicable",
        "reason": "no_usage_context",
        "statuses": [],
    }
    assert detail["risk"]["outcome"] == "inapplicable"
    assert detail["risk"]["reason"] == "ai_determination_non_ai"
    assert detail["risk"]["tier_counts"] == {}


def test_an_unresolved_candidate_shows_its_determinations_without_a_tier(data_dir):
    client, run_id = analyzed(data_dir)

    response = client.get(f"/runs/{run_id}/applications/candidate/10")

    assert response.status_code == 200
    detail = response.json()
    assert detail["summary"]["application_names"] == ["Workbench"]
    assert detail["identity"] == {
        "outcome": "unresolved_candidate",
        "tool_id": None,
        "basis": None,
        "reason": "insufficient_identity_evidence",
        "catalog_tool_ids": [],
    }
    ai = detail["candidates"][0]["ai_determination"]
    assert (ai["determination"], ai["stage"], ai["reason"]) == (
        "unresolved",
        "no_evidence",
        "blocked_destination",
    )
    assert detail["activity"]["first_observed_at"] <= detail["activity"]["last_observed_at"]
    assert detail["usage_contexts"]["reason"] == "identity_unresolved"
    assert detail["risk"] == {
        "outcome": "inapplicable",
        "reason": "identity_unresolved",
        "highest_tier": None,
        "tier_counts": {},
        "investigation_flag": False,
        "flag_reasons": [],
        "rule_versions": [],
    }


def test_candidates_resolved_to_one_tool_form_one_application(make_client):
    tool = "aitoolbuzz:x"
    known = {"outcome": "known_tool", "tool_id": tool, "basis": "exact_root_domain"}
    identities = [
        CandidateIdentity("x.example", ("X",), ("evt_000001",), **known, catalog_tool_ids=("x",)),
        CandidateIdentity(
            "x.example", ("X Desktop",), ("evt_000002", "evt_000003"), **known,
            catalog_tool_ids=("x",),
        ),
        CandidateIdentity(
            "y.internal", ("Y",), ("evt_000004",), "unresolved_candidate",
            reason="insufficient_identity_evidence",
        ),
    ]
    ai = [
        AiDetermination("non_ai", "keyword_gate"),
        AiDetermination("ai", "jev_judge", model="jev-test"),
        AiDetermination("ai", "jev_judge", model="jev-test"),
    ]
    catalog = EvidenceSource("catalog", "x", version="test")
    categories = [
        CategoryClassification("inapplicable", reason="ai_determination_non_ai"),
        CategoryClassification("assigned", "catalog", "Writing", source=catalog),
        CategoryClassification(
            "unresolved", "semantic_neighbor_vote", reason="neighbor_vote_below_cutoff", share=0.2
        ),
    ]
    facts = RiskFacts(policy_status="unapproved", training_on_customer_data="yes")
    context = UsageContext(
        tool, "X Desktop", "x.example", "Sales", "notes", "internal",
        ("evt_000002", "evt_000003"), "2026-09-15T08:22:00Z", "2026-09-15T08:33:00Z",
    )

    def save(connection, run):
        save_stage_results(connection, run.run_id, identities, ai, categories, {})
        assessed = [ContextAssessment(context, None, facts, assess(facts))]
        save_assessments(connection, run.run_id, assessed, {})

    client = make_client()
    client.app.state.pipeline = Pipeline(phases=(Phase("noop", lambda run: None),), save=save)
    run = upload_fixture(client).json()["latest_run"]
    run_id = run["run_id"]

    [x, y] = summaries_of(client, run_id)
    assert (x.subject_kind, x.subject_id, x.candidate_numbers) == ("tool", tool, (1, 2))
    assert x.application_names == ("X", "X Desktop")
    assert (x.ai_determination, x.category_outcome, x.category) == ("ai", "assigned", "Writing")
    assert (x.context_count, x.highest_tier, x.investigation_flag) == (1, "High", True)
    assert x.policy_statuses == ("unapproved",)
    assert (y.subject_kind, y.subject_id, y.ai_determination) == ("candidate", "3", "ai")
    assert (y.category_outcome, y.risk_outcome) == ("unresolved", "inapplicable")

    with client.app.state.engine.connect() as connection:
        detail = get_application(connection, run_id, run["batch_id"], "tool", tool)
    assert [c["candidate_number"] for c in detail["candidates"]] == [1, 2]
    assert detail["activity"]["event_count"] == 3
    assert detail["risk"]["flag_reasons"] == [
        "high_tier", "unapproved_tool", "customer_data_training_permitted"
    ]
    response = client.get(f"/runs/{run_id}/applications/candidate/3")
    assert response.json()["candidates"][0]["ai_determination"]["determination"] == "ai"
    assert response.json()["risk"]["reason"] == "identity_unresolved"


def test_unknown_run_is_not_found(data_dir):
    client, _ = analyzed(data_dir)

    response = client.get("/runs/run_missing/applications/candidate/1")

    assert response.status_code == 404
    assert response.json()["code"] == "run_not_found"


def test_unknown_subjects_are_not_found(data_dir):
    client, run_id = analyzed(data_dir)
    resolved = subject_named(client, run_id, "Slack")
    resolved_number = next(
        s.candidate_numbers[0] for s in summaries_of(client, run_id) if s.subject_kind == "tool"
    )

    for path in (
        f"/runs/{run_id}/applications/tool/observed:missing",
        f"/runs/{run_id}/applications/candidate/99",
        # A resolved candidate is addressed through its Tool.
        f"/runs/{run_id}/applications/candidate/{resolved_number}",
    ):
        response = client.get(path)
        assert response.status_code == 404, path
        assert response.json()["code"] == "application_not_found"
    assert client.get(resolved).status_code == 200


def test_a_failed_run_has_no_applications(data_dir):
    client = fixture_client(data_dir, jev=unavailable_jev)
    run = upload_fixture(client).json()["latest_run"]

    response = client.get(f"/runs/{run['run_id']}/applications/candidate/1")

    assert run["status"] == "failed"
    assert response.status_code == 409
    assert response.json()["code"] == "run_not_succeeded"


def test_an_unsupported_subject_kind_or_candidate_number_is_rejected(data_dir):
    client, run_id = analyzed(data_dir)

    for path, location in (
        ("widget/1", ["path", "subject_kind"]),
        ("candidate/one", ["path", "subject_id"]),
        ("candidate/0", ["path", "subject_id"]),
    ):
        response = client.get(f"/runs/{run_id}/applications/{path}")
        assert response.status_code == 422, path
        assert response.json()["details"]["errors"][0]["location"] == location
