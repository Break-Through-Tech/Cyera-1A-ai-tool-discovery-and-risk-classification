import copy
import hashlib
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from review_dataset_leakage import analyze, build


def example(eid, text, label="ai", source="aitoolbuzz", metadata=None):
    return {"example_id": eid, "source": source, "source_record_ids": [eid], "description_text": text,
            "description_sha256": hashlib.sha256(text.encode()).hexdigest(), "label": label,
            "metadata": metadata or {}}


class LeakageReviewTests(unittest.TestCase):
    def test_normalized_duplicates_merge_preserving_members_and_conflict_quarantine(self):
        a = example("a", "A useful scheduling system", "ai")
        b = example("b", " a useful   scheduling system ", "non_ai", "enterprise",
                    {"source_records": [{"source_record_number": "1", "product_group_id": "g"}]})
        result = analyze([a, b])
        self.assertEqual(result["summary"]["duplicate_examples_removed"], 1)
        self.assertEqual(result["summary"]["high_confidence_conflict_groups"], 1)
        self.assertEqual(result["examples"], [])
        self.assertEqual(len(result["quarantined"]), 1)
        self.assertEqual(result["quarantined"][0]["metadata"]["member_example_ids"], ["a", "b"])
        self.assertEqual(result["quarantined"][0]["source_record_ids"], ["a", "b"])
        self.assertEqual({member["example_id"]: member["source_record_ids"]
                          for member in result["quarantined"][0]["metadata"]["members"]},
                         {"a": ["a"], "b": ["b"]})

    def test_enterprise_product_group_links_distinct_texts_and_conflict_quarantines_group(self):
        rows = [{"source_record_number": "1", "product_group_id": "same", "product_name": "Tool"},
                {"source_record_number": "2", "product_group_id": "same", "product_name": "Tool"}]
        a = example("a", "This is a long description about standard office scheduling and team collaboration features.", "ai", "enterprise", {"source_records": [rows[0]]})
        b = example("b", "This is a different long description about standard payroll management and accounting features.", "non_ai", "enterprise", {"source_records": [rows[1]]})
        result = analyze([a, b])
        self.assertEqual(len(result["conflicts"]), 1)
        self.assertEqual(len(result["quarantined"]), 2)
        self.assertEqual(result["conflicts"][0]["evidence"][0]["reason"], "opposite_labels_high_confidence_enterprise_product_group")

    def test_shared_host_does_not_merge_different_tools_and_ambiguous_name_is_reviewed(self):
        one = example("a", "Description one", metadata={"name": "Alpha", "website": "https://tools.example.com"})
        two = example("b", "Description two", metadata={"name": "Beta", "website": "https://tools.example.com"})
        result = analyze([one, two])
        self.assertEqual(result["summary"]["leakage_groups"], 2)
        self.assertEqual(result["summary"]["eligible_examples"], 2)

    def test_name_only_candidates_with_partial_shared_domains_all_group_but_remain_ambiguous(self):
        rows = [example("a", "Description one", metadata={"name": "Same Tool", "website": "https://one.example"}),
                example("b", "Description two", metadata={"name": "Same-Tool", "website": "https://one.example"}),
                example("c", "Description three", metadata={"name": "Same Tool", "website": "https://two.example"})]
        result = analyze(rows)
        self.assertEqual(result["summary"]["leakage_groups"], 1)
        self.assertEqual(result["identity_review"][0]["identity_status"], "ambiguous")
        self.assertEqual(len({x["leakage_group_id"] for x in result["examples"]}), 1)
        self.assertEqual(result["conflicts"], [])

    def test_near_duplicate_candidate_groups_without_merging_and_is_deterministic(self):
        atext = "".join(f"Distinctive token{i} " for i in range(12)) + "supports secure customer workflows today."
        btext = "".join(f"Distinctive token{i} " for i in range(11)) + "supports secure customer workflows now."
        rows = [example("a", atext), example("b", btext)]
        left = analyze(rows)
        right = analyze(copy.deepcopy(rows))
        self.assertEqual(left, right)
        self.assertEqual(left["summary"]["near_text_candidate_pairs"], 1)
        self.assertEqual(left["summary"]["merged_examples"], 2)
        self.assertEqual(left["examples"][0]["leakage_group_id"], left["examples"][1]["leakage_group_id"])
        self.assertEqual(left["identity_review"][0]["identity_status"], "unconfirmed")

    def test_cross_source_name_candidate_is_grouped_but_not_claimed_or_quarantined(self):
        enterprise = example("enterprise", "Description for the tool", "non_ai", "enterprise",
            {"source_records": [{"product_name": "Shared Tool", "vendor_name": "Acme", "product_group_id": "g"}]})
        catalog = example("catalog", "Another description", "ai", "aitoolbuzz",
            {"name": "Shared Tool", "website": "https://acme.example/product"})
        result = analyze([enterprise, catalog])
        self.assertEqual(result["summary"]["high_confidence_conflict_groups"], 0)
        self.assertEqual(result["summary"]["quarantined_source_class_memberships"], {})
        self.assertEqual(result["summary"]["leakage_groups"], 1)
        self.assertEqual(result["identity_review"][0]["identity_status"], "ambiguous")

    def test_partial_vendor_corroboration_links_all_names_without_cross_subgroup_conflicts(self):
        rows = [
            example("a", "description a", "ai", metadata={"name": "Same Tool", "vendor_name": "Acme", "website": "https://catalog.example/a"}),
            example("b", "description b", "non_ai", metadata={"name": "Same Tool", "vendor_name": "Acme", "website": "https://catalog.example/b"}),
            example("c", "description c", "ai", metadata={"name": "Same Tool", "vendor_name": "Other", "website": "https://catalog.example/c"}),
        ]
        result = analyze(rows)
        self.assertEqual(result["summary"]["leakage_groups"], 1)
        self.assertEqual(len({x["leakage_group_id"] for x in result["quarantined"]}), 1)
        self.assertEqual(len(result["conflicts"]), 1)
        evidence = result["conflicts"][0]["evidence"]
        self.assertEqual(len(evidence), 1)
        self.assertEqual({evidence[0]["left_example_id"], evidence[0]["right_example_id"]}, {"a", "b"})
        self.assertEqual(evidence[0]["evidence"]["shared_vendor"], "acme")
        self.assertNotIn("shared_domains", evidence[0]["evidence"])
        self.assertEqual(result["identity_review"][0]["identity_status"], "candidate_same_tool")
        self.assertEqual(result["identity_review"][0]["corroborating_evidence"]["shared_domains_ambiguous_only"], ["catalog.example"])

    def test_existing_output_is_not_overwritten(self):
        with TemporaryDirectory() as tmp:
            out = Path(tmp) / "exists"
            out.mkdir()
            with patch("review_dataset_leakage.OUT", out):
                with self.assertRaisesRegex(FileExistsError, "refusing to overwrite"):
                    build()
            self.assertEqual(list(out.iterdir()), [])

    def test_duplicate_ids_and_bad_hashes_fail_closed(self):
        row = example("a", "valid")
        with self.assertRaisesRegex(ValueError, "duplicate example ID"):
            analyze([row, row])
        row["description_sha256"] = "bad"
        with self.assertRaisesRegex(ValueError, "invalid example description/hash"):
            analyze([row])


if __name__ == "__main__":
    unittest.main()
