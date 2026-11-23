import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import func, inspect, select

from app.ai_determination.cascade import AiDetermination
from app.category.classify import CategoryClassification
from app.db.engine import MIGRATIONS_DIR, migrate
from app.db.tables import (
    ai_determinations,
    category_classifications,
    metadata,
    tool_candidates,
    usage_context_assessments,
    website_captures,
)
from app.enrichment.fetch import Capture
from app.pipeline import Phase, Pipeline
from app.pipeline.identity import CandidateIdentity
from app.results import get_capture, list_candidates, no_risk_tier_reasons, save_stage_results
from tests.test_default_pipeline import (
    ServesOnlyMeetOscar,
    fixture_client,
    unavailable_jev,
    upload_fixture,
)
from tests.test_risk_results import ServesEveryHomepage

STAGE_TABLES = (tool_candidates, ai_determinations, category_classifications, website_captures)


def analyzed(data_dir, http=None):
    client = fixture_client(data_dir, http=http or ServesEveryHomepage())
    run = upload_fixture(client).json()["latest_run"]
    assert run["status"] == "succeeded"
    return client, run["run_id"]


def candidates_of(client, run_id):
    with client.app.state.engine.connect() as connection:
        return list_candidates(connection, run_id)


def row_counts(client):
    with client.app.state.engine.connect() as connection:
        return {
            table.name: connection.execute(select(func.count()).select_from(table)).scalar_one()
            for table in STAGE_TABLES
        }


def test_a_succeeded_run_saves_every_candidate_with_its_stage_outcomes(data_dir):
    client, run_id = analyzed(data_dir)

    candidates = candidates_of(client, run_id)

    assert [c["candidate_number"] for c in candidates] == list(range(1, 11))
    assert sum(c["event_count"] for c in candidates) == 265
    assert all(c["event_count"] == len(c["event_ids"]) for c in candidates)
    assert all(c["ai"] is not None and c["category"] is not None for c in candidates)

    by_name = {c["application_names"][0]: c for c in candidates}
    chatgpt = by_name["ChatGPT"]
    assert chatgpt["outcome"] == "known_tool"
    assert chatgpt["tool_id"].startswith("aitoolbuzz:")
    assert chatgpt["category"]["outcome"] == "assigned"
    assert chatgpt["category"]["method"] == "catalog"
    assert chatgpt["category"]["source"]["kind"] == "catalog"


def test_unresolved_and_non_ai_candidates_are_kept_without_a_risk_tier(data_dir):
    client, run_id = analyzed(data_dir)
    candidates = candidates_of(client, run_id)
    with client.app.state.engine.connect() as connection:
        assessed_tools = set(
            connection.execute(
                select(usage_context_assessments.c.tool_id).where(
                    usage_context_assessments.c.run_id == run_id
                )
            ).scalars()
        )

    workbench = next(c for c in candidates if c["application_names"][0] == "Workbench")
    assert workbench["outcome"] == "unresolved_candidate"
    assert workbench["tool_id"] is None
    assert workbench["reason"] == "insufficient_identity_evidence"

    assert "identity_unresolved" in workbench["no_risk_tier_reasons"]

    assessed = [c for c in candidates if c["tool_id"] in assessed_tools]
    not_assessed = [c for c in candidates if c["tool_id"] not in assessed_tools]
    assert assessed and not_assessed
    assert all(c["ai"]["determination"] == "ai" for c in assessed)
    assert all(c["no_risk_tier_reasons"] == [] for c in assessed)
    assert all(c["no_risk_tier_reasons"] for c in not_assessed)
    for candidate in not_assessed:
        if candidate["ai"]["determination"] != "ai":
            assert candidate["category"]["outcome"] == "inapplicable"


@pytest.mark.parametrize(
    ("outcome", "determination", "reasons"),
    [
        ("known_tool", "ai", ()),
        ("observed_tool", "ai", ()),
        ("known_tool", "non_ai", ("not_ai",)),
        ("observed_tool", "unresolved", ("ai_unresolved",)),
        ("unresolved_candidate", "ai", ("identity_unresolved",)),
        ("unresolved_candidate", "non_ai", ("identity_unresolved", "not_ai")),
        ("unresolved_candidate", "unresolved", ("identity_unresolved", "ai_unresolved")),
    ],
)
def test_no_risk_tier_reasons_follow_the_assessment_rule(outcome, determination, reasons):
    candidate = {"outcome": outcome, "ai": {"determination": determination}}

    assert no_risk_tier_reasons(candidate) == reasons


def test_ai_determinations_keep_their_evidence_fields(data_dir):
    client, run_id = analyzed(data_dir)

    for candidate in candidates_of(client, run_id):
        ai = candidate["ai"]
        assert ai["determination"] in {"ai", "non_ai", "unresolved"}
        assert isinstance(ai["evidence"], list)
        assert isinstance(ai["needs_review"], bool)
        for sentence in ai["evidence"]:
            assert set(sentence) == {"sentence", "probability"}
        if ai["probabilities"] is not None:
            assert {"ai", "non_ai", "unresolved"} <= set(ai["probabilities"])


def test_every_fetched_domain_keeps_its_capture(data_dir):
    client, run_id = analyzed(data_dir, http=ServesOnlyMeetOscar())
    domains = {c["domain"] for c in candidates_of(client, run_id)}

    with client.app.state.engine.connect() as connection:
        saved = set(
            connection.execute(
                select(website_captures.c.domain).where(website_captures.c.run_id == run_id)
            ).scalars()
        )
        meetoscar = get_capture(connection, run_id, "meetoscar.com")
        slack = get_capture(connection, run_id, "slack.com")
        missing = get_capture(connection, run_id, "never-fetched.example")

    assert saved == domains
    assert meetoscar["outcome"] == "extracted"
    assert "AI that summarizes meeting notes." in meetoscar["page_metadata"].values()
    assert meetoscar["main_text"] == "Summaries in seconds\nFor teams\nBody text."
    assert meetoscar["headings"] == ["Summaries in seconds", "For teams"]
    assert slack["outcome"] != "extracted"
    assert slack["main_text"] == ""
    assert missing is None


def test_reanalysis_saves_a_separate_copy_and_keeps_the_older_one(data_dir):
    client, first_run = analyzed(data_dir)
    batch_id = client.get(f"/runs/{first_run}").json()["batch_id"]
    before = candidates_of(client, first_run)

    second_run = client.post(f"/batches/{batch_id}/runs").json()["run_id"]

    assert candidates_of(client, first_run) == before
    assert len(candidates_of(client, second_run)) == len(before)


def test_a_failed_run_saves_no_stage_results(data_dir):
    client = fixture_client(data_dir, jev=unavailable_jev)

    run = upload_fixture(client).json()["latest_run"]

    assert run["status"] == "failed"
    assert set(row_counts(client).values()) == {0}


def test_stage_results_roll_back_when_a_later_save_step_fails(make_client):
    def save_then_fail(connection, context):
        save_stage_results(
            connection,
            context.run_id,
            [CandidateIdentity("x.example", ("X",), ("e1",), "unresolved_candidate")],
            [AiDetermination("unresolved", "insufficient_text")],
            [CategoryClassification("inapplicable", reason="ai_determination_unresolved")],
            {"x.example": Capture("https://x.example/", "2026-09-15T00:00:00Z", "fetch_failed")},
        )
        raise OSError("disk full")

    client = make_client()
    client.app.state.pipeline = Pipeline(
        phases=(Phase("noop", lambda context: None),), save=save_then_fail
    )

    run = upload_fixture(client).json()["latest_run"]

    assert run["status"] == "failed"
    assert run["failure"]["phase"] == "save_results"
    assert set(row_counts(client).values()) == {0}


def test_stage_results_must_be_parallel(make_client):
    client = make_client()
    candidate = CandidateIdentity("x.example", ("X",), ("e1",), "unresolved_candidate")

    with client.app.state.engine.begin() as connection, pytest.raises(ValueError):
        save_stage_results(connection, "run_x", [candidate], [], [], {})


def test_a_succeeded_runs_stage_results_survive_a_server_restart(data_dir):
    client, run_id = analyzed(data_dir, http=ServesOnlyMeetOscar())
    before = candidates_of(client, run_id)
    with client.app.state.engine.connect() as connection:
        captures = {c["domain"]: get_capture(connection, run_id, c["domain"]) for c in before}
    client.app.state.engine.dispose()

    restarted = fixture_client(data_dir)

    assert candidates_of(restarted, run_id) == before
    with restarted.app.state.engine.connect() as connection:
        assert {d: get_capture(connection, run_id, d) for d in captures} == captures
    assert restarted.get(f"/runs/{run_id}").json()["status"] == "succeeded"


def test_migrations_match_the_table_definitions_and_0007_downgrades(client):
    engine = client.app.state.engine
    with engine.connect() as connection:
        assert compare_metadata(MigrationContext.configure(connection), metadata) == []

    with engine.begin() as connection:
        config = Config()
        config.set_main_option("script_location", str(MIGRATIONS_DIR))
        config.attributes["connection"] = connection
        command.downgrade(config, "0006")
    with engine.connect() as connection:
        assert not {table.name for table in STAGE_TABLES} & set(inspect(connection).get_table_names())

    migrate(engine)
    assert set(row_counts(client).values()) == {0}
