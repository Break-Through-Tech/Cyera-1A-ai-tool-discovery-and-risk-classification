import csv
import hashlib
import os
import tempfile
import unittest
from pathlib import Path

import eda


class EdaTests(unittest.TestCase):
    def row(self, number, name, vendor, category="Cat", subcategory="Sub", description="A detailed description."):
        return {"source_record_number": number, "product_name": name, "vendor_name": vendor,
                "taxonomy_category": category, "taxonomy_sub_category": subcategory,
                "product_description": description}

    def test_multiline_csv_refs_are_logical_records(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "products.csv"
            with source.open("w", newline="", encoding="utf-8") as stream:
                writer = csv.writer(stream)
                writer.writerow(eda.FIELDS)
                writer.writerow(["One", "V", "C", "S", "line one\nline two"])
                writer.writerow(["Two", "V", "C", "S", "description"])
            rows = eda.load_rows(source)
        self.assertEqual([row["source_record_number"] for row in rows], [1, 2])

    def test_duplicate_groups_and_conflicting_labels_are_review_only(self):
        rows = [
            self.row(1, "Repeat", "Vendor", "Cat A", "Sub A", "same description"),
            self.row(2, "Repeat", "Vendor", "Cat B", "Sub B", " same   description "),
            self.row(3, "Repeat", "Vendor", "Cat A", "Sub A", "same description"),
        ]
        report, candidates = eda.analyze(rows)
        by_number = {item["source_record_number"]: item for item in candidates}
        self.assertEqual(report["duplicates_and_identity_cues"]["exact_duplicate_extra_rows"], 1)
        self.assertIn("normalized_name_vendor_label_conflict_manual_review", by_number[1]["review_reasons"])
        self.assertIn("normalized_description_label_conflict_manual_review", by_number[2]["review_reasons"])
        self.assertEqual(by_number[1]["related_source_record_numbers"], "2;3")
        self.assertIn("identity_unconfirmed", by_number[3]["review_reasons"])

    def test_whitespace_and_placeholders_are_flagged_not_rewritten(self):
        row = self.row(1, " Name ", "  ", description="name")
        _, candidates = eda.analyze([row])
        candidate = candidates[0]
        self.assertEqual(candidate["product_name"], " Name ")
        self.assertIn("outer_whitespace:product_name", candidate["review_reasons"])
        self.assertIn("missing_or_placeholder:vendor_name", candidate["review_reasons"])

    def test_unicode_and_html_entities_are_flagged(self):
        row = self.row(1, "Cafe\u0301\u200b", "Vendor", description="Useful &amp; <b>safe</b> text")
        _, candidates = eda.analyze([row])
        self.assertIn("unicode_format_character:product_name", candidates[0]["review_reasons"])
        self.assertIn("unicode_normalization_difference:product_name", candidates[0]["review_reasons"])
        self.assertIn("html_entity:product_description", candidates[0]["review_reasons"])
        self.assertIn("html_tag:product_description", candidates[0]["review_reasons"])

    def test_source_placeholder_and_replacement_character_regression(self):
        rows = eda.load_rows(eda.INPUT)
        report, candidates = eda.analyze(rows)
        by_number = {row["source_record_number"]: row for row in candidates}
        for number in (717, 723):
            self.assertIn("missing_or_placeholder:product_description", by_number[number]["review_reasons"])
            self.assertIn("boilerplate_description_review", by_number[number]["review_reasons"])
        self.assertEqual(report["missingness_and_hygiene"]["placeholder_description_count"], 2)
        self.assertIn("fee_name_granularity_review", by_number[9]["review_reasons"])
        self.assertEqual(by_number[9]["product_name"], "Hyperion BI Analysis Fee")
        self.assertEqual(report["review_cues"]["fee_name_examples"][0]["source_record_number"], 9)
        self.assertEqual(report["missingness_and_hygiene"]["replacement_character_description_count"], 52)
        cue_split = report["review_cues"]["ai_ml_keyword_mentions_by_source_taxonomy"]
        self.assertEqual((cue_split["AI & ML"]["count"], cue_split["other_source_categories"]["count"]), (11, 65))
        inside_examples = {item["source_record_number"] for item in cue_split["AI & ML"]["examples"]}
        outside_examples = {item["source_record_number"] for item in cue_split["other_source_categories"]["examples"]}
        self.assertIn(43, inside_examples)
        self.assertIn(16, outside_examples)
        markdown = eda.render_markdown(report)
        self.assertIn("11 within source category AI & ML and 65 outside it", markdown)
        self.assertNotIn("SOURCE.md reports", markdown)
        repeats = report["duplicates_and_identity_cues"]
        self.assertEqual(repeats["trimmed_case_sensitive_name_vendor_repeat_groups"], 25)
        self.assertEqual(repeats["normalized_name_vendor_repeat_groups"], 26)
        self.assertEqual(repeats["normalized_name_vendor_excess_records"], 32)
        self.assertEqual(repeats["normalized_name_vendor_pairwise_comparisons"], 39)
        example_records = {item["source_record_number"] for group in report["label_disagreements"]["examples"] for item in group["source_records"]}
        self.assertTrue({69, 70, 1177, 1178, 1179}.issubset(example_records))

    def test_fee_name_cue_matches_fee_words_not_substrings(self):
        rows = [self.row(1, "Service Fee", "Vendor"), self.row(2, "Processing Fees", "Vendor"),
                self.row(3, "Coffee Platform", "Vendor")]
        report, candidates = eda.analyze(rows)
        self.assertEqual(report["review_cues"]["fee_name_count"], 2)
        flagged = {row["source_record_number"] for row in candidates if "fee_name_granularity_review" in row["review_reasons"]}
        self.assertEqual(flagged, {1, 2})

    def test_keyword_matching_uses_word_boundaries(self):
        rows = [self.row(1, "Air filters", "Vendor", description="Clean air technology"),
                self.row(2, "AI Assistant", "Vendor", description="Product")]
        report, candidates = eda.analyze(rows)
        self.assertEqual(report["review_cues"]["ai_ml_keyword_mention_count"], 1)
        flagged = {item["source_record_number"] for item in candidates if "ai_ml_keyword" in item["review_reasons"]}
        self.assertEqual(flagged, {2})

    def test_output_collision_with_input_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "report.json"
            source.write_text(",".join(eda.FIELDS) + "\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "overwrite the input"):
                eda.write_outputs(source, tmp)

    def test_hard_link_alias_collision_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "input.csv"
            source.write_text(",".join(eda.FIELDS) + "\n", encoding="utf-8")
            alias = Path(tmp) / "report.json"
            os.link(source, alias)
            original = source.read_bytes()
            with self.assertRaisesRegex(ValueError, "filesystem alias"):
                eda.write_outputs(source, tmp)
            self.assertEqual(source.read_bytes(), original)

    def test_report_provenance_matches_custom_fixture_bytes(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "fixture.csv"
            with source.open("w", newline="", encoding="utf-8") as stream:
                writer = csv.writer(stream)
                writer.writerow(eda.FIELDS)
                writer.writerow(["One", "V", "C", "S", "fixture description"])
                writer.writerow(["Two", "V", "C", "S", "another fixture description"])
            original = source.read_bytes()
            report = eda.write_outputs(source, Path(tmp) / "out")
            self.assertEqual(report["dataset"]["sha256"], hashlib.sha256(original).hexdigest())
            self.assertEqual(report["dataset"]["records"], 2)
            self.assertEqual(report["dataset"]["path"], str(source.resolve()))
            self.assertEqual(source.read_bytes(), original)

    def test_schema_and_row_width_are_strict(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "bad.csv"
            source.write_text("wrong,header\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "schema mismatch"):
                eda.load_rows(source)
            for width in (4, 6):
                with source.open("w", newline="", encoding="utf-8") as stream:
                    writer = csv.writer(stream)
                    writer.writerow(eda.FIELDS)
                    writer.writerow(["One", "V", "C", "S", "line one\nline two"])
                    writer.writerow(["Bad"] * width)
                with self.assertRaisesRegex(ValueError, rf"logical source record 2: expected 5 fields, got {width}"):
                    eda.load_rows(source)


if __name__ == "__main__":
    unittest.main()
