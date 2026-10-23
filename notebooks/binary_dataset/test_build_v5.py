import unittest
from unittest.mock import patch

import build_v5
from build_v5 import carry_forward_assign, is_new_in_v5, select_exports
from test_split_unified_dataset import example


class CarryForwardTests(unittest.TestCase):
    def fixture(self):
        rows = []
        for i in range(30):
            source, label = ("enterprise", "non_ai") if i % 3 == 0 else ("aitoolbuzz", "ai")
            rows.append(example(f"e{i:02}", label, source, f"g{i:02}"))
        return rows

    def test_v4_members_keep_partition_and_new_groups_are_assigned(self):
        rows = self.fixture()
        v4 = {"e00": "test", "e01": "validation", "e02": "train"}
        result = carry_forward_assign(rows, v4)
        location = {r["example_id"]: p for p, part in result.items() for r in part}
        self.assertEqual({k: location[k] for k in v4}, v4)
        self.assertEqual(set(location), {r["example_id"] for r in rows})
        self.assertEqual(result, carry_forward_assign(list(reversed(rows)), v4))

    def test_new_example_joining_v4_group_follows_that_partition(self):
        rows = self.fixture() + [example("new", "non_ai", "enterprise", "g00")]
        result = carry_forward_assign(rows, {"e00": "test"})
        self.assertIn("new", {r["example_id"] for r in result["test"]})
        self.assertFalse(is_new_in_v5(rows[0], {"e00": "test"}))
        self.assertTrue(is_new_in_v5(rows[-1], {"e00": "test"}))

    def test_group_bridging_v4_partitions_fails(self):
        rows = self.fixture()
        rows[1]["leakage_group_id"] = rows[0]["leakage_group_id"]
        with self.assertRaisesRegex(ValueError, "different partitions"):
            carry_forward_assign(rows, {"e00": "test", "e01": "train"})


class SelectExportsTests(unittest.TestCase):
    def paths(self, *bases):
        return {f"{b}/{n}" for b in bases for n in ("description_labels.json", "record_labels.json", "PARENT_VALIDATION.json")}

    def run_select(self, paths, receipts):
        with patch.object(build_v5, "git_json", side_effect=lambda path, cutoff=None: receipts[path.rsplit("/", 1)[0]]):
            return select_exports(paths)

    def test_parent_integration_copy_supersedes_original(self):
        paths = self.paths("runs/batch-015", "runs/batch-015-parent-integration")
        selected, skipped = self.run_select(paths, {"runs/batch-015-parent-integration": {"status": "accepted"}})
        self.assertEqual([b for b, _ in selected], ["runs/batch-015-parent-integration"])
        self.assertEqual(skipped[0]["export"], "runs/batch-015")

    def test_unaccepted_or_held_export_fails(self):
        for status in ("pending_parent_independent_acceptance", "semantic_acceptance_hold"):
            with self.subTest(status=status), self.assertRaises(ValueError):
                self.run_select(self.paths("runs/batch-001"), {"runs/batch-001": {"status": status}})

    def test_held_batches_are_left_to_record_level_release(self):
        held = sorted(build_v5.HELD_BATCHES)[0]
        selected, skipped = self.run_select(self.paths(held), {})
        self.assertEqual(selected, [])
        self.assertEqual(skipped[0]["reason"], "semantic_hold_resolved_by_record_level_release")


if __name__ == "__main__":
    unittest.main()
