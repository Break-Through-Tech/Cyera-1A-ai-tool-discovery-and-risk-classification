from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.assistant.contracts import EventTimeRange, PinnedScope, RunReference
from app.assistant.store import start_turn
from app.config import Settings
from app.main import create_app
from app.pipeline import Pipeline
from tests.test_batches import upload

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


@pytest.fixture
def stored(client):
    batch = upload(client).json()
    scope = PinnedScope(
        runs=(
            RunReference(
                batch_id=batch["batch_id"], run_id=batch["latest_run"]["run_id"]
            ),
        ),
        event_time=EventTimeRange(
            start="2026-01-01T00:00:00Z", end="2027-01-01T00:00:00Z"
        ),
    )
    engine = client.app.state.engine
    turn = start_turn(
        engine,
        question="What activity was observed?",
        scope=scope,
        model_id="gemini-test-only",
        prompt_version="test-v1",
    )
    return engine, turn
