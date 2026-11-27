"""Offline unit tests using a fake tokenizer and fixed embedding vectors."""

import unittest
from unittest.mock import Mock

import numpy as np

from rag_bot.chunking import chunk_passage, token_count
from rag_bot.corpus import Passage
from rag_bot.semantic import SemanticRetriever, normalize_rows


class WordTokenizer:
    def encode(self, text, *, add_special_tokens, truncation, verbose):
        return text.split() + (["[CLS]", "[SEP]"] if add_special_tokens else [])


def passage(number, text, heading="Test Heading"):
    return Passage(str(number), "example.md", heading, "project_policy", "version", text)


def fake_model(vectors, dimension=2):
    model = Mock()
    model.tokenizer = WordTokenizer()
    model.max_seq_length = 32
    model.get_embedding_dimension.return_value = dimension
    model.encode.side_effect = vectors
    return model


class ChunkTests(unittest.TestCase):
    def test_chunks_fit_and_cover_original_with_overlap(self):
        source = passage(1, "First sentence. " * 10 + "\n\n" + "Second paragraph. " * 8)
        tokenizer = WordTokenizer()
        chunks = chunk_passage(source, tokenizer, limit=12, overlap_tokens=3)
        self.assertGreater(len(chunks), 1)
        self.assertEqual(chunks[0].start, 0)
        self.assertEqual(chunks[-1].end, len(source.text))
        self.assertTrue(any(a.end > b.start for a, b in zip(chunks, chunks[1:])))
        for first, second in zip(chunks, chunks[1:]):
            self.assertLess(first.end, second.end)
            self.assertGreaterEqual(first.end, second.start)
        for chunk in chunks:
            self.assertEqual(chunk.passage, source)
            self.assertEqual(chunk.text, source.text[chunk.start:chunk.end])
            self.assertLessEqual(token_count(tokenizer, chunk.embedding_text), 12)
        self.assertEqual(chunks, chunk_passage(source, tokenizer, limit=12, overlap_tokens=3))
        self.assertEqual(len({chunk.chunk_id for chunk in chunks}), len(chunks))

    def test_heading_and_special_tokens_count_against_limit(self):
        with self.assertRaisesRegex(ValueError, "Cannot fit"):
            chunk_passage(passage(1, "one"), WordTokenizer(), limit=4, overlap_tokens=0)


class SemanticTests(unittest.TestCase):
    def test_cosine_with_known_vectors(self):
        model = fake_model([[[3, 4], [-1, 0], [0, 0]], [[2, 0]]])
        index = SemanticRetriever([passage(i, f"Body {i}") for i in range(3)], model, -1)
        np.testing.assert_allclose([hit.score for hit in index.search("question")], [.6, 0, -1])
        np.testing.assert_allclose(normalize_rows(np.array([[0., 0.]])), [[0., 0.]])
        self.assertEqual(model.encode.call_count, 2)
        self.assertGreater(model.encode.call_args_list[0].kwargs["batch_size"], 1)

    def test_top_five_ties(self):
        model = fake_model([[[1, 0]] * 6 + [[0, 1]], [[1, 0]]])
        index = SemanticRetriever([passage(i, f"Body {i}") for i in range(7)], model)
        ids = sorted(chunk.chunk_id for chunk in index.chunks[:6])
        self.assertEqual([hit.chunk.chunk_id for hit in index.search("word")], ids[:5])

    def test_cutoff_filters_unrelated_vector(self):
        model = fake_model([[[0, 1]], [[1, 0]]])
        index = SemanticRetriever([passage(1, "Body")], model, min_score=.25)
        self.assertEqual(index.search("word"), [])

    def test_empty_query_empty_corpus_and_overlong_query(self):
        model = fake_model([])
        index = SemanticRetriever([], model)
        self.assertEqual(index.embeddings.shape, (0, 2))
        self.assertEqual(index.search("word"), [])
        model.encode.assert_not_called()
        model = fake_model([[[1, 0]]])
        index = SemanticRetriever([passage(1, "Body")], model)
        self.assertEqual(index.search(" \t "), [])
        with self.assertRaisesRegex(ValueError, "exceeds 32 tokens"):
            index.search("word " * 32)
        self.assertEqual(model.encode.call_count, 1)

    def test_rejects_embedding_dimensions_that_disagree_with_model(self):
        model = fake_model([[[1, 0, 2]]])
        with self.assertRaisesRegex(ValueError, "invalid vectors"):
            SemanticRetriever([passage(1, "Body")], model)
