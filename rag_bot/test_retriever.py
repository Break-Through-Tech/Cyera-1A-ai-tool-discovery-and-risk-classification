"""Tests for the approved corpus and local search."""

import re
import unittest

from rag_bot.corpus import Passage, load_passages, split_sections
from rag_bot.retrieval import search


class CorpusTests(unittest.TestCase):
    def test_loads_only_approved_sources_and_sections(self):
        passages = load_passages()
        self.assertEqual(
            {passage.source_path for passage in passages},
            {
                "CONTEXT.md",
                "PROJECT_PLAN.md",
                "docs/adr/0001-ai-tool-requires-own-ai-functionality.md",
            },
        )
        self.assertEqual(len(passages), 7)
        self.assertFalse(any("Evaluation policy" in passage.heading for passage in passages))
        self.assertEqual(passages, load_passages())
        self.assertEqual(len({passage.passage_id for passage in passages}), len(passages))
        for passage in passages:
            self.assertEqual(passage.source_role, "project_policy")
            self.assertTrue(passage.heading and passage.text)
            self.assertTrue(re.fullmatch(r"[a-f0-9]{64}", passage.content_version))

    def test_splits_headings_and_preserves_fenced_text(self):
        markdown = "# First\nBody\n~~~md\n## Example\n~~~\n## Second ##\nMore"
        self.assertEqual(
            split_sections(markdown),
            [("First", "Body\n~~~md\n## Example\n~~~"), ("Second", "More")],
        )


class RetrievalTests(unittest.TestCase):
    def test_ranks_rarer_words_and_limits_results_to_five(self):
        passages = [
            Passage(str(i), "example.md", "Heading", "project_policy", "version", "risk")
            for i in range(6)
        ]
        precise = Passage("6", "example.md", "Admin", "project_policy", "version", "risk")
        matches = search("ADMIN risk?", passages + [precise])
        self.assertEqual(len(matches), 5)
        self.assertEqual(matches[0].passage, precise)
        self.assertGreater(matches[0].score, matches[1].score)
        self.assertEqual([result.passage.passage_id for result in matches[1:]], list("0123"))

    def test_finds_contextual_risk_contract(self):
        matches = search("How do contextual risk tiers use admin controls?", load_passages())
        self.assertEqual(matches[0].passage.source_path, "PROJECT_PLAN.md")
        self.assertEqual(matches[0].passage.heading, "Initial contextual-risk contract — Confirmed")

    def test_returns_no_matches_for_empty_or_unrelated_input(self):
        passages = load_passages()
        for question in ("", "What is it?", "photosynthesis chlorophyll"):
            with self.subTest(question=question):
                self.assertEqual(search(question, passages), [])
