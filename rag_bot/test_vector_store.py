"""Offline persistent-index tests using fictional passages and vectors."""

import json
from dataclasses import replace
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

import numpy as np

from rag_bot import profiles, semantic
from rag_bot.test_semantic import fake_model, passage


class PersistentIndexTests(TestCase):
    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.snapshot = profiles.CorpusSnapshot(
            "docs_only", (passage(1, "First"), passage(2, "Second")), (), "test", "fictional-v1"
        )

    def index(self, model, snapshot=None, **kwargs):
        return semantic.SemanticRetriever.from_snapshot(
            snapshot or self.snapshot, model, cache_dir=kwargs.pop("cache_dir", self.root), **kwargs
        )

    def first_index(self):
        return self.index(fake_model([[[3, 4], [0, 1]]]))

    def test_roundtrip_and_query_still_embedded(self):
        cold_model = fake_model([[[3, 4], [0, 1]], [[1, 0]]])
        cold = self.index(cold_model, min_score=0.1)
        warm_model = fake_model([[[1, 0]]])
        warm = self.index(warm_model, min_score=0.2)
        self.assertEqual(cold.index_report.status, "newly built")
        self.assertEqual(warm.index_report.status, "loaded from disk")
        self.assertIsNone(warm.index_report.embedding_seconds)
        self.assertEqual(cold.store.identity, warm.store.identity)
        warm_model.encode.assert_not_called()
        self.assertEqual(cold.search("question"), warm.search("question"))
        warm_model.encode.assert_called_once()
        np.testing.assert_array_equal(cold.embeddings, warm.embeddings)
        self.assertEqual(set(cold.store.metadata["chunk_ids"]), {c.chunk_id for c in cold.chunks})
        self.assertNotIn("First", cold.store.manifest_path.read_text())

    def test_identity_tracks_corpus_order_profile_revision_and_chunking(self):
        original = self.first_index()
        changes = [
            (replace(self.snapshot, corpus_version="new-version"), {}),
            (replace(self.snapshot, passages=self.snapshot.passages[::-1]), {}),
            (self.snapshot, {"overlap_tokens": 12}),
        ]
        for snapshot, options in changes:
            changed = self.index(fake_model([[[1, 0], [0, 1]]]), snapshot, **options)
            self.assertNotEqual(original.store.identity, changed.store.identity)
        with patch.object(profiles, "CATALOG_REUSE_REFERENCE", "fictional permission"):
            dev = self.index(fake_model([[[1, 0], [0, 1]]]),
                             replace(self.snapshot, profile="catalog_dev"))
        self.assertNotEqual(original.store.identity, dev.store.identity)
        with patch.object(semantic, "MODEL_REVISION", "different-revision"):
            revision = self.first_index()
        self.assertNotEqual(original.store.identity, revision.store.identity)

    def replace_vectors(self, store, vectors):
        scratch = self.root / "replacement.npy"
        np.save(scratch, vectors, allow_pickle=False)
        data = scratch.read_bytes()
        checksum = sha256(data).hexdigest()
        (store.directory / f"{checksum}.npy").write_bytes(data)
        store.manifest_path.write_text(json.dumps(store.metadata | {"vector_sha256": checksum}))

    def test_rebuilds_invalid_shape_dtype_numbers_and_norm(self):
        for invalid in (
            np.array([[1, 0]], dtype=np.float32),
            np.eye(2, dtype=np.float64),
            np.array([[np.nan, 0], [0, 1]], dtype=np.float32),
            np.array([[2, 0], [0, 1]], dtype=np.float32),
        ):
            with self.subTest(invalid=invalid):
                current = self.first_index()
                self.replace_vectors(current.store, invalid)
                self.assertEqual(self.first_index().index_report.status, "newly built")

    def test_rebuilds_bad_manifest_order_checksum_and_partial_files(self):
        index = self.first_index()
        store = index.store
        manifest = json.loads(store.manifest_path.read_text())
        vector = store.directory / f"{manifest['vector_sha256']}.npy"
        for defect in ("order", "bad-json", "missing-manifest", "checksum", "missing-vector"):
            with self.subTest(defect=defect):
                if defect == "order":
                    store.manifest_path.write_text(json.dumps(
                        manifest | {"chunk_ids": manifest["chunk_ids"][::-1]}
                    ))
                elif defect == "bad-json":
                    store.manifest_path.write_text("{")
                elif defect == "missing-manifest":
                    store.manifest_path.unlink()
                    (store.directory / ".writing-interrupted").write_bytes(b"partial")
                elif defect == "checksum":
                    vector.write_bytes(b"corrupt")
                else:
                    vector.unlink()
                self.assertEqual(self.first_index().index_report.status, "newly built")

    def test_rebuild_and_memory_only(self):
        original = self.first_index()
        model = fake_model([[[1, 0], [0, 1]]])
        rebuilt = self.index(model, rebuild=True)
        self.assertEqual(rebuilt.store.identity, original.store.identity)
        self.assertEqual(rebuilt.index_report.status, "newly built")
        model.encode.assert_called_once()
        memory = self.index(fake_model([[[1, 0], [0, 1]]]), cache_dir=None)
        self.assertIsNone(memory.store)
        self.assertEqual(memory.index_report.status, "memory-only")

    def test_unauthorized_profile_fails_before_cache_lookup(self):
        for profile in ("catalog_dev", "catalog_unseen_eval"):
            with self.subTest(profile=profile), patch.object(
                profiles, "CATALOG_REUSE_REFERENCE", None
            ), patch("rag_bot.semantic.VectorStore") as store:
                model = fake_model([])
                with self.assertRaises(profiles.ProfileError):
                    self.index(model, replace(self.snapshot, profile=profile))
                store.assert_not_called()
                model.encode.assert_not_called()
