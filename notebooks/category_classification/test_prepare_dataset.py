"""Focused checks for review decisions and cross-partition leakage controls."""

import csv
import importlib.util
import json
import unittest
from collections import defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = Path(__file__).with_name("prepare_dataset.py")
spec = importlib.util.spec_from_file_location("category_preparation", SCRIPT)
preparation = importlib.util.module_from_spec(spec)
spec.loader.exec_module(preparation)


class PreparationTests(unittest.TestCase):
    def test_duplicate_description_decisions(self):
        def row(identifier, category, description):
            return {
                "tool_id": identifier, "Name": identifier, "Website": f"https://{identifier}.example",
                "Category": category, "Short Description": description,
                "duplicate_description_flag": "review_duplicate",
                "description_label_conflict_flag": "review_label_conflict" if identifier in {"c", "d"} else "ok",
            }

        rows = [row("a", "Alpha", "Shared text"), row("b", "Alpha", "Shared text"),
                row("c", "Alpha", "Other text"), row("d", "Beta", "Other text")]
        eligible, review = preparation.triage_descriptions(rows)
        self.assertEqual({item["tool_id"] for item in eligible}, {"a", "b"})
        self.assertEqual(sum(item["disposition"] == "exclude_pending_label_review" for item in review), 2)

    def test_near_description_grouping(self):
        rows = [
            {"tool_id": "a", "Name": "First", "Website": "https://first.example",
             "Short Description": "An AI image creation platform for artists and designers with custom styles"},
            {"tool_id": "b", "Name": "Second", "Website": "https://second.example",
             "Short Description": "An AI image creation platform for artists and designers with custom style"},
            {"tool_id": "c", "Name": "Third", "Website": "https://third.example",
             "Short Description": "A customer support chatbot that answers questions across company documents"},
        ]
        groups, near = preparation.identity_groups(rows)
        self.assertEqual(groups[0], groups[1])
        self.assertNotEqual(groups[0], groups[2])
        self.assertTrue(any({left, right} == {0, 1} for left, right, _ in near))

    def test_frozen_partitions_have_no_shared_identity_cues(self):
        data = ROOT / "data/category_classification/v1"
        manifest = json.loads((data / "manifest.json").read_text(encoding="utf-8"))
        seen = defaultdict(set)
        ids = set()
        group_by_id = {}
        for partition in preparation.SPLITS:
            path = data / f"{partition}.csv"
            self.assertEqual(preparation.sha256(path), manifest["partitions"][partition]["sha256"])
            with path.open(encoding="utf-8", newline="") as stream:
                rows = list(csv.DictReader(stream))
            self.assertEqual(len(rows), manifest["partitions"][partition]["rows"])
            for row in rows:
                self.assertNotIn(row["tool_id"], ids)
                ids.add(row["tool_id"])
                group_by_id[row["tool_id"]] = row["group_id"]
                seen[row["group_id"]].add(partition)
                seen[preparation.description_key(row["description_text"])].add(partition)
        self.assertTrue(all(len(partitions) == 1 for partitions in seen.values()))
        self.assertEqual(len(ids), manifest["counts"]["eligible_rows"])
        with (data / "description_review.csv").open(encoding="utf-8", newline="") as stream:
            review = list(csv.DictReader(stream))
        self.assertEqual(len(review), manifest["counts"]["review_rows"])
        self.assertEqual(sum(row["disposition"] == "exclude_pending_label_review" for row in review), 10)
        self.assertTrue(all(row["tool_id"] not in ids for row in review
                            if row["disposition"] == "exclude_pending_label_review"))
        with (data / "near_description_review.csv").open(encoding="utf-8", newline="") as stream:
            near = list(csv.DictReader(stream))
        self.assertEqual(len(near), manifest["counts"]["near_description_pairs_grouped"])
        for pair in near:
            self.assertEqual(group_by_id[pair["left_tool_id"]], group_by_id[pair["right_tool_id"]])


if __name__ == "__main__":
    unittest.main()
