"""End-to-end check on the synthetic dataset, through the public HTTP API only (#81).

Uploads ``data/synthetic_enterprise_activity/v1/activity.csv`` with ``POST /batches``,
which analyzes it synchronously, then reads the saved results back through ``GET /runs``,
``/overview``, ``/applications``, ``/contexts``, ``/events`` and ``POST /evidence/resolve``
and checks them against ``evaluation_only/expected_scenarios.csv`` and against each other.

Offline mode (default, deterministic, no network or key) runs the real ``default_pipeline``:

- Real: upload validation and ingestion, SQLite persistence, Identity Resolution against
  the real AIToolBuzz registry with its held-out exclusions and the real scenario Tool
  metadata, homepage fetch orchestration (robots, destination checks) and HTML extraction,
  the AI Determination cascade including its keyword gate and supplied-description
  fallback, catalog Category lookup for known Tools, the Semantic Neighbor vote over the
  real neighbor index, Usage Context grouping, the synthetic risk rules, every read
  endpoint and Evidence resolution.
- Faked: the HTTP transport and DNS (``ChatGPT``, ``Cursor`` and ``Magic Inspector`` get
  short hand-written homepages, not captures; every other URL is a 404, so the other Tools
  are judged on their supplied descriptions), the Jev judge (``FakeJev``: every text that
  passes the gate is judged AI with probability 0.9) and the embedding model (every text
  embeds as ChatGPT's catalog vector). Because of the fake embedder, the Category of a
  neighbor-voted Tool is only checked to have been voted on, not compared with the key;
  live mode compares it. AI Determination agreement for text that reaches the judge is
  partly by construction of ``FakeJev``.

Live mode runs the same checks against real services; it is skipped unless ``E2E_LIVE=1``:

    E2E_LIVE=1 TYPESAFE_API_KEY=... .venv/bin/python -m pytest -s tests/test_end_to_end.py -k live

It analyzes in-process with ``Settings.from_env()`` and a fresh data directory, or, with
``E2E_BASE_URL=http://127.0.0.1:8000``, against a running server. It prints the Run's
wall-clock time and every disagreement with the answer key, and fails if there is one.
"""

import csv
import io
import os
import time
from dataclasses import dataclass, field, replace
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import REPO_DIR, Settings
from app.main import create_app
from app.scope import CATEGORIES, RISK_TIERS
from tests.test_default_pipeline import EverythingNotFound, fixture_client
from tests.test_enrichment_fetch import html
from tests.test_identity_fixture import FIXTURE

EXPECTED = FIXTURE.parent / "evaluation_only/expected_scenarios.csv"
PAGE_SIZE = 200

# Hand-written stand-ins for the three Tools without a supplied functionality description.
HOMEPAGES = {
    "https://chatgpt.com/": (
        b"<html><head><title>ChatGPT</title><meta name='description' content='ChatGPT is an"
        b" AI assistant that answers questions, writes and summarizes text, and helps with"
        b" code.'></head><body><main><h1>ChatGPT</h1><p>Ask anything and get answers from a"
        b" conversational AI model.</p></main></body></html>"
    ),
    "https://cursor.so/": (
        b"<html><head><title>Cursor - The AI Code Editor</title></head><body><main>"
        b"<h1>The AI Code Editor</h1><p>Cursor is an AI code editor that predicts your next"
        b" edit and lets you write code with natural language instructions.</p></main>"
        b"</body></html>"
    ),
    "https://magicinspector.com/": (
        b"<html><head><title>Magic Inspector</title></head><body><main><h1>AI-powered test"
        b" automation</h1><p>Magic Inspector uses AI to create and maintain end-to-end and"
        b" visual regression tests for web applications without code.</p></main></body></html>"
    ),
}


class ServesThreeHomepages(EverythingNotFound):
    def get(self, destination):
        if destination.url in HOMEPAGES:
            self.requested.append((destination.url, destination.addresses))
            return html(HOMEPAGES[destination.url])
        return super().get(destination)


def load_scenarios() -> list[dict]:
    with EXPECTED.open(newline="", encoding="utf-8") as file:
        return [
            {**row, "event_ids": row["event_ids"].split("|")} for row in csv.DictReader(file)
        ]


def activity_event_ids() -> list[str]:
    return [row["event_id"] for row in csv.DictReader(io.StringIO(FIXTURE.read_text("utf-8")))]


SCENARIOS = load_scenarios()


# --- Reading the API ----------------------------------------------------------------------


def ok(response) -> dict:
    assert response.status_code in (200, 201), (response.status_code, response.text)
    return response.json()


def read_all(client, path: str, **params) -> tuple[list[dict], int]:
    """Every item of a paged listing, and the total the listing reported."""
    items, total, offset = [], None, 0
    while total is None or offset < total:
        page = ok(client.get(path, params={**params, "limit": PAGE_SIZE, "offset": offset}))
        items += page["items"]
        total = page["total"]
        offset += PAGE_SIZE
    return items, total


@dataclass
class Analysis:
    """One analyzed upload and what the listings returned for its Run."""

    client: object
    batch: dict
    run: dict
    seconds: float
    events: dict[str, dict] = field(default_factory=dict)
    events_total: int = 0
    applications: dict[tuple[str, str], dict] = field(default_factory=dict)
    applications_total: int = 0
    details: dict[tuple[str, str], dict] = field(default_factory=dict)
    contexts: dict[int, dict] = field(default_factory=dict)
    contexts_total: int = 0

    @property
    def run_ref(self) -> dict:
        return {"batch_id": self.run["batch_id"], "run_id": self.run["run_id"]}

    @property
    def scope(self) -> dict:
        return {"run_ids": [self.run["run_id"]]}


def upload_and_analyze(client, content: bytes) -> Analysis:
    """Upload the dataset (re-analyzing if this server already holds it) and read results."""
    started = time.perf_counter()
    response = client.post("/batches", files={"file": ("activity.csv", content, "text/csv")})
    batch = ok(response)
    run = batch["latest_run"]
    if response.status_code == 200:  # Already uploaded: the Batch is reused, so run again.
        run = ok(client.post(f"/batches/{batch['batch_id']}/runs"))
    seconds = time.perf_counter() - started
    assert run["status"] == "succeeded", run
    assert ok(client.get(f"/runs/{run['run_id']}")) == run

    analysis = Analysis(client, batch, run, seconds)
    events, analysis.events_total = read_all(client, "/events", **analysis.scope)
    analysis.events = {e["event_id"]: e for e in events}
    apps, analysis.applications_total = read_all(client, "/applications", **analysis.scope)
    analysis.applications = {(a["subject_kind"], a["subject_id"]): a for a in apps}
    for key in analysis.applications:
        kind, subject_id = key
        analysis.details[key] = ok(
            client.get(f"/runs/{run['run_id']}/applications/{kind}/{subject_id}")
        )
    contexts, analysis.contexts_total = read_all(client, "/contexts", **analysis.scope)
    analysis.contexts = {c["context_number"]: c for c in contexts}
    return analysis


# --- Checks, shared by both modes; each returns its disagreements ------------------------


def id_difference(actual, expected) -> dict[str, list[str]]:
    """Event IDs only one side has; empty when they are the same set."""
    actual, expected = set(actual), set(expected)
    return {
        side: sorted(ids)
        for side, ids in (("unexpected", actual - expected), ("missing", expected - actual))
        if ids
    }


def scenario_mismatches(
    analysis: Analysis, scenario: dict, compare_voted_category: bool = True
) -> list[str]:
    """How the saved results differ from one answer-key scenario (README column meanings)."""
    problems: list[str] = []

    def expect(what, actual, expected):
        if actual != expected:
            problems.append(f"{what}: expected {expected!r}, got {actual!r}")

    events = [analysis.events.get(event_id) for event_id in scenario["event_ids"]]
    if None in events:
        return [f"events missing from GET /events: {len([e for e in events if e is None])}"]
    subjects = {(e["subject_kind"], e["subject_id"]) for e in events}
    expect("applications holding the scenario's events", len(subjects), 1)
    if len(subjects) != 1:
        return problems
    (subject,) = subjects
    app = analysis.applications[subject]
    detail = analysis.details[subject]

    # Identity
    expect("identity outcome", app["identity_outcome"], scenario["expected_identity_outcome"])
    expected_identity = scenario["expected_tool_identity"]
    if scenario["expected_identity_outcome"] == "known_tool":
        expect("tool identity", app["subject_id"], expected_identity)
    elif scenario["cohort"] == "catalog_held_out_ai":
        # A held-out catalog Tool must be reported as previously unseen, not looked up.
        held_out = expected_identity.removeprefix("aitoolbuzz:")
        if app["subject_id"] == expected_identity or held_out in str(detail["identity"]):
            problems.append(f"held-out catalog Tool {expected_identity} was matched")
    elif scenario["expected_identity_outcome"] == "unresolved_candidate":
        expect("subject kind", app["subject_kind"], "candidate")

    # AI Determination
    expect("AI determination", app["ai_determination"], scenario["expected_ai_status"])

    # Category Classification
    expected_category = scenario["expected_category"]
    methods = {c["category_classification"]["method"] for c in detail["candidates"]}
    if expected_category == "inapplicable":
        expect("category outcome", app["category_outcome"], "inapplicable")
    elif "semantic_neighbor_vote" in methods and not compare_voted_category:
        voted = [c["category_classification"] for c in detail["candidates"]]
        if not all(v["neighbors"] and v["outcome"] in ("assigned", "unresolved") for v in voted):
            problems.append(f"category was not voted on by Semantic Neighbors: {voted}")
    elif expected_category == "unresolved":
        expect("category outcome", app["category_outcome"], "unresolved")
    else:
        assert expected_category in CATEGORIES, expected_category
        expect("category", (app["category_outcome"], app["category"]), ("assigned", expected_category))

    # Contextual risk: one Usage Context holding exactly the scenario's events, or none.
    numbers = {e["context_number"] for e in events}
    risk = scenario["expected_risk_behavior"]
    if risk in RISK_TIERS:
        expect("Usage Contexts holding the scenario's events", len(numbers), 1)
        (number,) = numbers if len(numbers) == 1 else (None,)
        context = analysis.contexts.get(number)
        if context is None:
            problems.append(f"no Usage Context for the scenario (context numbers {numbers})")
            return problems
        in_context = {e for e, row in analysis.events.items() if row["context_number"] == number}
        expect("Usage Context events", id_difference(in_context, scenario["event_ids"]), {})
        expect("risk tier", context["tier"], risk)
        expect(
            "investigation flag",
            context["investigation_flag"],
            scenario["expected_investigation_flag"] == "true",
        )
    else:
        assert risk in ("not_applicable", "not_assessed_ai_unresolved"), risk
        expect("Usage Contexts holding the scenario's events", numbers, {None})
        expect("risk outcome", app["risk_outcome"], "inapplicable")
        expect("investigation flag", scenario["expected_investigation_flag"], "not_applicable")
    return problems


def consistency_mismatches(analysis: Analysis, event_ids: list[str]) -> list[str]:
    """Totals and records that different endpoints report for the same Run must agree."""
    client, run_id = analysis.client, analysis.run["run_id"]
    problems: list[str] = []

    def expect(what, actual, expected):
        if actual != expected:
            problems.append(f"{what}: expected {expected!r}, got {actual!r}")

    events = analysis.events.values()
    contexts = analysis.contexts.values()
    apps = analysis.applications.values()
    by_ai = {d: sum(e["ai_determination"] == d for e in events) for d in ("ai", "non_ai", "unresolved")}

    expect("batch event_count", analysis.batch["event_count"], len(event_ids))
    expect("events total", analysis.events_total, len(event_ids))
    expect("event IDs", id_difference(analysis.events, event_ids), {})
    expect("applications total", analysis.applications_total, len(analysis.applications))
    expect("contexts total", analysis.contexts_total, len(analysis.contexts))
    expect("application events", sum(a["event_count"] for a in apps), len(event_ids))
    expect("application contexts", sum(a["context_count"] for a in apps), len(analysis.contexts))

    overview = ok(client.get("/overview", params=analysis.scope))
    headline, activity = overview["headline"], overview["activity"]
    expect("overview events", activity["events"], len(event_ids))
    expect("overview events by AI determination", activity["by_ai_determination"], by_ai)
    expect("overview AI-positive events", headline["ai_positive_events"], by_ai["ai"])
    expect("overview AI-unresolved events", headline["ai_unresolved_events"], by_ai["unresolved"])
    expect(
        "overview AI-positive events by identity",
        sum(activity["ai_positive_by_identity"].values()),
        by_ai["ai"],
    )
    expect(
        "overview known AI Tools",
        headline["known_ai_tools"],
        sum(a["identity_outcome"] == "known_tool" and a["ai_determination"] == "ai" for a in apps),
    )
    expect(
        "overview unresolved identity",
        overview["unresolved_stages"]["identity"],
        {
            "events": sum(e["identity_outcome"] == "unresolved_candidate" for e in events),
            "candidates": sum(a["identity_outcome"] == "unresolved_candidate" for a in apps),
        },
    )
    expect(
        "overview category rows",
        sum(c["ai_positive_events"] for c in overview["categories"]),
        by_ai["ai"],
    )
    expect("overview department events", sum(d["events"] for d in overview["departments"]), len(event_ids))
    expect(
        "overview risk distribution",
        {t: n for t, n in overview["risk_distribution"].items() if n},
        {t: n for t in RISK_TIERS if (n := sum(c["tier"] == t for c in contexts))},
    )
    expect(
        "overview policy statuses",
        sum(overview["policy_status_distribution"].values()),
        len(analysis.contexts),
    )
    flagged = sum(c["investigation_flag"] for c in contexts)
    expect("overview flagged contexts", headline["flagged_contexts"], flagged)
    expect(
        "GET /contexts?flagged=true total",
        ok(client.get("/contexts", params={**analysis.scope, "flagged": True}))["total"],
        flagged,
    )
    expect(
        "GET /events?ai_determinations=ai total",
        ok(client.get("/events", params={**analysis.scope, "ai_determinations": "ai"}))["total"],
        by_ai["ai"],
    )

    for key, app in analysis.applications.items():
        detail = analysis.details[key]
        summary = {k: v for k, v in app.items() if k in detail["summary"]}
        expect(f"{key} detail summary", detail["summary"], summary)
        expect(f"{key} detail contexts", detail["usage_contexts"]["count"], app["context_count"])
        expect(
            f"{key} detail candidate events",
            sum(c["event_count"] for c in detail["candidates"]),
            app["event_count"],
        )
    for number, context in analysis.contexts.items():
        detail = ok(client.get(f"/runs/{run_id}/contexts/{number}"))
        expect(f"context {number} tier", detail["assessment"]["tier"], context["tier"])
        expect(
            f"context {number} flag", detail["investigation"]["flagged"], context["investigation_flag"]
        )
        expect(
            f"context {number} events",
            sum(e["context_number"] == number for e in events),
            context["event_count"],
        )
        expect(
            f"context {number} GET /events total",
            ok(client.get("/events", params={**analysis.scope, "context_number": number}))["total"],
            context["event_count"],
        )
    return problems


def evidence_mismatches(analysis: Analysis) -> list[str]:
    """Evidence cited by application details and contexts resolves to the same records."""
    client, run = analysis.client, analysis.run_ref
    problems: list[str] = []

    def resolve(reference):
        response = client.post("/evidence/resolve", json={"reference": {**reference, "run": run}})
        if response.status_code != 200:
            problems.append(f"{reference} did not resolve: {response.status_code} {response.text}")
            return None
        return response.json()

    sentences = 0
    for detail in analysis.details.values():
        for candidate in detail["candidates"]:
            ai = candidate["ai_determination"]
            if ai["evidence"]:
                resolved = resolve(
                    {
                        "kind": "ai_evidence_sentence",
                        "candidate_number": candidate["candidate_number"],
                        "sentence_number": 1,
                    }
                )
                sentences += 1
                if resolved and resolved["record"]["sentence"] != ai["evidence"][0]["sentence"]:
                    problems.append(f"candidate {candidate['candidate_number']} sentence differs")
            if candidate["metadata_id"]:
                resolved = resolve({"kind": "tool_metadata", "metadata_id": candidate["metadata_id"]})
                if resolved and resolved["role"] != "synthetic_policy":
                    problems.append(f"{candidate['metadata_id']} role is {resolved['role']}")
    if not sentences:
        problems.append("no application detail cited an AI evidence sentence")
    for number, context in analysis.contexts.items():
        resolved = resolve({"kind": "usage_context", "context_number": number})
        if resolved and resolved["record"]["tier"] != context["tier"]:
            problems.append(f"context {number} resolved tier {resolved['record']['tier']}")
    event_id = min(analysis.events)
    resolved = resolve({"kind": "activity_event", "event_id": event_id})
    if resolved and resolved["role"] != "observed_activity":
        problems.append(f"{event_id} role is {resolved['role']}")
    return problems


# --- Offline mode -------------------------------------------------------------------------


@pytest.fixture(scope="module")
def analysis(tmp_path_factory) -> Analysis:
    client = fixture_client(tmp_path_factory.mktemp("data"), http=ServesThreeHomepages())
    return upload_and_analyze(client, FIXTURE.read_bytes())


def test_the_upload_is_analyzed_by_the_default_pipeline_in_one_request(analysis):
    print(f"\noffline Run {analysis.run['run_id']}: {analysis.seconds:.2f}s wall-clock")
    assert analysis.run["status"] == "succeeded"
    assert analysis.run["versions"]["known_tool_registry"].endswith(";excluded=2")
    assert set(analysis.run["versions"]) >= {
        "ai_determination",
        "category_classification",
        "risk_assessment",
    }


@pytest.mark.parametrize("scenario", SCENARIOS, ids=[s["scenario_id"] for s in SCENARIOS])
def test_each_answer_key_scenario_is_found_as_expected(analysis, scenario):
    assert scenario_mismatches(analysis, scenario, compare_voted_category=False) == []


def test_every_count_agrees_across_endpoints_and_with_the_upload(analysis):
    assert consistency_mismatches(analysis, activity_event_ids()) == []


def test_cited_evidence_resolves(analysis):
    assert evidence_mismatches(analysis) == []


# --- Live mode ----------------------------------------------------------------------------


@pytest.mark.skipif(
    os.environ.get("E2E_LIVE") != "1",
    reason="live end-to-end check: set E2E_LIVE=1 (and TYPESAFE_API_KEY, or E2E_BASE_URL)",
)
def test_live_end_to_end(tmp_path):
    base_url = os.environ.get("E2E_BASE_URL")
    if base_url:
        import httpx

        client = httpx.Client(base_url=base_url, timeout=None)
    else:
        settings = Settings.from_env()
        if not settings.typesafe_api_key:
            pytest.skip("TYPESAFE_API_KEY is not set")
        # A fresh database, so the Run is not a replay; the embedding model cache is shared.
        shared_models = settings.models_dir
        shared_models.mkdir(parents=True, exist_ok=True)
        settings = replace(settings, data_dir=tmp_path / "data")
        settings.data_dir.mkdir(parents=True)
        settings.models_dir.symlink_to(shared_models, target_is_directory=True)
        client = TestClient(create_app(settings))

    live = upload_and_analyze(client, FIXTURE.read_bytes())
    problems = {
        s["scenario_id"]: found for s in SCENARIOS if (found := scenario_mismatches(live, s))
    }
    problems |= {
        name: found
        for name, found in (
            ("consistency", consistency_mismatches(live, activity_event_ids())),
            ("evidence", evidence_mismatches(live)),
        )
        if found
    }
    print(
        f"\nlive Run {live.run['run_id']} ({base_url or 'in-process'}): "
        f"{live.seconds:.1f}s wall-clock, started {live.run['started_at']}, "
        f"completed {live.run['completed_at']}"
    )
    for name, found in problems.items():
        print(f"{name}:\n  " + "\n  ".join(found))
    assert problems == {}
