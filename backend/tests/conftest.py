from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


@pytest.fixture
def data_dir(tmp_path: Path) -> Path:
    return tmp_path / "data"


@pytest.fixture
def make_client(data_dir: Path):
    def make() -> TestClient:
        return TestClient(create_app(Settings(data_dir=data_dir)))

    return make


@pytest.fixture
def client(make_client) -> TestClient:
    return make_client()
