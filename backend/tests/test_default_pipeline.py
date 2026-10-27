from pathlib import Path

import numpy as np
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


class FakeEmbed:
    """Embeds every text as the first catalog Tool's own vector, without loading the model."""

    def __init__(self):
        self.vector = load_neighbor_index(Settings(data_dir=Path("unused")).neighbor_index_path).embeddings[0]
        self.texts = []

    def __call__(self, texts):
        self.texts.extend(texts)
        return np.tile(self.vector, (len(texts), 1))


def fixture_client(data_dir, http=None, jev=None, prefer_supplied_description=False, embed=None):
    settings = Settings(data_dir=data_dir, prefer_supplied_description=prefer_supplied_description)
    pipeline = default_pipeline(
        settings, http or EverythingNotFound(), public_dns(), jev or FakeJev(), embed or FakeEmbed()
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
    assert run["versions"]["known_tool_registry"].startswith("sha256:")
    assert run["versions"]["tool_metadata_snapshot"].endswith(
        "@sha256:10eb699f7c1d4350d777dcb1b4e23c879f22d45ef70f193c03b3c32c9d713423"
    )
    assert run["versions"]["website_enrichment"].startswith("homepage-v1")
    assert run["versions"]["ai_determination"].startswith("jev-cascade:sha256:")
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
    embed = FakeEmbed()
    client = fixture_client(data_dir, http=ServesOnlyMeetOscar(), embed=embed)

    run = upload_fixture(client).json()["latest_run"]

    assert run["status"] == "succeeded"
    assert run["versions"]["category_classification"].startswith("neighbor-vote:sha256:")
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
def test_the_preference_decides_what_jev_reads_and_is_recorded(
    data_dir, prefer_supplied, expected_meetoscar_text
):
    jev = FakeJev()
    client = fixture_client(
        data_dir,
        http=ServesOnlyMeetOscar(),
        jev=jev,
        prefer_supplied_description=prefer_supplied,
    )

    run = upload_fixture(client).json()["latest_run"]

    assert run["versions"]["ai_determination"] == configuration_version(prefer_supplied)
    assert run["versions"]["category_classification"] == category_version(
        load_neighbor_index(Settings(data_dir=data_dir).neighbor_index_path), prefer_supplied
    )
    read = {body["state"]["meta_description"] for body in jev.decision_bodies}
    assert expected_meetoscar_text in read


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
