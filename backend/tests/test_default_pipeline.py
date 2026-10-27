from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.ai_determination.cascade import configuration_version
from app.ai_determination.jev import JudgeUnavailable
from app.category.classify import configuration_version as category_version
from app.category.neighbors import load_neighbor_index
from app.config import Settings
from app.main import create_app
from app.pipeline.default import default_pipeline
from tests.test_ai_determination import FakeJev
from tests.test_category_classification import FakeEmbed
from tests.test_enrichment_fetch import FakeHttp, html, not_found, public_dns
from tests.test_identity_fixture import FIXTURE


class EverythingNotFound(FakeHttp):
    def __init__(self):
        super().__init__({})

    def get(self, destination):
        self.requested.append((destination.url, destination.addresses))
        return not_found()


class ServesOnlyMeetOscar(EverythingNotFound):
    def get(self, destination):
        if destination.url == "https://meetoscar.com/":
            self.requested.append((destination.url, destination.addresses))
            return html()
        return super().get(destination)


def unavailable_jev(body):
    raise JudgeUnavailable("TYPESAFE_API_KEY is not set")


def catalog_vector_embed():
    """Embeds every text as the first catalog Tool's own vector, without loading the model."""
    vector = load_neighbor_index(Settings(data_dir=Path("unused")).neighbor_index_path).embeddings[0]
    return FakeEmbed(lambda text: vector)


def fixture_client(data_dir, http=None, jev=None, prefer_supplied_description=False, embed=None):
    settings = Settings(data_dir=data_dir, prefer_supplied_description=prefer_supplied_description)
    pipeline = default_pipeline(
        settings, http or EverythingNotFound(), public_dns(), jev or FakeJev(), embed or catalog_vector_embed()
    )
    return TestClient(create_app(settings, pipeline))


def upload_fixture(client):
    return client.post(
        "/batches", files={"file": ("activity.csv", FIXTURE.read_bytes(), "text/csv")}
    )


def test_default_pipeline_resolves_identities_fetches_homepages_and_pins_inputs(data_dir):
    http = EverythingNotFound()

    run = upload_fixture(fixture_client(data_dir, http=http)).json()["latest_run"]

    assert run["status"] == "succeeded"
    assert run["versions"]["known_tool_registry"].endswith(";listings=13701;excluded=2")
    assert run["versions"]["tool_metadata_snapshot"].endswith("scenario_tool_metadata.csv;rows=9")
    assert run["versions"]["website_enrichment"].startswith("homepage-v1")
    assert run["versions"]["ai_determination"].startswith("jev-cascade-v1;model=jev-1.14.0;")
    homepages = sorted(url for url, _ in http.requested if not url.endswith("/robots.txt"))
    assert homepages == [
        "https://aws.amazon.com/",
        "https://chatgpt.com/",
        "https://cursor.so/",
        "https://insidesales.com/",
        "https://magicinspector.com/",
        "https://mattermost.com/",
        "https://meetoscar.com/",
        "https://slack.com/",
    ]


def test_unseen_ai_tools_are_categorized_from_the_text_ai_determination_judged(data_dir):
    embed = catalog_vector_embed()
    client = fixture_client(data_dir, http=ServesOnlyMeetOscar(), embed=embed)

    run = upload_fixture(client).json()["latest_run"]

    assert run["status"] == "succeeded"
    assert run["versions"]["category_classification"] == (
        "neighbor-vote-v1;index=artifacts/category_neighbor_index/v1;tools=8214;"
        "model=BAAI/bge-small-en-v1.5@5c38ec7;fastembed=0.9.1;onnxruntime=1.31.1;"
        "k=15;cutoff=0.469;source=homepage_first"
    )
    assert any("AI that summarizes meeting notes." in text for text in embed.texts)


def test_reanalysis_replays_stored_jev_answers(data_dir):
    jev = FakeJev()
    client = fixture_client(data_dir, jev=jev)
    batch_id = upload_fixture(client).json()["batch_id"]
    asked_first_run = len(jev.bodies)

    rerun = client.post(f"/batches/{batch_id}/runs").json()

    assert rerun["status"] == "succeeded"
    assert asked_first_run == 8
    assert len(jev.bodies) == asked_first_run


@pytest.mark.parametrize(
    ("prefer_supplied", "expected_meetoscar_text"),
    [
        (False, "AI that summarizes meeting notes."),
        (True, "AI-assisted email outreach and campaign automation for marketing teams"),
    ],
)
def test_the_preference_decides_what_jev_and_the_category_vote_read_and_is_recorded(
    data_dir, prefer_supplied, expected_meetoscar_text
):
    jev = FakeJev()
    embed = catalog_vector_embed()
    client = fixture_client(
        data_dir,
        http=ServesOnlyMeetOscar(),
        jev=jev,
        prefer_supplied_description=prefer_supplied,
        embed=embed,
    )

    run = upload_fixture(client).json()["latest_run"]

    assert run["versions"]["ai_determination"] == configuration_version(prefer_supplied)
    assert run["versions"]["category_classification"] == category_version(
        load_neighbor_index(Settings(data_dir=data_dir).neighbor_index_path), prefer_supplied
    )
    read = {body["state"]["meta_description"] for body in jev.decision_bodies}
    assert expected_meetoscar_text in read
    assert any(expected_meetoscar_text in text for text in embed.texts)


def test_settings_read_the_preference_from_the_environment(monkeypatch):
    monkeypatch.setenv("AI_PREFER_SUPPLIED_DESCRIPTION", "true")
    assert Settings.from_env().prefer_supplied_description is True

    monkeypatch.setenv("AI_PREFER_SUPPLIED_DESCRIPTION", "0")
    assert Settings.from_env().prefer_supplied_description is False


def test_run_fails_in_ai_determination_when_jev_is_unavailable(data_dir):
    run = upload_fixture(fixture_client(data_dir, jev=unavailable_jev)).json()["latest_run"]

    assert run["status"] == "failed"
    assert run["failure"] == {
        "summary": "Analysis failed during the ai_determination phase.",
        "phase": "ai_determination",
    }


def test_run_fails_in_category_classification_when_the_embedding_model_is_unavailable(data_dir):
    def unavailable_embed(texts):
        raise OSError("model download failed")

    client = fixture_client(data_dir, http=ServesOnlyMeetOscar(), embed=unavailable_embed)

    run = upload_fixture(client).json()["latest_run"]

    assert run["status"] == "failed"
    assert run["failure"] == {
        "summary": "Analysis failed during the category_classification phase.",
        "phase": "category_classification",
    }
