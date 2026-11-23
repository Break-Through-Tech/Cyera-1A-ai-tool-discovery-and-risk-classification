import pytest
from pydantic import ValidationError
from sqlalchemy import insert

from app.assistant.contracts import RecordEvidence, RunReference
from app.db.tables import website_captures
from app.evidence import (
    MAX_ITEMS,
    MAX_TEXT_CHARS,
    ActivityEventReference,
    Applicability,
    AiEvidenceSentenceReference,
    CategoryNeighborReference,
    EvidenceError,
    EvidenceSources,
    PassageReference,
    ResolvedEvidence,
    SourceIdentity,
    ToolMetadataReference,
    UsageContextReference,
    WebsiteCaptureReference,
    from_record_evidence,
    record_reference,
    resolve_evidence,
    to_record_evidence,
)
from app.pipeline import Phase
from app.pipeline.identity import ToolMetadataSnapshot
from app.results import list_candidates
from tests.test_batches import upload
from tests.test_default_pipeline import fixture_client, upload_fixture
from tests.test_risk_results import ServesEveryHomepage


@pytest.fixture(scope="module")
def analyzed(tmp_path_factory):
    """One succeeded fixture Run in which every homepage was captured and judged AI."""
    client = fixture_client(tmp_path_factory.mktemp("data"), http=ServesEveryHomepage())
    batch = upload_fixture(client).json()
    assert batch["latest_run"]["status"] == "succeeded"
    run = {"batch_id": batch["batch_id"], "run_id": batch["latest_run"]["run_id"]}
    with client.app.state.engine.connect() as connection:
        saved = list_candidates(connection, run["run_id"])
    candidates = {c["application_names"][0]: c for c in saved}
    return client, run, candidates


def resolve(client, reference):
    return client.post("/evidence/resolve", json={"reference": reference})


def resolved(client, reference):
    response = resolve(client, reference)
    assert response.status_code == 200, response.json()
    return response.json()


def test_an_activity_event_resolves_as_observed_activity(analyzed):
    client, run, candidates = analyzed
    event_id = candidates["ChatGPT"]["event_ids"][0]

    evidence = resolved(client, {"kind": "activity_event", "run": run, "event_id": event_id})

    assert evidence["role"] == "observed_activity"
    assert evidence["source"]["type"] == "activity_event"
    assert evidence["source"]["id"] == evidence["record"]["event_id"] == event_id
    assert evidence["source"]["version"].startswith("sha256:")
    assert (evidence["source"]["batch_id"], evidence["source"]["run_id"]) == (
        run["batch_id"],
        run["run_id"],
    )
    assert evidence["record"]["application_name"] == "ChatGPT"
    assert evidence["dates"]["occurred_at"] == evidence["record"]["occurred_at"]
    assert set(evidence["versions"]) == {"batch_schema"}
    assert evidence["applicability"]["subject_type"] == "activity_event"
    assert evidence["truncated"] is False and evidence["truncations"] == []


def test_a_usage_context_resolves_to_its_assessment_with_bounded_event_ids(analyzed):
    client, run, _ = analyzed
    contexts = client.get(f"/runs/{run['run_id']}/assessments").json()["items"]
    large = next(c for c in contexts if c["event_count"] > MAX_ITEMS)

    evidence = resolved(
        client, {"kind": "usage_context", "run": run, "context_number": large["context_number"]}
    )

    assert evidence["role"] == "analysis_result"
    assert evidence["source"]["type"] == "usage_context_assessment"
    assert evidence["source"]["version"] == large["rule_version"]
    record = evidence["record"]
    assert {k: record[k] for k in ("tier", "facts", "reason_codes", "unknown_facts")} == {
        k: large[k] for k in ("tier", "facts", "reason_codes", "unknown_facts")
    }
    assert record["event_ids"] == large["event_ids"][:MAX_ITEMS]
    assert record["event_count"] == large["event_count"]
    assert evidence["truncated"] is True
    assert evidence["truncations"] == [
        {
            "field": "event_ids",
            "unit": "items",
            "returned": MAX_ITEMS,
            "total": large["event_count"],
        }
    ]
    assert evidence["dates"]["first_observed_at"] == large["first_observed_at"]
    assert evidence["versions"]["rule_version"] == large["rule_version"]
    assert "tool_metadata_snapshot" in evidence["versions"]


def test_an_analysis_run_resolves_to_its_status_and_versions(analyzed):
    client, run, _ = analyzed

    evidence = resolved(client, {"kind": "analysis_run", "run": run})

    assert evidence["role"] == "analysis_provenance"
    assert evidence["record"]["status"] == "succeeded"
    assert evidence["versions"] == client.get(f"/runs/{run['run_id']}").json()["versions"]


def test_a_homepage_evidence_sentence_is_a_vendor_claim_scored_by_a_model(analyzed):
    client, run, candidates = analyzed
    chatgpt = candidates["ChatGPT"]

    evidence = resolved(
        client,
        {
            "kind": "ai_evidence_sentence",
            "run": run,
            "candidate_number": chatgpt["candidate_number"],
            "sentence_number": 1,
        },
    )

    first = chatgpt["ai"]["evidence"][0]
    assert evidence["role"] == "vendor_claim"
    assert evidence["source"]["type"] == "homepage"
    assert evidence["source"]["url"] == chatgpt["ai"]["source"]["reference"]
    assert evidence["dates"]["captured_at"] == chatgpt["ai"]["source"]["captured_at"]
    assert evidence["record"]["sentence"] == first["sentence"]
    assert evidence["record"]["sentence_count"] == len(chatgpt["ai"]["evidence"])
    assert evidence["record"]["scored_by"]["role"] == "model_output"
    assert evidence["record"]["scored_by"]["probability"] == first["probability"]
    assert evidence["record"]["determination"]["determination"] == "ai"
    assert set(evidence["versions"]) == {"ai_determination", "website_enrichment"}


def test_a_supplied_description_sentence_is_synthetic_policy(analyzed):
    client, run, candidates = analyzed
    supplied = next(
        c for c in candidates.values()
        if c["ai"]["source"] and c["ai"]["source"]["kind"] == "supplied_description"
    )

    evidence = resolved(
        client,
        {
            "kind": "ai_evidence_sentence",
            "run": run,
            "candidate_number": supplied["candidate_number"],
            "sentence_number": 1,
        },
    )

    assert evidence["role"] == "synthetic_policy"
    assert evidence["source"]["id"] == supplied["metadata_id"]
    assert evidence["source"]["url"] is None
    assert set(evidence["versions"]) == {"ai_determination", "tool_metadata_snapshot"}


def test_a_website_capture_resolves_as_a_vendor_claim(analyzed):
    client, run, _ = analyzed

    evidence = resolved(client, {"kind": "website_capture", "run": run, "domain": "chatgpt.com"})

    assert evidence["role"] == "vendor_claim"
    assert evidence["source"] == {
        "type": "website_capture",
        "id": "chatgpt.com",
        "batch_id": run["batch_id"],
        "run_id": run["run_id"],
        "version": None,
        "url": "https://chatgpt.com/",
    }
    assert evidence["record"]["outcome"] == "extracted"
    assert evidence["record"]["main_text"]
    assert set(evidence["versions"]) == {"website_enrichment"}
    assert evidence["truncated"] is False


def test_long_capture_text_and_lists_are_truncated_explicitly(analyzed):
    client, run, _ = analyzed
    with client.app.state.engine.begin() as connection:
        connection.execute(
            insert(website_captures).values(
                run_id=run["run_id"],
                domain="long.example",
                requested_url="https://long.example/",
                captured_at="2026-10-01T00:00:00Z",
                outcome="extracted",
                page_metadata={"description": "short"},
                headings=[f"Heading {n}" for n in range(MAX_ITEMS + 5)],
                main_text="x" * (MAX_TEXT_CHARS + 10),
            )
        )

    evidence = resolved(client, {"kind": "website_capture", "run": run, "domain": "long.example"})

    assert len(evidence["record"]["main_text"]) == MAX_TEXT_CHARS
    assert len(evidence["record"]["headings"]) == MAX_ITEMS
    assert evidence["truncated"] is True
    assert evidence["truncations"] == [
        {"field": "headings", "unit": "items", "returned": MAX_ITEMS, "total": MAX_ITEMS + 5},
        {
            "field": "main_text",
            "unit": "characters",
            "returned": MAX_TEXT_CHARS,
            "total": MAX_TEXT_CHARS + 10,
        },
    ]


def test_a_tool_metadata_row_resolves_as_synthetic_policy(analyzed):
    client, run, candidates = analyzed
    metadata_id = candidates["MeetOscar"]["metadata_id"]

    evidence = resolved(client, {"kind": "tool_metadata", "run": run, "metadata_id": metadata_id})

    assert evidence["role"] == "synthetic_policy"
    assert evidence["source"]["type"] == "tool_metadata_row"
    assert evidence["record"]["metadata_id"] == metadata_id
    assert evidence["record"]["governance_fact_basis"] == "synthetic_demonstration_assumption"
    assert evidence["source"]["version"] == evidence["versions"]["tool_metadata_snapshot"]


def test_a_tool_metadata_snapshot_other_than_the_runs_is_not_served(analyzed):
    client, run, _ = analyzed
    reference = ToolMetadataReference(run=RunReference(**run), metadata_id="meta_01")
    other = ToolMetadataSnapshot([], "other.csv;rows=0")

    with client.app.state.engine.connect() as connection:
        with pytest.raises(EvidenceError) as error:
            resolve_evidence(connection, reference, EvidenceSources(tool_metadata=other))

    assert (error.value.status_code, error.value.code) == (404, "source_version_unavailable")


def test_a_category_neighbor_resolves_as_model_output(analyzed):
    client, run, candidates = analyzed
    voted = next(c for c in candidates.values() if c["category"]["neighbors"])

    evidence = resolved(
        client,
        {
            "kind": "category_neighbor",
            "run": run,
            "candidate_number": voted["candidate_number"],
            "neighbor_number": 2,
        },
    )

    neighbor = voted["category"]["neighbors"][1]
    assert evidence["role"] == "model_output"
    assert evidence["source"]["type"] == "catalog_tool"
    assert evidence["source"]["id"] == neighbor["tool_id"]
    assert evidence["record"]["similarity"] == neighbor["similarity"]
    assert evidence["record"]["classification"]["method"] == "semantic_neighbor_vote"
    assert "category_classification" in evidence["versions"]


PASSAGE = {
    "kind": "passage",
    "corpus_version": "governance-v1",
    "document_id": "doc",
    "document_version": "1",
    "passage_id": "p1",
}


def test_a_passage_is_reported_unavailable_until_a_corpus_exists(analyzed):
    client, _, _ = analyzed

    response = resolve(client, PASSAGE)

    assert response.status_code == 501
    assert response.json()["code"] == "passage_corpus_unavailable"


def test_a_passage_resolver_can_be_plugged_in(analyzed):
    client, _, _ = analyzed
    reference = PassageReference(**PASSAGE)

    def passages(connection, reference):
        return ResolvedEvidence(
            reference=reference,
            role="governance_guidance",
            source=SourceIdentity(
                type="passage", id=reference.passage_id, version=reference.corpus_version
            ),
            dates={},
            applicability=Applicability(
                subject_type="passage", subject_id="p1", statement="Guidance."
            ),
            versions={"corpus": reference.corpus_version},
            record={"excerpt": "Review AI tools."},
        )

    with client.app.state.engine.connect() as connection:
        evidence = resolve_evidence(connection, reference, EvidenceSources(passages=passages))

    assert evidence.role == "governance_guidance"


def test_an_aggregate_reference_is_routed_to_the_listing_operations(analyzed):
    client, run, _ = analyzed

    response = resolve(
        client, {"kind": "aggregate", "operation": "summarize_usage", "scope": {"runs": [run]}}
    )

    assert response.status_code == 422
    body = response.json()
    assert body["code"] == "aggregate_reference_not_resolvable"
    assert "GET /overview" in body["details"]["listing_operations"]


@pytest.mark.parametrize(
    ("reference", "code"),
    [
        ({"kind": "activity_event", "event_id": "evt_missing"}, "activity_event_not_found"),
        ({"kind": "usage_context", "context_number": 9999}, "usage_context_not_found"),
        (
            {"kind": "ai_evidence_sentence", "candidate_number": 9999, "sentence_number": 1},
            "candidate_not_found",
        ),
        (
            {"kind": "ai_evidence_sentence", "candidate_number": 1, "sentence_number": 99},
            "evidence_sentence_not_found",
        ),
        (
            {"kind": "category_neighbor", "candidate_number": 1, "neighbor_number": 99},
            "category_neighbor_not_found",
        ),
        ({"kind": "website_capture", "domain": "unseen.example"}, "website_capture_not_found"),
        ({"kind": "tool_metadata", "metadata_id": "meta_missing"}, "tool_metadata_not_found"),
    ],
)
def test_unknown_records_are_not_found(analyzed, reference, code):
    client, run, _ = analyzed

    response = resolve(client, {**reference, "run": run})

    assert response.status_code == 404
    assert response.json()["code"] == code


@pytest.mark.parametrize(
    "run",
    [
        {"batch_id": "bat_missing", "run_id": "run_missing"},
        {"batch_id": "bat_other"},  # a real Run under the wrong Batch
    ],
)
def test_an_unknown_or_mismatched_run_is_not_found(analyzed, run):
    client, real, _ = analyzed
    run = {"run_id": real["run_id"], **run}

    response = resolve(client, {"kind": "analysis_run", "run": run})

    assert response.status_code == 404
    assert response.json()["code"] == "run_not_found"


@pytest.mark.parametrize(
    "reference",
    [
        {"kind": "activity_event"},
        {"kind": "usage_context", "context_number": 0},
        {"kind": "usage_context", "context_number": "1"},
        {"kind": "website_capture", "domain": ""},
        {"kind": "activity_event", "event_id": "e", "extra": 1},
        {"kind": "spreadsheet_cell", "cell": "A1"},
    ],
)
def test_malformed_references_are_rejected(analyzed, reference):
    client, run, _ = analyzed

    response = resolve(client, {**reference, "run": run})

    assert response.status_code == 422
    assert response.json()["code"] == "invalid_request"


def test_a_missing_reference_body_is_rejected(analyzed):
    client, _, _ = analyzed

    assert client.post("/evidence/resolve", json={}).status_code == 422
    assert client.post("/evidence/resolve", json={"references": []}).status_code == 422


def test_a_failed_run_exposes_its_status_but_no_findings(make_client):
    def fail(context):
        raise RuntimeError("boom")

    client = make_client(Phase("detect", fail))
    batch = upload(client).json()
    run = {"batch_id": batch["batch_id"], "run_id": batch["latest_run"]["run_id"]}

    finding = resolve(client, {"kind": "activity_event", "run": run, "event_id": "evt_1"})
    status = resolve(client, {"kind": "analysis_run", "run": run})

    assert finding.status_code == 409
    assert finding.json()["code"] == "run_not_succeeded"
    assert status.status_code == 200
    assert status.json()["record"]["status"] == "failed"
    assert status.json()["record"]["failure_phase"] == "detect"


def test_record_evidence_converts_to_and_from_typed_references():
    run = RunReference(batch_id="bat_1", run_id="run_1")
    cases = [
        ("activity_event", "evt_7", ActivityEventReference(run=run, event_id="evt_7")),
        ("usage_context", "3", UsageContextReference(run=run, context_number=3)),
    ]
    for record_type, record_id, reference in cases:
        evidence = RecordEvidence(
            evidence_id="e1", run=run, record_type=record_type, record_id=record_id
        )

        assert from_record_evidence(evidence) == reference
        assert to_record_evidence(reference, "e1") == evidence

    analysis_run = RecordEvidence(
        evidence_id="e2", run=run, record_type="analysis_run", record_id="run_1"
    )
    assert to_record_evidence(from_record_evidence(analysis_run), "e2") == analysis_run


def test_record_ids_of_kinds_record_evidence_does_not_list_yet_still_parse():
    run = RunReference(batch_id="bat_1", run_id="run_1")

    assert record_reference(run, "ai_evidence_sentence", "4:2") == AiEvidenceSentenceReference(
        run=run, candidate_number=4, sentence_number=2
    )
    assert record_reference(run, "category_neighbor", "4:1") == CategoryNeighborReference(
        run=run, candidate_number=4, neighbor_number=1
    )
    assert record_reference(run, "website_capture", "a.example") == WebsiteCaptureReference(
        run=run, domain="a.example"
    )
    with pytest.raises(ValidationError):
        to_record_evidence(WebsiteCaptureReference(run=run, domain="a.example"), "e1")


@pytest.mark.parametrize(
    ("record_type", "record_id"),
    [
        ("usage_context", "0"),
        ("usage_context", "x"),
        ("analysis_run", "run_other"),
        ("ai_evidence_sentence", "4"),
        ("activity_event", ""),
        ("spreadsheet_cell", "A1"),
    ],
)
def test_invalid_record_ids_are_rejected(record_type, record_id):
    run = RunReference(batch_id="bat_1", run_id="run_1")

    with pytest.raises(EvidenceError) as error:
        record_reference(run, record_type, record_id)

    assert (error.value.status_code, error.value.code) == (422, "invalid_reference")
