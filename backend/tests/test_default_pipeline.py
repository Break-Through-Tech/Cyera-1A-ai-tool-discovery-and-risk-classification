from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from tests.test_identity_fixture import FIXTURE


def test_default_pipeline_runs_identity_resolution_and_pins_its_inputs(data_dir):
    client = TestClient(create_app(Settings(data_dir=data_dir)))

    response = client.post(
        "/batches", files={"file": ("activity.csv", FIXTURE.read_bytes(), "text/csv")}
    )

    run = response.json()["latest_run"]
    assert run["status"] == "succeeded"
    assert run["versions"]["known_tool_registry"].startswith("sha256:")
    assert run["versions"]["tool_metadata_snapshot"].endswith(
        "@sha256:10eb699f7c1d4350d777dcb1b4e23c879f22d45ef70f193c03b3c32c9d713423"
    )
