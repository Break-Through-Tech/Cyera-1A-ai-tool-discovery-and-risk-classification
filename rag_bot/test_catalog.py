"""Catalog and profile tests using only fictional listings."""

import csv
import io
import json
from contextlib import contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import Mock, patch

from rag_bot import profiles
from rag_bot.catalog import COLUMNS, load_catalog
from rag_bot.chunking import Chunk
from rag_bot.generator import GeminiGenerator, GeminiSettings, GenerationError
from rag_bot.prompts import build_prompt
from rag_bot.rag import RagChat


FICTIONAL_ID = "a" * 64
FIXTURE_FILE = "fictional.csv"


def row(**updates):
    record = dict(zip(COLUMNS, (
        FICTIONAL_ID, "Fictional Compass", "https://compass.example/path", "Example Category",
        "Organize examples", "  An invented description.\nSecond line.  ", "", "",
        "ok", "ok", "ok",
    )))
    return record | updates


def csv_bytes(*records):
    target = io.StringIO(newline="")
    writer = csv.DictWriter(target, fieldnames=COLUMNS)
    writer.writeheader()
    writer.writerows(records)
    return target.getvalue().encode()


@contextmanager
def fictional_profile(*records):
    with TemporaryDirectory() as directory:
        root = Path(directory).resolve()
        path = root / FIXTURE_FILE
        path.write_bytes(csv_bytes(*records))
        with (
            patch.object(profiles, "REPO_ROOT", root),
            patch.object(profiles, "CATALOG_PATH", FIXTURE_FILE),
            patch.object(profiles, "CATALOG_REUSE_REFERENCE", "fictional fixture permission"),
        ):
            yield path


class CatalogTests(TestCase):
    def test_valid_rows_preserve_exact_evidence_and_missing_values(self):
        passage, second = load_catalog(csv_bytes(row(), row(tool_id="b" * 64)), FIXTURE_FILE)
        self.assertEqual(passage.heading, "Fictional Compass")
        self.assertEqual(passage.text, row()["Short Description"])
        self.assertEqual(passage.source_role, "tool_evidence")
        self.assertEqual(passage.catalog.record_id, f"aitoolbuzz:{FICTIONAL_ID}")
        self.assertEqual(passage.catalog.hostname, "compass.example")
        self.assertEqual(passage.catalog.website, "https://compass.example/path")
        self.assertEqual(passage.catalog.category, "Example Category")
        self.assertEqual(passage.catalog.primary_task, "Organize examples")
        self.assertIsNone(passage.catalog.keywords)
        self.assertIsNone(passage.catalog.industry)
        self.assertNotEqual(passage.passage_id, second.passage_id)

    def test_schema_required_fields_ids_and_flags(self):
        for data, message in (
            (b"Name,Website\nexample,example.test\n", "columns"),
            (csv_bytes(row(**{"Short Description": "   "})), "missing Short Description"),
            (csv_bytes(row(tool_id="bad")), "Invalid tool ID"),
            (csv_bytes(row(), row()), "Duplicate tool ID"),
            (csv_bytes(row(text_quality_flag="invented")), "Invalid text_quality_flag"),
            (csv_bytes(row(Website="bad.example")), "Invalid website"),
        ):
            with self.subTest(message=message):
                with self.assertRaisesRegex(ValueError, message):
                    load_catalog(data, FIXTURE_FILE)

    def test_passage_identity_stays_stable_as_content_changes(self):
        original, = load_catalog(csv_bytes(row()), FIXTURE_FILE)
        edited, = load_catalog(csv_bytes(row(Category="Edited", **{"Short Description": "New"})),
                              FIXTURE_FILE)
        self.assertEqual(original.passage_id, edited.passage_id)
        self.assertNotEqual(original.content_version, edited.content_version)

    def test_verified_holdouts_conflicts_and_reviewed_identities(self):
        holdouts = tuple(profiles.FIXTURE_HOLDOUTS)
        with fictional_profile(
            row(),
            row(tool_id=holdouts[0], Name="Fictional Alias One"),
            row(tool_id=holdouts[1], Name="Fictional Alias Two"),
            row(tool_id="b" * 64, description_label_conflict_flag="review_label_conflict"),
            row(tool_id="c" * 64),
            row(tool_id="d" * 64, text_quality_flag="review_short"),
        ), patch.object(profiles, "REVIEWED_IDENTITY_EXCLUSIONS",
                        (("c" * 64, "Fictional reviewed alias"),)):
            snapshot = profiles.load_snapshot(profiles.CATALOG_DEV)
        catalog = [p for p in snapshot.passages if p.catalog]
        self.assertEqual(len(catalog), 2)
        self.assertEqual(catalog[1].catalog.text_quality_flag, "review_short")
        self.assertEqual([entry.reasons for entry in snapshot.exclusions], [
            ("fixture_holdout: MeetOscar",), ("fixture_holdout: Magic Inspector",),
            ("description_category_conflict",),
            ("reviewed_identity_exclusion: Fictional reviewed alias",),
        ])

    def test_corpus_version_tracks_source_and_policy(self):
        with fictional_profile(row()) as path:
            original = profiles.load_snapshot(profiles.CATALOG_DEV)
            self.assertEqual(original, profiles.load_snapshot(profiles.CATALOG_DEV))
            path.write_bytes(csv_bytes(row(Category="Edited")))
            edited = profiles.load_snapshot(profiles.CATALOG_DEV)
            self.assertNotEqual(original.source_fingerprints, edited.source_fingerprints)
            self.assertNotEqual(original.corpus_version, edited.corpus_version)
            with patch.object(profiles, "CATALOG_POLICY_VERSION", "new-policy"):
                self.assertNotEqual(edited.corpus_version,
                                    profiles.load_snapshot(profiles.CATALOG_DEV).corpus_version)
            with patch.object(profiles, "REVIEWED_IDENTITY_EXCLUSIONS",
                              ((FICTIONAL_ID, "Fictional exclusion"),)):
                self.assertNotEqual(edited.corpus_version,
                                    profiles.load_snapshot(profiles.CATALOG_DEV).corpus_version)

    def test_blocked_profiles_fail_before_opening_sources(self):
        with (
            patch.object(profiles, "CATALOG_REUSE_REFERENCE", None),
            patch.object(profiles, "load_documents") as docs,
            patch.object(Path, "read_bytes") as read,
        ):
            with self.assertRaisesRegex(profiles.ProfileError, "confirmed catalog reuse"):
                profiles.load_snapshot(profiles.CATALOG_DEV)
            with self.assertRaisesRegex(profiles.ProfileError, "checksum"):
                profiles.load_snapshot(profiles.CATALOG_UNSEEN_EVAL)
        docs.assert_not_called()
        read.assert_not_called()

    def test_catalog_citation_metadata_and_external_transmission_guard(self):
        passage, = load_catalog(csv_bytes(row()), FIXTURE_FILE)
        chunk = Chunk(passage, 0, len(passage.text), "fictional-chunk")
        prompt = build_prompt("What does the listing say?", [chunk],
                              corpus_profile=profiles.CATALOG_DEV, corpus_version="fictional-v")
        body = json.loads(prompt.user_message)
        self.assertEqual(body["corpus_version"], "fictional-v")
        self.assertEqual(body["evidence"][0]["catalog"]["tool_id"], FICTIONAL_ID)
        self.assertEqual(body["evidence"][0]["text"], passage.text)
        client = Mock()
        generator = GeminiGenerator(GeminiSettings("gemini-test", "dummy"), client)
        with self.assertRaisesRegex(GenerationError, "local only"):
            generator.generate(build_prompt("Question?", [chunk]))
        with self.assertRaisesRegex(GenerationError, "local only"):
            generator.generate(build_prompt("Question?", [], corpus_profile=profiles.CATALOG_DEV))
        retriever = Mock()
        retriever.search.return_value = [Mock(chunk=chunk)]
        with self.assertRaisesRegex(GenerationError, "local only"):
            RagChat(retriever, generator, corpus_profile=profiles.CATALOG_DEV).ask("Question?")
        client.models.generate_content.assert_not_called()

    def test_docs_only_preserves_passages_and_ids(self):
        snapshot = profiles.load_snapshot()
        self.assertEqual(snapshot.profile, profiles.DOCS_ONLY)
        self.assertEqual(len(snapshot.passages), 7)
        self.assertEqual(snapshot.source_roles, ("project_policy",))
        language = next(p for p in snapshot.passages if p.heading == "Language")
        self.assertEqual(language.passage_id, "c44b2b41dea183af")
        self.assertEqual(snapshot, profiles.load_snapshot(profiles.DOCS_ONLY))
