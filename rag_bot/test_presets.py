"""Preset and frozen-report regression checks."""

import io
import json
import sys
from contextlib import redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import Mock, patch

from rag_bot import chat, semantic
from rag_bot.evaluation_view import ROOT, read_evaluation
from rag_bot.presets import HYBRID_BASELINE, HYBRID_CALIBRATED, SEMANTIC_STABLE
from rag_bot.profiles import load_snapshot


class PresetTests(TestCase):
    def test_presets_match_frozen_reports(self):
        frozen = json.loads((ROOT / "results" / "selection.json").read_bytes())["selected"]
        self.assertEqual(SEMANTIC_STABLE.cutoff, frozen["semantic"]["cutoff"])
        self.assertEqual(SEMANTIC_STABLE.limit, frozen["semantic"]["limit"])
        self.assertEqual(HYBRID_BASELINE.hybrid_config().summary(),
                         "RRF k=60, depth=20 per method, limit=5, per-passage cap=2")
        config = HYBRID_CALIBRATED.hybrid_config()
        self.assertEqual((HYBRID_CALIBRATED.cutoff, config.smoothing, config.candidate_depth,
                          config.limit, config.max_per_passage),
                         tuple(frozen["hybrid"][key] for key in
                               ("cutoff", "smoothing", "depth", "limit", "cap")))

    def test_cli_calibrated_preset_and_invalid_mode_combination(self):
        index = Mock(chunks=[], dimension=2)
        index.search.return_value = []
        with (
            patch.object(sys, "argv", ["chat", "--mode", "hybrid", "--preset", "hybrid-calibrated",
                                       "Question?"]),
            patch.object(semantic, "load_model"),
            patch.object(semantic.SemanticRetriever, "from_snapshot", return_value=index),
            redirect_stdout(io.StringIO()) as output,
        ):
            self.assertEqual(chat.main(), 0)
        self.assertIn("Calibrated (experimental)", output.getvalue())
        self.assertIn("RRF k=10, depth=20 per method, limit=5, per-passage cap=none", output.getvalue())
        with patch.object(sys, "argv", ["chat", "--preset", "hybrid-calibrated"]), \
                patch("sys.stderr", new=io.StringIO()), self.assertRaises(SystemExit):
            chat.main()

    def test_evaluation_view_reads_both_report_partitions_and_rejects_stale_data(self):
        version = load_snapshot().corpus_version
        _, count, identity, partitions = read_evaluation(version)
        self.assertEqual(count, 60)
        self.assertEqual(identity["corpus_version"], version)
        self.assertEqual([part[0] for part in partitions.values()], [36, 24])
        held_out = {row["Method"]: row for row in partitions["held_out"][1]}
        self.assertEqual(held_out["Hybrid — Calibrated (experimental)"]["OOD empty"], "2/3")
        self.assertTrue(partitions["held_out"][2])
        with self.assertRaisesRegex(ValueError, "Stale"):
            read_evaluation("changed")
        with TemporaryDirectory() as directory, self.assertRaises(FileNotFoundError):
            read_evaluation(version, Path(directory))

    def test_cli_does_not_print_private_startup_or_search_errors(self):
        with (
            patch.object(sys, "argv", ["chat", "--mode", "semantic", "Question?"]),
            patch.object(semantic, "load_model", side_effect=OSError("/private/model/file")),
            patch("sys.stderr", new=io.StringIO()) as stderr,
        ):
            self.assertEqual(chat.main(), 1)
            self.assertIn("Could not start retrieval", stderr.getvalue())
            self.assertNotIn("/private", stderr.getvalue())
        with patch("sys.stderr", new=io.StringIO()) as stderr:
            self.assertEqual(chat.run_questions(
                "Question?", Mock(side_effect=OSError("/private/cache/file"))
            ), 1)
            self.assertIn("retrieval request failed", stderr.getvalue())
            self.assertNotIn("/private", stderr.getvalue())
