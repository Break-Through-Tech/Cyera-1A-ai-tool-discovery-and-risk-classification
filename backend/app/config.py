import os
from dataclasses import dataclass
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class Settings:
    """Local state locations. Everything under ``data_dir`` is generated and resettable."""

    data_dir: Path

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(data_dir=Path(os.environ.get("APP_DATA_DIR", BACKEND_DIR / "var")))

    @property
    def database_path(self) -> Path:
        return self.data_dir / "app.sqlite3"

    @property
    def uploads_dir(self) -> Path:
        return self.data_dir / "uploads"
