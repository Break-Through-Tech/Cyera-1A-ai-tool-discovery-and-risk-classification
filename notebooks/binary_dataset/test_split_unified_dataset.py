import hashlib
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from split_unified_dataset import assign, build, validate_inputs


def example(eid, label, source, group, *, name=None, product=None, member_id=None, record_ids=None, flags=None):
    text = f"Description for {eid} with useful product functionality."
    metadata = {"member_example_ids": [member_id or eid]}
    member_metadata = {}
    if source == "enterprise":
        member_metadata["source_records"] = [{"product_name": name or eid, "product_group_id": product or group}]
    else:
        member_metadata["name"] = name or eid
    member_metadata.update(flags or {})
    metadata.update(member_metadata)
    member = {"example_id": member_id or eid, "source": source, "label": label,
              "source_record_ids": record_ids or [f"{source}-record:{eid}"], "metadata": metadata}
    return {"example_id": eid, "source": source, "source_record_ids": member["source_record_ids"],
            "description_text": text, "description_sha256": hashlib.sha256(text.encode()).hexdigest(),
            "label": label, "leakage_group_id": group, "metadata": metadata}


class SplitDatasetTests(unittest.TestCase):
    def fixture(self):
        rows = []
        # Feasible class and source coverage across three partitions.
        for i in range(30):
            source, label = ("enterprise", "non_ai") if i % 3 == 0 else ("aitoolbuzz", "ai")
            rows.append(example(f"e{i:02}", label, source, f"g{i:02}"))
        return rows

    def test_deterministic_replay_independent_of_input_order(self):
        rows = self.fixture()
        result = assign(rows)
        self.assertEqual(result, assign(list(reversed(rows))))
        expected = {"train": 0.70, "validation": 0.15, "test": 0.15}
        for partition, target in expected.items():
            self.assertLessEqual(abs(len(result[partition]) / len(rows) - target), 0.05)

    def test_skewed_imbalanced_weighted_groups_balance_and_replay(self):
        rows = []
        for source, label, group_count, sizes in (
            ("aitoolbuzz", "ai", 60, (1, 2, 3, 4)),
            ("enterprise", "ai", 30, (1, 2)),
            ("enterprise", "non_ai", 30, (1, 2)),
        ):
            for group_number in range(group_count):
                for member_number in range(sizes[group_number % len(sizes)]):
                    eid = f"{source}-{label}-{group_number:03}-{member_number}"
                    weight = 1 + (group_number + member_number) % 3
                    record_ids = [f"record:{eid}:{index}" for index in range(weight)]
                    rows.append(example(eid, label, source, f"{source}-{label}-group-{group_number:03}",
                                        record_ids=record_ids))

        self.assertEqual({sum(row["leakage_group_id"] == group for row in rows)
                          for group in {row["leakage_group_id"] for row in rows}}, {1, 2, 3, 4})
        self.assertGreater(len({len(row["source_record_ids"]) for row in rows}), 1)
        result = assign(rows)
        self.assertEqual(result, assign(list(reversed(rows))))
        target_ratios = {"train": 0.70, "validation": 0.15, "test": 0.15}
        group_partitions = {}
        for partition, partition_rows in result.items():
            self.assertLessEqual(abs(len(partition_rows) / len(rows) - target_ratios[partition]), 0.03)
            for row in partition_rows:
                group_partitions.setdefault(row["leakage_group_id"], set()).add(partition)
            for label in ("ai", "non_ai"):
                self.assertTrue(any(row["label"] == label for row in partition_rows))
        self.assertTrue(all(len(partitions) == 1 for partitions in group_partitions.values()))

        cohorts = {(row["source"], row["label"]) for row in rows}
        for source, label in cohorts:
            total_members = sum(len(row["source_record_ids"]) for row in rows
                                if row["source"] == source and row["label"] == label)
            for partition, partition_rows in result.items():
                partition_members = sum(len(row["source_record_ids"]) for row in partition_rows
                                         if row["source"] == source and row["label"] == label)
                self.assertGreater(partition_members, 0)
                self.assertLessEqual(abs(partition_members / total_members - target_ratios[partition]), 0.06)

    def test_whole_group_isolation_and_feasible_class_source_coverage(self):
        rows = self.fixture()
        rows.extend([example("merged-a", "ai", "aitoolbuzz", "shared"),
                     example("merged-b", "ai", "aitoolbuzz", "shared")])
        result = assign(rows)
        group_locations = {}
        for partition, values in result.items():
            for row in values:
                group_locations.setdefault(row["leakage_group_id"], set()).add(partition)
        self.assertEqual(len(group_locations), len({r["leakage_group_id"] for r in rows}))
        self.assertTrue(all(len(partitions) == 1 for partitions in group_locations.values()))
        for values in result.values():
            self.assertTrue(any(r["label"] == "ai" for r in values))
            self.assertTrue(any(r["label"] == "non_ai" for r in values))
            self.assertTrue(any(r["source"] == "enterprise" for r in values))
            self.assertTrue(any(r["source"] == "aitoolbuzz" for r in values))
        self.assertEqual(sum(map(len, result.values())), len(rows))

    def test_malformed_or_missing_membership_ids_fail_closed(self):
        row = self.fixture()[0]
        row["metadata"]["member_example_ids"] = []
        with self.assertRaisesRegex(ValueError, "member ID mapping"):
            validate_inputs([row], [])
        row = self.fixture()[0]
        row["metadata"]["member_example_ids"] = [None]
        with self.assertRaisesRegex(ValueError, "member ID mapping"):
            validate_inputs([row], [])

    def test_weak_or_forced_enterprise_member_is_rejected(self):
        weak = example("weak", "non_ai", "enterprise", "weak-group", flags={"evidence_strength": "weak"})
        with self.assertRaisesRegex(ValueError, "weak/forced"):
            validate_inputs([weak], [])

    def test_quarantined_member_is_rejected(self):
        row = self.fixture()[0]
        quarantined = [{"example_id": row["example_id"]}]
        with self.assertRaisesRegex(ValueError, "quarantined example admitted"):
            validate_inputs([row], quarantined)

    def test_existing_output_or_symlink_is_not_overwritten(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            out = root / "exists"
            out.mkdir()
            (out / "keep").write_text("untouched")
            with patch("split_unified_dataset.OUT", out):
                with self.assertRaisesRegex(FileExistsError, "refusing to overwrite"):
                    build(out)
            self.assertEqual((out / "keep").read_text(), "untouched")
            target = root / "target"
            target.mkdir()
            alias = root / "alias"
            alias.symlink_to(target, target_is_directory=True)
            with patch("split_unified_dataset.OUT", alias):
                with self.assertRaises(FileExistsError):
                    build(alias)


if __name__ == "__main__":
    unittest.main()
