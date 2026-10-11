import csv
import hashlib
import json
import os
import tempfile
import unittest
from pathlib import Path

import clean


class CleanerTests(unittest.TestCase):
    def row(self, number, name="Product", vendor="Vendor", category="Category",
            subcategory="Subcategory", description="Useful product functionality"):
        return {"source_record_number": number, "product_name": name, "vendor_name": vendor,
                "taxonomy_category": category, "taxonomy_sub_category": subcategory,
                "product_description": description}

    def write_source(self, path, rows):
        with path.open("w", encoding="utf-8", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=clean.FIELDS)
            writer.writeheader()
            writer.writerows({field: row[field] for field in clean.FIELDS} for row in rows)

    def test_normalization_preserves_internal_spacing_and_legitimate_unicode(self):
        source = self.row(1, name=" Product ", description="  Café™  tools\r\nsecond line\rthird line  ")
        retained, report = clean.clean_rows([source])
        self.assertEqual(retained[0]["product_name"], "Product")
        self.assertEqual(retained[0]["product_description"], "Café™  tools\nsecond line\nthird line")
        self.assertEqual(source["product_description"], "  Café™  tools\r\nsecond line\rthird line  ")
        self.assertEqual(report["normalized_retained_values_by_field"],
                         {"product_description": 1, "product_name": 1})

    def test_exclusions_are_explicit_not_keyword_based(self):
        rows = [self.row(1, description=" NEED PRODUCT DESCRIPTION "),
                self.row(2, description="Useful but damaged \ufffd text"),
                self.row(3, name="Signature Services", vendor="QLIKTECH INC"),
                self.row(4, name="Hyperion BI Analysis Fee", vendor="KURT STECKEL"),
                self.row(5, name="Premium Support Software Suite"),
                self.row(6, name="Signature Services", vendor="Different Vendor"),
                self.row(7, description="   ")]
        retained, report = clean.clean_rows(rows)
        self.assertEqual([row["source_record_number"] for row in retained], [5, 6])
        self.assertEqual(report["exclusion_reason_counts"], {
            "missing_description": 1, "placeholder_description": 1,
            "replacement_character_in_description": 1,
            "reviewed_consulting_support_package": 1, "reviewed_fee_entry": 1})
        self.assertEqual(report["input_records"], report["retained_records"] + report["excluded_records"])
        self.assertNotIn("encoding_flag", retained[0])

    def test_multicategory_grouping_retains_every_membership_and_description(self):
        rows = [self.row(1, name="Same Product", vendor="Vendor", category="A", subcategory="X"),
                self.row(2, name=" same  PRODUCT ", vendor="VENDOR", category="B", subcategory="Y",
                         description="Different product description"),
                self.row(3, name="Same Product", vendor="Other Vendor", category="A", subcategory="X")]
        retained, report = clean.clean_rows(rows)
        self.assertEqual(len(retained), 3)
        self.assertEqual(retained[0]["product_group_id"], retained[1]["product_group_id"])
        self.assertNotEqual(retained[0]["product_group_id"], retained[2]["product_group_id"])
        group = report["repeated_product_groups"][0]
        self.assertEqual(group["source_record_numbers"], [1, 2])
        self.assertEqual(group["memberships"], [{"category": "A", "subcategory": "X"},
                                               {"category": "B", "subcategory": "Y"}])
        self.assertEqual(retained[1]["product_description"], "Different product description")
        reordered, _ = clean.clean_rows(list(reversed(rows)))
        self.assertEqual({r["source_record_number"]: r["product_group_id"] for r in retained},
                         {r["source_record_number"]: r["product_group_id"] for r in reordered})

    def test_equal_descriptions_do_not_merge_different_products(self):
        retained, report = clean.clean_rows([self.row(1, name="One"), self.row(2, name="Two")])
        self.assertNotEqual(retained[0]["product_group_id"], retained[1]["product_group_id"])
        self.assertEqual(report["repeated_product_groups"], [])

    def test_missing_identity_or_taxonomy_is_rejected(self):
        for field in clean.FIELDS[:-1]:
            row = self.row(1)
            row[field] = " "
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, f"record 1: missing {field}"):
                clean.clean_rows([row])

    def test_all_path_collisions_fail_before_writing(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            source, output, report = (folder / name for name in ("input.csv", "cleaned.csv", "report.json"))
            self.write_source(source, [self.row(1)])
            original = source.read_bytes()
            for paths in ((source, source, report), (source, output, source), (source, output, output)):
                with self.subTest(paths=paths), self.assertRaisesRegex(ValueError, "different files"):
                    clean.write_outputs(*paths)
                self.assertEqual(source.read_bytes(), original)
            os.link(source, output)
            with self.assertRaisesRegex(ValueError, "different files"):
                clean.write_outputs(source, output, report)
            self.assertEqual(source.read_bytes(), original)
            output.unlink()
            output.write_text("existing generated output", encoding="utf-8")
            os.link(output, report)
            with self.assertRaisesRegex(ValueError, "different files"):
                clean.write_outputs(source, output, report)
            self.assertEqual(output.read_text(), "existing generated output")

    def test_repeated_generation_is_identical_and_preserves_source_records(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            source, output, report_path = (folder / name for name in ("input.csv", "cleaned.csv", "report.json"))
            self.write_source(source, [self.row(1, description="first\r\nsecond"),
                                       self.row(2, description="NEED PRODUCT DESCRIPTION")])
            original = source.read_bytes()
            report = clean.write_outputs(source, output, report_path)
            first_outputs = (output.read_bytes(), report_path.read_bytes())
            clean.write_outputs(source, output, report_path)
            self.assertEqual(first_outputs, (output.read_bytes(), report_path.read_bytes()))
            self.assertEqual(source.read_bytes(), original)
            self.assertEqual(report["source"]["sha256"], hashlib.sha256(original).hexdigest())
            self.assertEqual(report["output"]["sha256"], hashlib.sha256(output.read_bytes()).hexdigest())
            self.assertEqual(report, json.loads(report_path.read_text()))
            with output.open(encoding="utf-8", newline="") as stream:
                reader = csv.DictReader(stream)
                self.assertEqual(reader.fieldnames, list(clean.OUTPUT_FIELDS))
                rows = list(reader)
            self.assertEqual(rows[0]["source_record_number"], "1")
            self.assertEqual(rows[0]["product_description"], "first\nsecond")
            self.assertEqual(report["excluded_source_records"][0]["source_record_number"], 2)

    def test_malformed_csv_does_not_replace_existing_outputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            source, output, report = (folder / name for name in ("input.csv", "cleaned.csv", "report.json"))
            source.write_text(",".join(clean.FIELDS) + "\nonly,two\n", encoding="utf-8")
            output.write_text("previous cleaned view", encoding="utf-8")
            report.write_text("previous report", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "logical source record 1"):
                clean.write_outputs(source, output, report)
            self.assertEqual(output.read_text(), "previous cleaned view")
            self.assertEqual(report.read_text(), "previous report")

    def test_pinned_dataset_counts_and_exclusion_references(self):
        rows = clean.load_rows(clean.INPUT)
        retained, report = clean.clean_rows(rows)
        self.assertEqual((len(rows), len(retained), report["excluded_records"]), (1494, 1438, 56))
        self.assertEqual(report["exclusion_reason_counts"], {
            "placeholder_description": 2, "replacement_character_in_description": 52,
            "reviewed_consulting_support_package": 1, "reviewed_fee_entry": 1})
        excluded_ids = {row["source_record_number"] for row in report["excluded_source_records"]}
        self.assertTrue({3, 9, 717, 723}.issubset(excluded_ids))
        self.assertEqual(excluded_ids | {row["source_record_number"] for row in retained}, set(range(1, 1495)))
        self.assertFalse(any("\ufffd" in row["product_description"] for row in retained))
        self.assertEqual(sum(report["category_record_counts"].values()), 1438)
        snowflake = next(group for group in report["repeated_product_groups"]
                         if group["source_record_numbers"] == [1177, 1178, 1179])
        self.assertEqual(len(snowflake["memberships"]), 3)
        self.assertEqual({row["source_record_number"] for row in retained
                          if row["product_group_id"] == snowflake["product_group_id"]}, {1177, 1178, 1179})


if __name__ == "__main__":
    unittest.main()
