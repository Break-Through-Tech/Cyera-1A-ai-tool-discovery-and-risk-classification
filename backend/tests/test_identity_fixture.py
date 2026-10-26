from app.config import REPO_DIR, Settings
from app.ingestion.activity import parse_activity
from app.pipeline.identity import load_registry, load_tool_metadata, resolve_identities

FIXTURE = REPO_DIR / "data/synthetic_enterprise_activity/v1/activity.csv"


def test_synthetic_fixture_resolves_identities_as_its_scenarios_describe(tmp_path):
    settings = Settings(data_dir=tmp_path)
    registry = load_registry(settings.catalog_path, settings.registry_exclusions_path)
    metadata = load_tool_metadata(settings.tool_metadata_path)

    candidates = resolve_identities(
        "bat_fixture", parse_activity(FIXTURE.read_bytes()), registry, metadata
    )

    outcomes = {
        c.application_names[0]: (c.outcome, c.tool_id if c.outcome == "known_tool" else c.basis or c.reason)
        for c in candidates
    }
    assert outcomes == {
        "ChatGPT": (
            "known_tool",
            "aitoolbuzz:2c1fde4c873a82ca00d999e553012213c67abe8463e0f2947bb10598c555a3cd",
        ),
        "Cursor": (
            "known_tool",
            "aitoolbuzz:598c6b12630af5f5f3987ddd91ca8c207b19f8f6be4fd10af4489bc8c79b149c",
        ),
        "Slack": ("observed_tool", "tool_metadata_match"),
        "Mattermost": ("observed_tool", "tool_metadata_match"),
        "MeetOscar": ("observed_tool", "tool_metadata_match"),
        "Magic Inspector": ("observed_tool", "tool_metadata_match"),
        "Amazon Comprehend": ("observed_tool", "tool_metadata_match"),
        "Playbooks": ("observed_tool", "tool_metadata_match"),
        "Open Canvas AI": ("observed_tool", "tool_metadata_match"),
        "Workbench": ("unresolved_candidate", "insufficient_identity_evidence"),
    }
    assert sum(len(c.event_ids) for c in candidates) == 265


def test_registry_and_metadata_versions_are_content_hashes(tmp_path):
    settings = Settings(data_dir=tmp_path)

    registry = load_registry(settings.catalog_path, settings.registry_exclusions_path)
    metadata = load_tool_metadata(settings.tool_metadata_path)

    assert registry.version.startswith("sha256:") and len(registry.version) == 71
    assert metadata.version == (
        "data/synthetic_enterprise_activity/v1/scenario_tool_metadata.csv"
        "@sha256:10eb699f7c1d4350d777dcb1b4e23c879f22d45ef70f193c03b3c32c9d713423"
    )
