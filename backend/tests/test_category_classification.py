from dataclasses import replace

import numpy as np
import pytest

from app.ai_determination.cascade import AiDetermination
from app.category.classify import classify_category
from app.category.neighbors import CatalogTool, NeighborIndex
from tests.test_ai_determination import NO_METADATA, candidate, page, snapshot

INDEX = NeighborIndex(
    np.array([[1.0, 0.0], [0.8, 0.6], [0.6, 0.8], [0.0, 1.0]], dtype=np.float32),
    (
        CatalogTool("t_a", "Otter", "Communication And Support"),
        CatalogTool("t_b", "MeetGeek", "Communication And Support"),
        CatalogTool("t_c", "Tableau AI", "Data And Analytics"),
        CatalogTool("t_d", "Looker", "Data And Analytics"),
    ),
    "sha256:test-index",
)


class FakeEmbed:
    """Meeting text points at the meeting Tools; anything else sits exactly between both groups."""

    def __init__(self):
        self.texts = []

    def __call__(self, texts):
        self.texts.extend(texts)
        return np.array(
            [[1.0, 0.0] if "meeting" in t else [0.7071, 0.7071] for t in texts], dtype=np.float32
        )


def ai(determination="ai"):
    return AiDetermination(determination, "jev_judge")


@pytest.mark.parametrize("determination", ["non_ai", "unresolved"])
def test_a_tool_that_is_not_an_ai_tool_has_no_applicable_category(determination):
    embed = FakeEmbed()

    result = classify_category(
        candidate(), ai(determination), {"tool.com": page()}, NO_METADATA, {}, INDEX, embed
    )

    assert result.outcome == "inapplicable"
    assert result.category is None
    assert result.reason == f"ai_determination_{determination}"
    assert embed.texts == []


def test_a_known_ai_tool_takes_its_catalog_category_without_a_vote():
    embed = FakeEmbed()
    known = replace(
        candidate(), outcome="known_tool", tool_id="aitoolbuzz:k1", catalog_tool_ids=("k1",)
    )

    result = classify_category(
        known, ai(), {"tool.com": page()}, NO_METADATA, {"k1": "Security And Privacy"}, INDEX, embed
    )

    assert (result.outcome, result.method, result.category) == (
        "assigned",
        "catalog",
        "Security And Privacy",
    )
    assert embed.texts == []


def test_an_unseen_ai_tool_takes_the_category_its_nearest_catalog_tools_vote_for():
    embed = FakeEmbed()

    result = classify_category(
        candidate(), ai(), {"tool.com": page(title="Notetaker")}, NO_METADATA, {}, INDEX, embed
    )

    assert (result.outcome, result.method, result.category) == (
        "assigned",
        "semantic_neighbor_vote",
        "Communication And Support",
    )
    # Similarities 1.0 + 0.8 for meeting Tools against 0.6 + 0.0 for data Tools.
    assert result.share == pytest.approx(1.8 / 2.4)
    assert [n.name for n in result.neighbors] == ["Otter", "MeetGeek", "Tableau AI", "Looker"]
    assert result.source.kind == "homepage"
    assert len(embed.texts) == 1
    assert embed.texts[0].startswith("Notetaker")
    assert "summaries of every meeting" in embed.texts[0]


def test_a_split_vote_leaves_the_category_unresolved_but_keeps_the_neighbors():
    three_way = NeighborIndex(
        np.array([[1.0, 0.0]] * 3, dtype=np.float32),
        (
            CatalogTool("x", "X", "Business And Finance"),
            CatalogTool("y", "Y", "Marketing And Sales"),
            CatalogTool("z", "Z", "Operations And Management"),
        ),
    )

    result = classify_category(
        candidate(), ai(), {"tool.com": page()}, NO_METADATA, {}, three_way, FakeEmbed()
    )

    assert (result.outcome, result.category, result.reason) == (
        "unresolved",
        None,
        "neighbor_vote_below_cutoff",
    )
    assert result.share == pytest.approx(1 / 3)
    assert [n.name for n in result.neighbors] == ["X", "Y", "Z"]


def test_an_ai_tool_without_readable_text_has_an_unresolved_category():
    embed = FakeEmbed()

    result = classify_category(candidate(), ai(), {}, NO_METADATA, {}, INDEX, embed)

    assert (result.outcome, result.reason) == ("unresolved", "not_fetched")
    assert embed.texts == []


@pytest.mark.parametrize(
    ("prefer_supplied", "expected_kind", "expected_text"),
    [
        (False, "homepage", "summaries of every meeting"),
        (True, "supplied_description", "Dashboards for revenue data"),
    ],
)
def test_the_vote_reads_the_same_text_ai_determination_judged(
    prefer_supplied, expected_kind, expected_text
):
    embed = FakeEmbed()
    metadata = snapshot(("m1", "Tool", "tool.com", "Dashboards for revenue data"))

    result = classify_category(
        candidate(metadata_id="m1"), ai(), {"tool.com": page()}, metadata, {}, INDEX, embed,
        prefer_supplied,
    )

    assert result.source.kind == expected_kind
    assert expected_text in embed.texts[0]
