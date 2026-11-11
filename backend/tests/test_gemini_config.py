import asyncio

import pytest
from app.assistant.model import GeminiConfig, GeminiModel
from app.config import Settings
from app.main import create_app
from app.pipeline import Pipeline
from fastapi.testclient import TestClient
from pydantic import SecretStr, ValidationError


def test_no_implicit_model_and_no_key_in_settings_representation(tmp_path):
    settings = Settings(data_dir=tmp_path, gemini_api_key="do-not-print-this-key")
    assert GeminiModel.from_settings(settings) is None
    assert "do-not-print" not in repr(settings)
    config = GeminiConfig(
        api_key=SecretStr("do-not-print-this-key"), model_id="gemini-fixture"
    )
    assert "do-not-print" not in repr(config) + config.model_dump_json()


def test_explicit_model_requires_our_explicit_api_key_not_ambient_google_auth(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("GOOGLE_API_KEY", "ambient-key-must-not-be-used")
    settings = Settings(data_dir=tmp_path, gemini_model="gemini-fixture")
    with pytest.raises(ValueError, match="GEMINI_API_KEY"):
        GeminiModel.from_settings(settings)


@pytest.mark.parametrize(
    "changes",
    [
        {"model_id": ""},
        {"model_id": "https://untrusted.example/model"},
        {"api_key": SecretStr(" ")},
        {"max_output_tokens": 0},
        {"max_output_tokens": True},
        {"timeout_seconds": float("inf")},
        {"timeout_seconds": 0},
    ],
)
def test_invalid_configuration_is_rejected_before_any_request(changes):
    with pytest.raises(ValidationError):
        GeminiConfig(
            **{
                "api_key": SecretStr("fixture-key"),
                "model_id": "gemini-fixture",
                **changes,
            }
        )


def test_environment_overrides_dotenv_and_empty_model_explicitly_disables(
    tmp_path, monkeypatch
):
    monkeypatch.setattr("app.config.REPO_DIR", tmp_path)
    (tmp_path / ".env").write_text(
        "GEMINI_API_KEY=dotenv-key\nGEMINI_MODEL=gemini-dotenv\n"
        "GEMINI_TIMEOUT_SECONDS=15\nGEMINI_MAX_OUTPUT_TOKENS=2048\n"
    )
    for name in (
        "GEMINI_API_KEY",
        "GEMINI_MODEL",
        "GEMINI_TIMEOUT_SECONDS",
        "GEMINI_MAX_OUTPUT_TOKENS",
    ):
        monkeypatch.delenv(name, raising=False)
    settings = Settings.from_env()
    assert settings.gemini_model == "gemini-dotenv"
    assert settings.gemini_api_key == "dotenv-key"
    assert settings.gemini_timeout_seconds == 15
    assert settings.gemini_max_output_tokens == 2048
    monkeypatch.setenv("GEMINI_MODEL", "gemini-environment")
    monkeypatch.setenv("GEMINI_API_KEY", "environment-key")
    assert Settings.from_env().gemini_model == "gemini-environment"
    assert Settings.from_env().gemini_api_key == "environment-key"
    monkeypatch.setenv("GEMINI_MODEL", "")
    assert Settings.from_env().gemini_model is None


def test_app_lifespan_creates_and_closes_the_configured_sdk_client(
    tmp_path, monkeypatch
):
    closed = []
    original_close = GeminiModel.aclose

    async def tracked_close(self):
        await original_close(self)
        closed.append(self.model_id)

    monkeypatch.setattr(GeminiModel, "aclose", tracked_close)
    app = create_app(
        Settings(
            data_dir=tmp_path,
            gemini_api_key="fixture-key",
            gemini_model="gemini-fixture",
        ),
        Pipeline(phases=()),
    )
    assert app.state.assistant_model is None
    with TestClient(app) as client:
        assert isinstance(app.state.assistant_model, GeminiModel)
        assert app.state.assistant_model.model_id == "gemini-fixture"
        assert client.get("/health").json() == {"status": "ok"}
    assert closed == ["gemini-fixture"]
    assert app.state.assistant_model is None


def test_default_sdk_client_has_one_attempt_and_fixed_developer_api_routing(
    monkeypatch,
):
    from google import genai

    created = []
    original_client = genai.Client

    def capture(**kwargs):
        created.append(kwargs)
        return original_client(**kwargs)

    monkeypatch.setattr(genai, "Client", capture)
    monkeypatch.setenv("GOOGLE_GENAI_USE_VERTEXAI", "true")
    monkeypatch.setenv("GOOGLE_GEMINI_BASE_URL", "https://untrusted.example")
    model = GeminiModel(
        GeminiConfig(api_key=SecretStr("fixture-key"), model_id="gemini-fixture")
    )
    asyncio.run(model.aclose())
    options = created[0]["http_options"]
    assert created[0]["vertexai"] is False and created[0]["enterprise"] is False
    assert options.base_url == "https://generativelanguage.googleapis.com"
    assert options.retry_options.attempts == 1
    assert options.timeout == model.request_metadata.timeout_ms == 30000


def test_unconfigured_app_has_no_model_and_configured_missing_key_fails_closed(
    tmp_path,
):
    app = create_app(Settings(data_dir=tmp_path / "disabled"), Pipeline(phases=()))
    with TestClient(app):
        assert app.state.assistant_model is None
    app = create_app(
        Settings(data_dir=tmp_path / "invalid", gemini_model="gemini-fixture"),
        Pipeline(phases=()),
    )
    with pytest.raises(ValueError, match="GEMINI_API_KEY"), TestClient(app):
        pass
