"""Offline regression tests for chunk retrieval, rank fusion, and RAG integration."""

import io
import sys
from contextlib import redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import Mock, patch

from rag_bot import chat, profiles, semantic
from rag_bot.catalog import load_catalog
from rag_bot.chunking import Chunk
from rag_bot.generator import GeneratedAnswer, GenerationError, GeminiGenerator, GeminiSettings
from rag_bot.hybrid import HybridConfig, HybridRetriever, fuse
from rag_bot.rag import RagChat
from rag_bot.retrieval import ChunkKeywordIndex, ChunkKeywordResult, search
from rag_bot.semantic import SemanticResult
from rag_bot.test_catalog import csv_bytes, row
from rag_bot.test_semantic import fake_model, passage


def excerpt(identity, body, source=None):
    source = source or passage(identity, body, heading="Example")
    return Chunk(source, 0, len(body), identity)


class HybridTests(TestCase):
    def test_chunk_keywords_use_precomputed_statistics_and_baseline_uses_passages(self):
        broad = excerpt("chunk-a", "usage context")
        rare = excerpt("chunk-b", "usage context audit")
        index = ChunkKeywordIndex([broad, rare])
        self.assertEqual(index.search("audit usage", limit=1)[0].chunk, rare)
        self.assertEqual(search("audit usage", [broad.passage, rare.passage])[0].passage, rare.passage)
        self.assertEqual(index.search(""), [])

    def test_reciprocal_ranks_use_first_occurrence_and_keep_raw_scores(self):
        a, b, c = [excerpt(key, key) for key in ("a", "b", "c")]
        lexical = [ChunkKeywordResult(b, 900), ChunkKeywordResult(b, 800),
                   ChunkKeywordResult(a, 500)]
        vector = [SemanticResult(a, 0.9), SemanticResult(c, 0.5)]
        hits = fuse(lexical, vector, {"b"}, HybridConfig())
        self.assertEqual([hit.chunk.chunk_id for hit in hits], ["a", "b", "c"])
        self.assertAlmostEqual(hits[0].score, 1 / 63 + 1 / 61)
        self.assertEqual((hits[0].keyword_rank, hits[0].keyword_score), (3, 500))
        self.assertEqual((hits[0].semantic_rank, hits[0].semantic_score), (1, 0.9))
        self.assertAlmostEqual(hits[1].score, 1 / 61)
        self.assertIsNone(hits[1].semantic_rank)
        self.assertIsNone(hits[2].keyword_score)

    def test_deterministic_tie_and_candidate_depth(self):
        a, b, c = [excerpt(key, key) for key in ("a", "b", "c")]
        keyword = [ChunkKeywordResult(b, 9), ChunkKeywordResult(c, 8)]
        vector = [SemanticResult(a, 0.6), SemanticResult(c, 0.5)]
        hits = fuse(keyword, vector, {"b", "c"}, HybridConfig(candidate_depth=1))
        self.assertEqual([hit.chunk.chunk_id for hit in hits], ["a", "b"])
        self.assertAlmostEqual(hits[0].score, hits[1].score)
        self.assertEqual(len(fuse(keyword, vector, {"b"}, HybridConfig(limit=1))), 1)

    def test_diversification_does_not_add_rejected_chunks_or_merge_distinct_sources(self):
        source = passage("shared", "common text")
        chunks = [excerpt(key, "common text", source) for key in ("a", "b", "c")]
        distinct = excerpt("d", "common text")
        rejected = excerpt("e", "common text")
        hits = fuse([ChunkKeywordResult(rejected, 10)],
                    [SemanticResult(chunk, 0.8) for chunk in [*chunks, distinct]], set(),
                    HybridConfig(max_per_passage=2))
        self.assertEqual([hit.chunk.chunk_id for hit in hits], ["a", "b", "d"])

    def test_cutoff_precedes_fusion_and_incidental_terms_do_not_bypass_it(self):
        source = passage("111", "governance risk tool")
        model = fake_model([[[1, 0]], [[0, 1]], [[0, 1]], [[0, 1]], [[0, 1]]])
        index = semantic.SemanticRetriever([source], model)
        keywords = ChunkKeywordIndex(index.chunks)
        hybrid = HybridRetriever(index, keywords, HybridConfig(candidate_depth=1))
        self.assertEqual(hybrid.search(""), [])
        for question in ("How do I bake a cake for the governance committee?",
                         "How do I water an orchid with a kitchen tool?",
                         "unrelated recipe"):
            self.assertEqual(hybrid.search(question), [])
        relaxed = HybridRetriever(index, keywords, min_score=0)
        hit, = relaxed.search("governance")
        self.assertEqual(hit.semantic_score, 0)
        self.assertEqual(hit.semantic_rank, 1)

    def test_exact_identifiers_and_complete_catalog_name_are_eligible_without_semantic_hit(self):
        catalog, = load_catalog(csv_bytes(row()), "fictional.csv")
        chunk = excerpt("abc123", catalog.text, catalog)
        index = Mock()
        index.search.return_value = []
        hybrid = HybridRetriever(index, ChunkKeywordIndex([chunk]), HybridConfig(candidate_depth=7))
        for question in ("Fictional Compass?", "Show abc123", f"Find {catalog.catalog.record_id}"):
            hit, = hybrid.search(question)
            self.assertIs(hit.chunk.passage.catalog, catalog.catalog)
            self.assertEqual(hit.keyword_rank, 1)
            self.assertIsNone(hit.semantic_rank)
        self.assertEqual(hybrid.search("Can I bake with a Fictional Compass?"), [])
        index.search.assert_called_with(
            "Can I bake with a Fictional Compass?", min_score=0.25, limit=7
        )

    def test_hybrid_rag_citations_abstention_and_catalog_guard(self):
        chunk = excerpt("a42", "tool description")
        index = Mock()
        index.search.return_value = [SemanticResult(chunk, 0.8)]
        generator = Mock()
        generator.generate.return_value = GeneratedAnswer("Fictional answer", "sufficient", ("1",), ())
        retriever = HybridRetriever(index, ChunkKeywordIndex([chunk]))
        answer = RagChat(retriever, generator).ask("tool")
        self.assertIs(answer.cited_sources[0].chunk, chunk)
        index.search.return_value = []
        generator.reset_mock()
        self.assertEqual(RagChat(retriever, generator).ask("cake").status, "insufficient")
        generator.generate.assert_not_called()

        catalog, = load_catalog(csv_bytes(row()), "fictional.csv")
        catalog_chunk = excerpt("b42", catalog.text, catalog)
        client = Mock()
        adapter = GeminiGenerator(GeminiSettings("gemini-test", "dummy"), client)
        with self.assertRaises(GenerationError):
            RagChat(HybridRetriever(index, ChunkKeywordIndex([catalog_chunk])),
                    adapter, corpus_profile="catalog_dev").ask("Fictional Compass")
        client.models.generate_content.assert_not_called()

    def test_hybrid_search_uses_warm_persistent_index_and_profile_gate(self):
        snapshot = profiles.CorpusSnapshot("docs_only", (passage("id", "tool"),), (), "test", "v1")
        with TemporaryDirectory() as directory:
            cold = semantic.SemanticRetriever.from_snapshot(
                snapshot, fake_model([[[1, 0]]]), cache_dir=Path(directory)
            )
            model = fake_model([[[1, 0]]])
            warm = semantic.SemanticRetriever.from_snapshot(snapshot, model, cache_dir=Path(directory))
            self.assertEqual(warm.store.identity, cold.store.identity)
            model.encode.assert_not_called()
            HybridRetriever(warm, ChunkKeywordIndex(warm.chunks)).search("tool")
            model.encode.assert_called_once()
        with patch.object(sys, "argv", ["chat", "--profile", "catalog_unseen_eval", "--mode", "hybrid"]), \
                patch("rag_bot.semantic.load_model") as load, patch("sys.stderr", new=io.StringIO()):
            self.assertEqual(chat.main(), 1)
        load.assert_not_called()

    def test_cli_hybrid_shows_rank_cosine_rrf_and_chunk_metadata(self):
        chunk = excerpt("chunk123", "tool")
        index = Mock(chunks=[chunk], dimension=2)
        index.search.return_value = [SemanticResult(chunk, 0.8)]
        with (
            patch.object(sys, "argv", ["chat", "--mode", "hybrid", "--rrf-k", "42",
                                       "--result-limit", "1", "tool"]),
            patch.object(semantic, "load_model"),
            patch.object(semantic.SemanticRetriever, "from_snapshot", return_value=index),
            redirect_stdout(io.StringIO()) as output,
        ):
            self.assertEqual(chat.main(), 0)
        for expected in ("Retrieval method: hybrid", "RRF k=42", "Rank 1 [chunk123]",
                         "Keyword rank 1", "cosine 0.800", "Corpus version", "Passage ID"):
            self.assertIn(expected, output.getvalue())
