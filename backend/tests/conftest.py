from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.pipeline import Pipeline

TEST_VERSIONS = {"ai_detector": "test-detector-1", "risk_rules": "test-rules-1"}


@pytest.fixture
def data_dir(tmp_path: Path) -> Path:
    return tmp_path / "data"


@pytest.fixture
def make_client(data_dir: Path):
    def make(*phases) -> TestClient:
        pipeline = Pipeline(phases=tuple(phases), versions=TEST_VERSIONS)
        return TestClient(create_app(Settings(data_dir=data_dir), pipeline))

    return make


@pytest.fixture
def client(make_client) -> TestClient:
    return make_client()
