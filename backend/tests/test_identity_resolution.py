import pytest

from app.pipeline.identity import (
    CatalogListing,
    KnownToolRegistry,
    ToolMetadataSnapshot,
    resolve_identities,
)

CHATGPT = CatalogListing("c0ffee", "ChatGPT", "https://chatgpt.com", "Communication And Support")
SLACK_GPT_FEATURE_PAGE = CatalogListing(
    "51ac6",
    "Slack GPT",
    "https://slack.com/intl/en-in/blog/news/introducing-slack-gpt",
    "Communication And Support",
)
NO_KNOWN_TOOLS = KnownToolRegistry.from_listings([], excluded_tool_ids=set())
NO_METADATA = ToolMetadataSnapshot(rows=[])


def event(event_id: str, application_name: str, domain: str) -> dict:
    return {"event_id": event_id, "application_name": application_name, "domain": domain}


def resolve(events, registry=NO_KNOWN_TOOLS, metadata=NO_METADATA, batch_id="bat_1"):
    return resolve_identities(batch_id, events, registry, metadata)


def test_candidates_group_events_by_normalized_domain_and_application_name():
    candidates = resolve(
        [
            event("e1", "Amazon Comprehend", "aws.amazon.com"),
            event("e2", "amazon  comprehend", "WWW.AWS.Amazon.com."),
            event("e3", "Amazon S3", "aws.amazon.com"),
            event("e4", "Amazon Comprehend", "comprehend.example"),
        ]
    )

    assert [(c.domain, c.event_ids) for c in candidates] == [
        ("aws.amazon.com", ("e1", "e2")),
        ("aws.amazon.com", ("e3",)),
        ("comprehend.example", ("e4",)),
    ]
    assert candidates[0].application_names == ("Amazon Comprehend", "amazon  comprehend")


def registry(*listings: CatalogListing, excluded: set[str] = frozenset()):
    return KnownToolRegistry.from_listings(listings, excluded_tool_ids=set(excluded))


def test_domain_of_a_single_site_root_listing_resolves_to_that_known_tool():
    [candidate] = resolve(
        [event("e1", "OpenAI chat", "www.chatgpt.com")], registry(CHATGPT)
    )

    assert candidate.outcome == "known_tool"
    assert candidate.tool_id == "aitoolbuzz:c0ffee"
    assert candidate.basis == "exact_root_domain"
    assert candidate.reason is None


def test_two_site_root_listings_on_one_domain_leave_the_candidate_unresolved():
    [candidate] = resolve(
        [event("e1", "HubSpot", "hubspot.com")],
        registry(
            CatalogListing("h1", "HubSpot AI", "https://www.hubspot.com/", "Marketing And Sales"),
            CatalogListing("h2", "HubSpot Breeze", "https://hubspot.com", "Marketing And Sales"),
        ),
    )

    assert candidate.outcome == "unresolved_candidate"
    assert candidate.tool_id is None
    assert candidate.reason == "ambiguous_known_match"
    assert candidate.catalog_tool_ids == ("h1", "h2")


def test_held_out_catalog_tool_is_not_a_known_match():
    meetoscar = CatalogListing("m05c4", "MeetOscar", "https://www.meetoscar.com/", "Communication And Support")

    [candidate] = resolve(
        [event("e1", "MeetOscar", "meetoscar.com")],
        registry(meetoscar, excluded={"m05c4"}),
    )

    assert candidate.outcome == "observed_tool"


@pytest.mark.parametrize(
    "domain",
    [
        "workbench.example",
        "app.example.com",
        "intranet.test",
        "printer.local",
        "localhost",
        "10.0.0.5",
        "not a domain",
    ],
)
def test_non_public_domain_without_metadata_stays_unresolved(domain):
    [candidate] = resolve([event("e1", "Workbench", domain)])

    assert candidate.outcome == "unresolved_candidate"
    assert candidate.tool_id is None
    assert candidate.reason == "insufficient_identity_evidence"


def test_exact_tool_metadata_match_gives_non_public_domain_an_observed_identity():
    metadata = ToolMetadataSnapshot(
        rows=[
            {
                "metadata_id": "meta_09",
                "application_name": "Open Canvas AI",
                "domain": "open-canvas-ai.example",
            }
        ]
    )

    [other_name, matched] = resolve(
        [
            event("e1", "open canvas ai", "open-canvas-ai.example"),
            event("e2", "Canvas Helper", "open-canvas-ai.example"),
        ],
        metadata=metadata,
    )

    assert matched.outcome == "observed_tool"
    assert matched.basis == "tool_metadata_match"
    assert matched.metadata_id == "meta_09"
    assert other_name.outcome == "unresolved_candidate"


def test_observed_identity_is_stable_within_a_batch_but_never_shared_across_batches():
    events = [event("e1", "Mattermost", "mattermost.com"), event("e2", "Matter", "mattermost.com")]

    first_run = resolve(events, batch_id="bat_1")
    second_run = resolve(events, batch_id="bat_1")
    other_batch = resolve(events, batch_id="bat_2")

    assert [c.tool_id for c in first_run] == [c.tool_id for c in second_run]
    assert first_run[0].tool_id != first_run[1].tool_id
    assert {c.tool_id for c in first_run}.isdisjoint(c.tool_id for c in other_batch)


def test_listing_for_a_deeper_page_does_not_claim_its_whole_domain():
    [candidate] = resolve(
        [event("e1", "Slack", "slack.com")], registry(SLACK_GPT_FEATURE_PAGE)
    )

    assert candidate.outcome == "observed_tool"
    assert candidate.basis == "public_hostname"
