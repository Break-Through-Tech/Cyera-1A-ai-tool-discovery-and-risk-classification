from concurrent.futures import ThreadPoolExecutor
from importlib.metadata import version

from sqlalchemy import select

from app.ai_determination.cascade import configuration_version, determine_ai
from app.ai_determination.jev import CachedJudge, JevClient, Judge
from app.config import Settings
from app.db.tables import activity_events
from app.enrichment.destinations import Resolver, system_resolver
from app.enrichment.fetch import HttpClient, fetch_homepages
from app.enrichment.http import CurlHttpClient
from app.pipeline import Phase, Pipeline, RunContext
from app.pipeline.identity import load_registry, load_tool_metadata, resolve_identities

WEBSITE_ENRICHMENT_VERSION = (
    f"homepage-v1;curl_cffi={version('curl_cffi')};"
    f"beautifulsoup4={version('beautifulsoup4')};trafilatura={version('trafilatura')}"
)
JUDGE_WORKERS = 4


def default_pipeline(
    settings: Settings,
    http: HttpClient | None = None,
    resolve: Resolver | None = None,
    jev: Judge | None = None,
) -> Pipeline:
    """The application's analysis pipeline, with its versioned inputs loaded once at startup."""
    registry = load_registry(settings.catalog_path, settings.registry_exclusions_path)
    metadata = load_tool_metadata(settings.tool_metadata_path)
    http = http or CurlHttpClient()
    resolve = resolve or system_resolver
    jev = jev or JevClient(settings.typesafe_api_key)
    prefer_supplied = settings.prefer_supplied_description

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

    def fetch_websites(context: RunContext) -> None:
        domains = {candidate.domain for candidate in context.results["identities"]}
        context.results["captures_by_domain"] = fetch_homepages(domains, http, resolve)

    def ai_determination(context: RunContext) -> None:
        judge = CachedJudge(context.engine, jev)
        captures = context.results["captures_by_domain"]
        with ThreadPoolExecutor(max_workers=JUDGE_WORKERS) as pool:
            context.results["ai_determinations"] = list(
                pool.map(
                    lambda candidate: determine_ai(
                        candidate, captures, metadata, judge, prefer_supplied
                    ),
                    context.results["identities"],
                )
            )

    return Pipeline(
        phases=(
            Phase("resolve_identity", resolve_identity),
            Phase("fetch_websites", fetch_websites),
            Phase("ai_determination", ai_determination),
        ),
        versions={
            "known_tool_registry": registry.version,
            "tool_metadata_snapshot": metadata.version,
            "website_enrichment": WEBSITE_ENRICHMENT_VERSION,
            "ai_determination": configuration_version(prefer_supplied),
        },
    )
