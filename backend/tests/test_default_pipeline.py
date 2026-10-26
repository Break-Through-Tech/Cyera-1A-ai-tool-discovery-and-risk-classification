from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.pipeline.default import default_pipeline
from tests.test_enrichment_fetch import FakeHttp, not_found, public_dns
from tests.test_identity_fixture import FIXTURE


class EverythingNotFound(FakeHttp):
    def __init__(self):
        super().__init__({})

    def get(self, destination):
        self.requested.append((destination.url, destination.addresses))
        return not_found()


def test_default_pipeline_resolves_identities_fetches_homepages_and_pins_inputs(data_dir):
    settings = Settings(data_dir=data_dir)
    http = EverythingNotFound()
    client = TestClient(create_app(settings, default_pipeline(settings, http, public_dns())))

    response = client.post(
        "/batches", files={"file": ("activity.csv", FIXTURE.read_bytes(), "text/csv")}
    )

    run = response.json()["latest_run"]
    assert run["status"] == "succeeded"
    assert run["versions"]["known_tool_registry"].startswith("sha256:")
    assert run["versions"]["tool_metadata_snapshot"].endswith(
        "@sha256:10eb699f7c1d4350d777dcb1b4e23c879f22d45ef70f193c03b3c32c9d713423"
    )
    assert run["versions"]["website_enrichment"].startswith("homepage-v1")
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
