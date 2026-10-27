import pytest

from app.ai_determination.cascade import configuration_version, determine_ai
from app.ai_determination.jev import MODEL
from app.enrichment.fetch import Capture
from app.pipeline.identity import CandidateIdentity, ToolMetadataSnapshot

AI_PAGE_TEXT = (
    "Our AI writes summaries of every meeting you record. "
    "Plans start at ten dollars per seat and include unlimited projects. "
    "Teams in forty countries rely on us to keep their work organized every day."
)
PLAIN_PAGE_TEXT = (
    "Track projects, assign owners and share files with your whole team. "
    "Plans start at ten dollars per seat and include unlimited projects. "
    "Teams in forty countries rely on us to keep their work organized every day."
)


class FakeJev:
    """Decision requests get fixed probabilities; evidence sentences mentioning 'AI writes' score high."""

    def __init__(self, ai=0.9, non_ai=0.05, unresolved=0.05, strong=0.9, weak=0.1):
        self.probabilities = {"ai": ai, "non_ai": non_ai, "unresolved": unresolved}
        self.strong, self.weak = strong, weak
        self.bodies = []

    def __call__(self, body):
        self.bodies.append(body)
        questions = body["questions"]
        if "determination" in questions:
            answers = {
                "determination": {"probabilities": dict(self.probabilities)},
                "own_ai_task": {"noul": 0.7},
                "ai_only_subject": {"noul": 0.1},
                "vague_ai_claim": {"noul": 0.2},
                "describes_product": {"noul": 0.95},
            }
        else:
            answers = {
                key: {"noul": self.strong if "AI writes" in q["instructions"] else self.weak}
                for key, q in questions.items()
            }
        return {"model": "jev-1.14.0", "answers": answers}

    @property
    def decision_bodies(self):
        return [b for b in self.bodies if "determination" in b["questions"]]


def candidate(domain="tool.com", name="Tool", metadata_id=None):
    return CandidateIdentity(
        domain=domain,
        application_names=(name,),
        event_ids=("evt_1",),
        outcome="observed_tool",
        tool_id="observed:abc",
        basis="public_hostname",
        metadata_id=metadata_id,
    )


def page(main_text=AI_PAGE_TEXT, title="Tool", description="", headings=(), domain="tool.com"):
    return Capture(
        requested_url=f"https://{domain}/",
        captured_at="2026-10-26T12:00:00Z",
        outcome="extracted",
        final_url=f"https://{domain}/",
        title=title,
        metadata={"description": description} if description else {},
        headings=headings,
        main_text=main_text,
    )


def snapshot(*rows):
    return ToolMetadataSnapshot(
        [
            {"metadata_id": m, "application_name": n, "domain": d, "functionality_text": t}
            for m, n, d, t in rows
        ],
        "metadata.csv;rows=1",
    )


NO_METADATA = snapshot()


def test_homepage_with_ai_signal_goes_to_the_judge_and_keeps_its_evidence():
    jev = FakeJev()

    result = determine_ai(candidate(), {"tool.com": page()}, NO_METADATA, jev)

    assert result.determination == "ai"
    assert result.stage == "jev_judge"
    assert result.model == "jev-1.14.0"
    assert result.probabilities["ai"] == 0.9
    assert result.source.kind == "homepage"
    assert result.source.reference == "https://tool.com/"
    assert result.source.captured_at == "2026-10-26T12:00:00Z"
    assert result.evidence[0].sentence == "Our AI writes summaries of every meeting you record."
    assert result.evidence[0].probability == 0.9
    assert len(result.evidence) == 3
    assert [e.probability for e in result.evidence] == sorted(
        (e.probability for e in result.evidence), reverse=True
    )
    assert result.needs_review is False


def test_decision_request_pins_the_model_and_trims_page_text():
    jev = FakeJev()

    determine_ai(
        candidate(),
        {"tool.com": page(main_text="AI " + "x" * 20000, headings=("One", "Two"))},
        NO_METADATA,
        jev,
    )

    body = jev.decision_bodies[0]
    assert body["model"] == MODEL == "jev-1.14.0"
    assert body["state"]["headings"] == "One | Two"
    assert len(body["state"]["page_text"]) == 12000
    assert set(body["questions"]) == {
        "determination",
        "own_ai_task",
        "ai_only_subject",
        "vague_ai_claim",
        "describes_product",
    }


@pytest.mark.parametrize(
    ("ai", "non_ai", "unresolved", "expected"),
    [
        (0.40, 0.30, 0.30, "ai"),
        (0.39, 0.50, 0.11, "non_ai"),
        (0.39, 0.20, 0.41, "unresolved"),
    ],
)
def test_ai_needs_probability_at_least_0_4_otherwise_the_likelier_of_the_rest(
    ai, non_ai, unresolved, expected
):
    jev = FakeJev(ai=ai, non_ai=non_ai, unresolved=unresolved)

    result = determine_ai(candidate(), {"tool.com": page()}, NO_METADATA, jev)

    assert result.determination == expected


def test_ai_call_whose_best_evidence_is_weak_needs_review():
    jev = FakeJev(strong=0.59)

    result = determine_ai(candidate(), {"tool.com": page()}, NO_METADATA, jev)

    assert result.determination == "ai"
    assert result.needs_review is True


def test_weak_evidence_on_a_non_ai_call_needs_no_review():
    jev = FakeJev(ai=0.1, non_ai=0.8, unresolved=0.1, strong=0.2)

    result = determine_ai(candidate(), {"tool.com": page()}, NO_METADATA, jev)

    assert result.determination == "non_ai"
    assert result.needs_review is False


def test_homepage_without_ai_signal_is_non_ai_without_asking_the_judge():
    jev = FakeJev()

    result = determine_ai(
        candidate(), {"tool.com": page(main_text=PLAIN_PAGE_TEXT)}, NO_METADATA, jev
    )

    assert (result.determination, result.stage) == ("non_ai", "keyword_gate")
    assert result.evidence == ()
    assert jev.bodies == []


def test_thin_homepage_without_ai_signal_is_unresolved():
    jev = FakeJev()

    result = determine_ai(
        candidate(), {"tool.com": page(main_text="Sign in to continue.")}, NO_METADATA, jev
    )

    assert (result.determination, result.stage) == ("unresolved", "insufficient_text")
    assert jev.bodies == []


def test_ai_capability_described_without_ai_terms_still_reaches_the_judge():
    jev = FakeJev()

    determine_ai(
        candidate(),
        {"tool.com": page(main_text=PLAIN_PAGE_TEXT + " Turn plain English into SQL.")},
        NO_METADATA,
        jev,
    )

    assert len(jev.decision_bodies) == 1


def test_an_extracted_homepage_takes_precedence_over_a_supplied_description():
    jev = FakeJev()
    metadata = snapshot(("meta_04", "Mattermost", "mattermost.com", "Team chat with channels"))

    result = determine_ai(
        candidate("mattermost.com", "Mattermost", "meta_04"),
        {"mattermost.com": page(domain="mattermost.com")},
        metadata,
        jev,
    )

    assert result.source.kind == "homepage"
    assert result.determination == "ai"
    assert jev.decision_bodies[0]["state"]["page_text"] == AI_PAGE_TEXT


def test_supplied_description_stands_in_when_no_homepage_was_extracted():
    jev = FakeJev()
    metadata = snapshot(("meta_05", "MeetOscar", "meetoscar.com", "AI-assisted email outreach"))
    failed = Capture("https://meetoscar.com/", "2026-10-26T12:00:00Z", "fetch_failed", "Timeout")

    result = determine_ai(
        candidate("meetoscar.com", "MeetOscar", "meta_05"),
        {"meetoscar.com": failed},
        metadata,
        jev,
    )

    assert result.source.kind == "supplied_description"
    assert result.source.reference == "meta_05"
    assert result.source.version == "metadata.csv;rows=1"
    assert jev.decision_bodies[0]["state"] == {
        "title": "MeetOscar",
        "meta_description": "AI-assisted email outreach",
        "headings": "",
        "page_text": "",
    }


def test_preferring_supplied_descriptions_judges_one_even_when_a_homepage_was_extracted():
    jev = FakeJev()
    metadata = snapshot(("meta_05", "MeetOscar", "meetoscar.com", "AI-assisted email outreach"))

    result = determine_ai(
        candidate("meetoscar.com", "MeetOscar", "meta_05"),
        {"meetoscar.com": page(domain="meetoscar.com")},
        metadata,
        jev,
        prefer_supplied=True,
    )

    assert result.source.kind == "supplied_description"
    assert jev.decision_bodies[0]["state"]["meta_description"] == "AI-assisted email outreach"


def test_preferring_supplied_descriptions_still_uses_the_homepage_when_none_is_supplied():
    jev = FakeJev()

    result = determine_ai(
        candidate(), {"tool.com": page()}, NO_METADATA, jev, prefer_supplied=True
    )

    assert result.source.kind == "homepage"


def test_the_preference_is_part_of_the_configuration_version():
    assert configuration_version(prefer_supplied=True) != configuration_version()


def test_supplied_description_without_ai_signal_is_non_ai_however_short():
    jev = FakeJev()
    metadata = snapshot(("meta_04", "Mattermost", "mattermost.com", "Team chat with channels"))

    result = determine_ai(
        candidate("mattermost.com", "Mattermost", "meta_04"), {}, metadata, jev
    )

    assert (result.determination, result.stage) == ("non_ai", "keyword_gate")
    assert result.source.kind == "supplied_description"
    assert jev.bodies == []


def test_ai_in_the_application_name_alone_does_not_pass_the_gate():
    jev = FakeJev()
    metadata = snapshot(("meta_x", "Canvas AI", "canvas.com", PLAIN_PAGE_TEXT))

    result = determine_ai(
        candidate("canvas.com", "Canvas AI", "meta_x"), {}, metadata, jev
    )

    assert result.determination == "non_ai"
    assert jev.bodies == []


def test_empty_supplied_description_leaves_the_fetch_outcome_as_the_reason():
    jev = FakeJev()
    metadata = snapshot(("meta_06", "Tool", "tool.com", ""))
    missing = Capture("https://tool.com/", "2026-10-26T12:00:00Z", "not_usable_response", "http_404")

    result = determine_ai(candidate(metadata_id="meta_06"), {"tool.com": missing}, metadata, jev)

    assert (result.determination, result.reason) == ("unresolved", "not_usable_response")


def test_supplied_description_stands_in_for_known_tools_too():
    jev = FakeJev()
    metadata = snapshot(("meta_x", "Tool", "tool.com", PLAIN_PAGE_TEXT))
    known = CandidateIdentity(
        domain="tool.com",
        application_names=("Tool",),
        event_ids=("evt_1",),
        outcome="known_tool",
        tool_id="aitoolbuzz:1",
        basis="exact_root_domain",
    )

    result = determine_ai(known, {}, metadata, jev)

    assert result.source.kind == "supplied_description"
    assert result.determination == "non_ai"


def test_fixture_determinations_when_no_homepage_is_usable():
    import csv

    from app.config import Settings
    from app.pipeline.identity import load_registry, load_tool_metadata, resolve_identities
    from tests.test_identity_fixture import FIXTURE

    settings = Settings(data_dir=None)
    registry = load_registry(settings.catalog_path, settings.registry_exclusions_path)
    metadata = load_tool_metadata(settings.tool_metadata_path)
    events = list(csv.DictReader(FIXTURE.open(encoding="utf-8")))
    candidates = resolve_identities("batch-1", events, registry, metadata)
    unusable = {
        c.domain: Capture(f"https://{c.domain}/", "2026-10-26T12:00:00Z", "not_usable_response", "http_404")
        for c in candidates
    }

    results = {
        c.application_names[0]: determine_ai(c, unusable, metadata, FakeJev()).determination
        for c in candidates
    }

    assert results == {
        "ChatGPT": "unresolved",
        "Cursor": "unresolved",
        "Slack": "non_ai",
        "Mattermost": "non_ai",
        "MeetOscar": "ai",
        "Magic Inspector": "unresolved",
        "Amazon Comprehend": "ai",
        "Playbooks": "ai",
        "Open Canvas AI": "ai",
        "Workbench": "unresolved",
    }


def test_without_usable_evidence_the_determination_abstains_with_the_fetch_outcome():
    jev = FakeJev()
    blocked = Capture("https://workbench.example/", "2026-10-26T12:00:00Z", "blocked_destination")

    result = determine_ai(
        candidate("workbench.example", "Workbench"), {"workbench.example": blocked}, NO_METADATA, jev
    )

    assert (result.determination, result.stage) == ("unresolved", "no_evidence")
    assert result.reason == "blocked_destination"
    assert result.source is None
    assert jev.bodies == []
