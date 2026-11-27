"""Offline tests of the standalone integration boundary."""

import subprocess
import sys
from dataclasses import replace
from unittest import TestCase
from unittest.mock import patch

from rag_bot.evidence import document_id
from rag_bot.profiles import load_snapshot
from rag_bot.service import RetrievalRequest, RetrievalService
from rag_bot.test_semantic import WordTokenizer


class LocalModel:
    tokenizer = WordTokenizer()
    max_seq_length = 256

    def get_embedding_dimension(self):
        return 2

    def encode(self, texts, **kwargs):
        return [[0, 1] if text == "Unrelated?" else [1, 0] for text in texts]


class ServiceTests(TestCase):
    def setUp(self):
        with patch("rag_bot.service.load_model", return_value=LocalModel()) as load:
            self.service = RetrievalService(cache_dir=None)
        load.assert_called_once()

    def test_request_validation_and_token_limit(self):
        for request in (
            None, RetrievalRequest("  "), RetrievalRequest("q" * 2001), RetrievalRequest(1),
            RetrievalRequest("q", limit=True), RetrievalRequest("q", limit=5.0),
            RetrievalRequest("q", limit=0), RetrievalRequest("q", limit=11),
            RetrievalRequest("q", preset="catalog_dev"), RetrievalRequest("q", preset=[]),
        ):
            with self.subTest(request=request):
                self.assertEqual(self.service.retrieve(request).status, "invalid_input")
        with patch.object(self.service._index, "search") as search:
            result = self.service.retrieve(RetrievalRequest("word " * 256))
            self.assertEqual(result.status, "unsupported_input")
            search.assert_not_called()

    def test_reuses_resources_and_applies_requested_limits_for_all_presets(self):
        with patch("rag_bot.service.load_model") as load:
            for preset in ("semantic-stable", "hybrid-baseline", "hybrid-calibrated"):
                result = self.service.retrieve(RetrievalRequest(" Tool Candidate ", 1, preset))
                self.assertEqual(result.status, "data")
                self.assertEqual(len(result.matches), 1)
                self.assertEqual(result.matches[0].ranking.rank, 1)
                self.assertEqual(result.matches[0].ranking.rrf_score is None,
                                 preset == "semantic-stable")
            self.assertEqual(len(self.service.retrieve(RetrievalRequest("Tool Candidate")).matches), 5)
            self.assertEqual(len(self.service.retrieve(RetrievalRequest(
                "Tool Candidate", 10, "hybrid-calibrated")).matches), 10)
            load.assert_not_called()

    def test_no_matches_unavailability_and_failure_are_distinct_and_safe(self):
        self.assertEqual(self.service.retrieve(RetrievalRequest("Unrelated?")).status, "no_matches")
        with patch.object(self.service._index, "search", side_effect=RuntimeError("/private/token")):
            result = self.service.retrieve(RetrievalRequest("Question"))
        self.assertEqual(result.status, "execution_failure")
        self.assertNotIn("/private/token", result.message)
        self.assertFalse(result.matches)
        with patch("rag_bot.service.load_model", side_effect=OSError("/private/key")):
            unavailable = RetrievalService(cache_dir=None)
        self.assertEqual(unavailable.retrieve(RetrievalRequest("Question")).status, "unavailable")
        self.assertNotIn("/private/key", unavailable.retrieve(RetrievalRequest("Question")).message)
        self.assertEqual(unavailable.resolve("passage").status, "unavailable")

    def test_evidence_identity_and_round_trip(self):
        result = self.service.retrieve(RetrievalRequest("Tool Candidate", 1))
        hit = result.matches[0].evidence
        source = next(chunk for chunk in self.service._index.chunks if chunk.chunk_id == hit.chunk_id)
        snapshot = load_snapshot()
        self.assertEqual(hit.document_id, document_id(source.passage.source_path))
        self.assertEqual(hit.document_version, dict(snapshot.source_fingerprints)[hit.source_path])
        self.assertEqual(hit.corpus_version, snapshot.corpus_version)
        self.assertEqual(hit.section_passage_id, source.passage.passage_id)
        self.assertEqual(hit.source_role, "project_policy")
        self.assertEqual(hit.heading, source.passage.heading)
        self.assertEqual(hit.excerpt, source.text.strip())
        self.assertEqual(self.service.resolve(hit.reference).evidence, hit)
        with patch("rag_bot.service.load_model", return_value=LocalModel()):
            another = RetrievalService(cache_dir=None)
        self.assertEqual(another.resolve(hit.reference).evidence, hit)

    def test_rejects_malformed_unknown_and_version_mismatched_references(self):
        hit = self.service.retrieve(RetrievalRequest("Tool Candidate", 1)).matches[0].evidence
        self.assertEqual(self.service.resolve("step_1:" + hit.reference).status, "malformed_reference")
        self.assertEqual(self.service.resolve(None).status, "malformed_reference")
        for altered, status in (
            (replace(hit, document_id=document_id("other.md")), "not_found"),
            (replace(hit, chunk_id="0" * 20), "not_found"),
            (replace(hit, corpus_version="0" * 64), "version_mismatch"),
            (replace(hit, document_version="0" * 64), "version_mismatch"),
        ):
            resolution = self.service.resolve(altered.reference)
            self.assertEqual(resolution.status, status)
            self.assertIsNone(resolution.evidence)
        other = next(chunk.passage.source_path for chunk in self.service._index.chunks
                     if chunk.passage.source_path != hit.source_path)
        mismatched_parent = replace(hit, document_id=document_id(other),
                                    document_version=dict(load_snapshot().source_fingerprints)[other])
        self.assertEqual(self.service.resolve(mismatched_parent.reference).status, "not_found")

    def test_catalog_snapshots_and_tool_evidence_fail_before_model_initialization(self):
        snapshot = load_snapshot()
        for blocked in (
            replace(snapshot, profile="catalog_dev"), replace(snapshot, profile="catalog_unseen_eval"),
            replace(snapshot, passages=(replace(snapshot.passages[0], source_role="tool_evidence"),)),
        ):
            with patch("rag_bot.service.load_snapshot", return_value=blocked) as load, \
                    patch("rag_bot.service.load_model") as model:
                service = RetrievalService(cache_dir=None)
            load.assert_called_once_with("docs_only")
            model.assert_not_called()
            self.assertEqual(service.retrieve(RetrievalRequest("Question")).status, "unavailable")

    def test_service_import_does_not_need_ui_or_generation_packages(self):
        subprocess.run([sys.executable, "-B", "-c", """
import sys
for package in ('streamlit', 'google.genai', 'rag_bot.generator', 'rag_bot.rag'):
    sys.modules[package] = None
from rag_bot.service import RetrievalService
"""], check=True)
