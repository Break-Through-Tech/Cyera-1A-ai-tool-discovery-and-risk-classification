from sqlalchemy import select

from app.config import Settings
from app.db.tables import activity_events
from app.pipeline import Phase, Pipeline, RunContext
from app.pipeline.identity import load_registry, load_tool_metadata, resolve_identities


def default_pipeline(settings: Settings) -> Pipeline:
    """The application's analysis pipeline, with its versioned inputs loaded once at startup."""
    registry = load_registry(settings.catalog_path, settings.registry_exclusions_path)
    metadata = load_tool_metadata(settings.tool_metadata_path)

    def resolve_identity(context: RunContext) -> None:
        with context.engine.connect() as connection:
            events = connection.execute(
                select(
                    activity_events.c.event_id,
                    activity_events.c.application_name,
                    activity_events.c.domain,
                )
                .where(activity_events.c.batch_id == context.batch_id)
                .order_by(activity_events.c.occurred_at, activity_events.c.event_id)
            ).mappings().all()
        context.results["identities"] = resolve_identities(
            context.batch_id, events, registry, metadata
        )

    return Pipeline(
        phases=(Phase("resolve_identity", resolve_identity),),
        versions={
            "known_tool_registry": registry.version,
            "tool_metadata_snapshot": metadata.version,
        },
    )
