from fastapi import FastAPI

from app.api import batches
from app.config import Settings
from app.db.engine import migrate, open_database
from app.errors import register_error_handlers


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    engine = open_database(settings.database_path)
    migrate(engine)

    app = FastAPI(title="AI Tool Governance API")
    app.state.settings = settings
    app.state.engine = engine
    register_error_handlers(app)
    app.include_router(batches.router)

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    return app
