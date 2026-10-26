import os
from dataclasses import dataclass
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
    tool_metadata_path: Path = (
        REPO_DIR / "data/synthetic_enterprise_activity/v1/scenario_tool_metadata.csv"
    )

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(data_dir=Path(os.environ.get("APP_DATA_DIR", BACKEND_DIR / "var")))

    @property
    def database_path(self) -> Path:
        return self.data_dir / "app.sqlite3"

    @property
    def uploads_dir(self) -> Path:
        return self.data_dir / "uploads"
