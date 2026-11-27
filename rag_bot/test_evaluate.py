"""Hand-calculated metrics and isolation checks for offline evaluation."""

import copy
import json
import math
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import Mock

from rag_bot.evaluate import calibrate, load_benchmark, outcome, ranking_metrics


CHUNK_MAP = {"a": "first", "b": "first", "c": "second", "d": "third"}


def question(identity="one", partition="calibration", family="first"):
    return {"id": identity, "text": f"Question {identity}?", "category": "multi_evidence",
            "partition": partition, "family": family, "answerability": "answerable",
            "expected_behavior": "retrieve_direct", "rationale": "Fictional evidence.",
            "passages": {"first": 2, "second": 2, "third": 1},
            "chunks": {"a": 2, "b": 2, "c": 2, "d": 1}, "evidence_groups": [["a", "b"], ["c"]]}


class MetricTests(TestCase):
    def test_known_grades_and_fixed_precision_denominator(self):
        result = ranking_metrics(["background", "hit", "hit", "unjudged"], {
            "hit": 2, "missing": 2, "background": 1
        }, k=5)
        self.assertEqual(result["hit"], 1)
        self.assertEqual(result["precision"], .2)
        self.assertEqual(result["recall"], .5)
        self.assertEqual(result["rr"], .5)
        self.assertAlmostEqual(result["ndcg"], (1 + 3 / math.log2(3))
                               / (3 + 3 / math.log2(3) + 1 / math.log2(4)))
        self.assertEqual(set(ranking_metrics([], {"hit": 2}).values()), {0})

    def test_deduplicate_passages_and_measure_separate_evidence_groups(self):
        result = outcome(question(), ["first", "first", "second"], ["a", "b", "c"], CHUNK_MAP)
        self.assertEqual(result["distinct_passages"], 2)
        self.assertEqual(result["passage"]["precision"], .4)
        self.assertEqual(result["chunk"]["precision"], .6)
        self.assertEqual(result["chunk"]["evidence_coverage"], 1)
        partial = outcome(question(), ["first", "first"], ["a", "b"], CHUNK_MAP)
        self.assertEqual(partial["chunk"]["evidence_coverage"], .5)
        self.assertEqual(partial["chunk"]["all_evidence_groups"], 0)

    def test_abstention_and_unsupported_background_are_separate(self):
        self.assertEqual(outcome(question(), [], [], CHUNK_MAP)["chunk"]["false_abstention"], 1)
        ood = dict(answerability="out_of_domain", chunks={}, passages={})
        self.assertEqual(outcome(ood, [], [], CHUNK_MAP)["chunk"], {"correct_empty": 1})
        self.assertEqual(outcome(ood, ["first"], ["a"], CHUNK_MAP)["chunk"], {"correct_empty": 0})
        unsupported = dict(answerability="insufficient", chunks={"d": 1}, passages={"third": 1})
        self.assertEqual(outcome(unsupported, ["third"], ["d"], CHUNK_MAP)["chunk"],
                         {"background_hit": 1, "no_results": 0})


class BenchmarkTests(TestCase):
    def setUp(self):
        root = TemporaryDirectory()
        self.addCleanup(root.cleanup)
        self.path = Path(root.name) / "benchmark.json"
        self.data = {"version": "test", "corpus_profile": "docs_only", "corpus_version": "v1",
                     "questions": [question(), question("two", "held_out", "second")]}

    def read(self, data=None, corpus_version="v1"):
        self.path.write_text(json.dumps(self.data if data is None else data))
        return load_benchmark(self.path, corpus_version, CHUNK_MAP)

    def test_round_trip_and_fingerprint(self):
        first, digest = self.read()
        self.assertEqual(first, self.data)
        self.assertEqual(digest, self.read()[1])
        revised = copy.deepcopy(self.data)
        revised["questions"][0]["rationale"] = "Revised rationale."
        self.assertNotEqual(digest, self.read(revised)[1])

    def test_stale_versions_grades_ids_and_schema(self):
        with self.assertRaisesRegex(ValueError, "corpus version"):
            self.read(corpus_version="stale")
        for key, bad_value, error in (
            ("chunks", {"stale": 2}, "stale chunk ID"),
            ("chunks", {"a": 3}, "Invalid grade"),
            ("passages", {"stale": 2}, "stale passage"),
            ("evidence_groups", [["a"], ["stale"]], "multi-evidence"),
            ("expected_behavior", "anything", "expected behavior"),
            ("rationale", "", "metadata"),
        ):
            with self.subTest(key=key):
                invalid = copy.deepcopy(self.data)
                invalid["questions"][0][key] = bad_value
                with self.assertRaisesRegex(ValueError, error):
                    self.read(invalid)

    def test_partition_and_family_disjointness(self):
        for key, value, error in (("family", "first", "family crosses"),
                                  ("id", "one", "Duplicate"),
                                  ("partition", "calibration", "Both benchmark partitions")):
            with self.subTest(key=key):
                invalid = copy.deepcopy(self.data)
                invalid["questions"][1][key] = value
                with self.assertRaisesRegex(ValueError, error):
                    self.read(invalid)

    def test_calibration_refuses_held_out_before_retrieval_and_is_deterministic(self):
        index = Mock(chunks=[])
        keywords = Mock()
        with self.assertRaisesRegex(ValueError, "only calibration"):
            calibrate(self.data["questions"], index, keywords, CHUNK_MAP)
        index.search.assert_not_called()
        keywords.search.assert_not_called()
        index.search.return_value = []
        keywords.search.return_value = []
        keywords.exact_references.return_value = set()
        inputs = [question(), dict(question("empty"), category="out_of_domain",
                                   answerability="out_of_domain", chunks={}, passages={})]
        selected, sweep = calibrate(inputs, index, keywords, CHUNK_MAP)
        self.assertEqual((selected, sweep), calibrate(inputs, index, keywords, CHUNK_MAP))
        self.assertEqual(index.search.call_count, 2 * len(inputs))
        self.assertEqual(len(sweep), 24)
