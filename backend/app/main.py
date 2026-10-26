from fastapi import Depends, FastAPI

from app.api import batches, runs
from app.api.query import reject_unknown_query_parameters
from app.config import Settings
from app.db.engine import migrate, open_database
from app.errors import register_error_handlers
from app.pipeline import Pipeline
from app.pipeline.default import default_pipeline
from app.runs import fail_interrupted_runs
from app.versioning import current_code_commit


def create_app(
    settings: Settings | None = None, pipeline: Pipeline | None = None
) -> FastAPI:
    settings = settings or Settings.from_env()
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    engine = open_database(settings.database_path)
    migrate(engine)
    fail_interrupted_runs(engine)

    app = FastAPI(
        title="AI Tool Governance API",
        dependencies=[Depends(reject_unknown_query_parameters)],
    )
    app.state.settings = settings
    app.state.engine = engine
    app.state.pipeline = pipeline or default_pipeline(settings)
    app.state.code_commit = current_code_commit()
    register_error_handlers(app)
    app.include_router(batches.router)
    app.include_router(runs.router)

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    return app
