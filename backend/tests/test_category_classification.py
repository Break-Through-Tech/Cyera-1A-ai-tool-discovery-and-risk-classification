from dataclasses import replace

import numpy as np
import pytest

from app.ai_determination.cascade import AiDetermination, EvidenceSource, EvidenceText
from app.category.classify import classify_category
from app.category.neighbors import CatalogTool, NeighborIndex
from app.pipeline.identity import CatalogListing, KnownToolRegistry
from tests.test_ai_determination import candidate

INDEX = NeighborIndex(
    np.array([[1.0, 0.0], [0.8, 0.6], [0.6, 0.8], [0.0, 1.0]], dtype=np.float32),
    (
        CatalogTool("t_a", "Otter", "Communication And Support"),
        CatalogTool("t_b", "MeetGeek", "Communication And Support"),
        CatalogTool("t_c", "Tableau AI", "Data And Analytics"),
        CatalogTool("t_d", "Looker", "Data And Analytics"),
    ),
    "test-index",
    {"repo": "test/model", "revision": "abc1234", "dim": 2},
)
REGISTRY = KnownToolRegistry.from_listings(
    [CatalogListing("k1", "Known", "https://known.com/", "Security And Privacy")], set(), "catalog;listings=1"
)
HOMEPAGE = EvidenceSource("homepage", "https://tool.com/", "2026-10-26T12:00:00Z")


class FakeEmbed:
    """Embeds each text as ``vector_for(text)`` and remembers what it was asked to embed."""

    def __init__(self, vector_for=lambda text: [1.0, 0.0] if "meeting" in text else [0.7071, 0.7071]):
        self.vector_for = vector_for
        self.texts = []

    def __call__(self, texts):
        self.texts.extend(texts)
        return np.array([self.vector_for(text) for text in texts], dtype=np.float32)


def ai(determination="ai", full_text="Notetaker AI writes summaries of every meeting you record."):
    text = EvidenceText("Notetaker", "", "", full_text, full_text, supplied=False)
    return AiDetermination(determination, "jev_judge", HOMEPAGE, text=text)


@pytest.mark.parametrize("determination", ["non_ai", "unresolved"])
def test_a_tool_that_is_not_an_ai_tool_has_no_applicable_category(determination):
    embed = FakeEmbed()

    result = classify_category(candidate(), ai(determination), REGISTRY, INDEX, embed)

    assert result.outcome == "inapplicable"
    assert result.category is None
    assert result.reason == f"ai_determination_{determination}"
    assert embed.texts == []


def test_a_known_ai_tool_takes_its_catalog_category_with_the_listing_as_provenance():
    embed = FakeEmbed()
    known = replace(
        candidate(domain="known.com"), outcome="known_tool", tool_id="aitoolbuzz:k1", catalog_tool_ids=("k1",)
    )

    result = classify_category(known, ai(), REGISTRY, INDEX, embed)

    assert (result.outcome, result.method, result.category) == (
        "assigned",
        "catalog",
        "Security And Privacy",
    )
    assert result.source == EvidenceSource("catalog", "k1", version="catalog;listings=1")
    assert embed.texts == []


def test_an_unseen_ai_tool_takes_the_category_its_nearest_catalog_tools_vote_for():
    embed = FakeEmbed()
    judged = ai()

    result = classify_category(candidate(), judged, REGISTRY, INDEX, embed)

    assert (result.outcome, result.method, result.category) == (
        "assigned",
        "semantic_neighbor_vote",
        "Communication And Support",
    )
    # Similarities 1.0 + 0.8 for meeting Tools against 0.6 + 0.0 for data Tools.
    assert result.share == pytest.approx(1.8 / 2.4)
    assert [n.name for n in result.neighbors] == ["Otter", "MeetGeek", "Tableau AI", "Looker"]
    assert result.source == HOMEPAGE
    assert embed.texts == [judged.text.full_text]


def test_a_split_vote_leaves_the_category_unresolved_but_keeps_the_neighbors():
    three_way = NeighborIndex(
        np.array([[1.0, 0.0]] * 3, dtype=np.float32),
        (
            CatalogTool("x", "X", "Business And Finance"),
            CatalogTool("y", "Y", "Marketing And Sales"),
            CatalogTool("z", "Z", "Operations And Management"),
        ),
        "three-way-index",
        INDEX.model,
    )

    result = classify_category(candidate(), ai(), REGISTRY, three_way, FakeEmbed())

    assert (result.outcome, result.category, result.reason) == (
        "unresolved",
        None,
        "neighbor_vote_below_cutoff",
    )
    assert result.share == pytest.approx(1 / 3)
    assert [n.name for n in result.neighbors] == ["X", "Y", "Z"]


def test_an_ai_tool_without_judged_text_has_an_unresolved_category():
    embed = FakeEmbed()
    without_text = AiDetermination("ai", "jev_judge", HOMEPAGE)

    result = classify_category(candidate(), without_text, REGISTRY, INDEX, embed)

    assert (result.outcome, result.reason) == ("unresolved", "no_evidence_text")
    assert embed.texts == []
