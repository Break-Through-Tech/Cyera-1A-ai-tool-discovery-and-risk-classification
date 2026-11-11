import os
from dataclasses import dataclass, field
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
REPO_DIR = BACKEND_DIR.parent


@dataclass(frozen=True)
class Settings:
    """Local state locations and the versioned inputs loaded at startup.

    Everything under ``data_dir`` is generated and resettable.
    """

    data_dir: Path
    catalog_path: Path = (
        REPO_DIR / "data/aitoolbuzz-com-16k-ai-tools-database/ai_tools_cleaned.csv"
    )
    registry_exclusions_path: Path = (
        BACKEND_DIR / "config/known_tool_registry_exclusions.json"
    )
    neighbor_index_path: Path = REPO_DIR / "artifacts/category_neighbor_index/v1"
    tool_metadata_path: Path = (
        REPO_DIR / "data/synthetic_enterprise_activity/v1/scenario_tool_metadata.csv"
    )
    typesafe_api_key: str | None = field(default=None, repr=False)
    gemini_api_key: str | None = field(default=None, repr=False)
    gemini_model: str | None = None
    gemini_timeout_seconds: float = 30
    gemini_max_output_tokens: int = 4096
    # False follows ADR 0002 (homepage text first); True judges supplied Dataset B text first.
    prefer_supplied_description: bool = False

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            data_dir=Path(os.environ.get("APP_DATA_DIR", BACKEND_DIR / "var")),
            typesafe_api_key=os.environ.get("TYPESAFE_API_KEY")
            or _dotenv_value(REPO_DIR / ".env", "TYPESAFE_API_KEY"),
            gemini_api_key=_gemini_setting("GEMINI_API_KEY"),
            gemini_model=(_gemini_setting("GEMINI_MODEL") or "").strip() or None,
            gemini_timeout_seconds=float(
                _gemini_setting("GEMINI_TIMEOUT_SECONDS") or "30"
            ),
            gemini_max_output_tokens=int(
                _gemini_setting("GEMINI_MAX_OUTPUT_TOKENS") or "4096"
            ),
            prefer_supplied_description=os.environ.get(
                "AI_PREFER_SUPPLIED_DESCRIPTION", ""
            )
            .strip()
            .lower()
            in ("1", "true", "yes"),
        )

    @property
    def database_path(self) -> Path:
        return self.data_dir / "app.sqlite3"

    @property
    def uploads_dir(self) -> Path:
        return self.data_dir / "uploads"

    @property
    def models_dir(self) -> Path:
        return self.data_dir / "models"


def display_path(path: Path) -> str:
    """A repository-relative path when possible, for readable version labels."""
    resolved = path.resolve()
    if resolved.is_relative_to(REPO_DIR):
        return resolved.relative_to(REPO_DIR).as_posix()
    return resolved.as_posix()


def _gemini_setting(name: str) -> str | None:
    # An explicitly empty environment value overrides .env, including disabling a model.
    return (
        os.environ[name]
        if name in os.environ
        else _dotenv_value(REPO_DIR / ".env", name)
    )


def _dotenv_value(path: Path, name: str) -> str | None:
    if not path.is_file():
        return None
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith(f"{name}="):
            return line.split("=", 1)[1].strip().strip("'\"") or None
    return None
