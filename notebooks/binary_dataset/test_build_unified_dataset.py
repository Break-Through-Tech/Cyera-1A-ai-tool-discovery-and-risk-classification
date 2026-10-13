import csv
import hashlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from build_unified_dataset import (CUTOFF, TOOLBUZZ_FIELDS, build_dataset, read_toolbuzz,
                                   sha, write_dataset)


def csv_bytes(fields, rows):
    stream = io.StringIO(newline="")
    writer = csv.writer(stream)
    writer.writerow(fields)
    writer.writerows(rows)
    return stream.getvalue().encode("utf-8")


def enterprise_inputs():
    text = "Useful scheduling software."
    digest = sha(text.encode())
    descriptions = [{"product_description": text, "description_sha256": digest, "annotation_id": "a1",
                     "ai_status": "non_ai", "evidence_strength": "supported", "trusted_eligible": True,
                     "provenance": {"label_export": "pinned.json"}},
                    {"product_description": "weak", "description_sha256": sha(b"weak"), "annotation_id": "a2",
                     "ai_status": "ai", "evidence_strength": "weak", "trusted_eligible": False,
                     "provenance": {}}]
    fields = ["source_record_number", "product_group_id", "product_name", "vendor_name", "taxonomy_category",
              "taxonomy_sub_category", "product_description", "description_sha256", "ai_status", "trusted_eligible"]
    rows = [["1", "g1", "One", "Vendor", "Cat A", "Sub", text, digest, "non_ai", "True"],
            ["2", "g1", "One", "Vendor", "Cat B", "Sub2", text, digest, "non_ai", "True"],
            ["3", "g2", "Weak", "Vendor", "Cat", "", "weak", sha(b"weak"), "ai", "False"]]
    desc_bytes = json.dumps(descriptions).encode()
    record_bytes = csv_bytes(fields, rows)
    manifest = json.dumps({"source_cutoff": CUTOFF, "finalized_rows": 3, "weak_or_forced_rows": 1,
                          "artifacts": {"enterprise_descriptions.json": sha(desc_bytes),
                                       "enterprise_records.csv": sha(record_bytes)}}).encode()
    return desc_bytes, record_bytes, manifest


def toolbuzz_row(name, desc, category="Tools"):
    values = {key: "" for key in TOOLBUZZ_FIELDS}
    values.update({"Name": name, "Link": f"https://example.test/{name}", "Category": category,
                   "Short Description": desc})
    return [values[key] for key in TOOLBUZZ_FIELDS]


class UnifiedDatasetTests(unittest.TestCase):
    def test_build_preserves_toolbuzz_candidates_and_enterprise_memberships(self):
        raw = csv_bytes(TOOLBUZZ_FIELDS, [toolbuzz_row("one", " AI writing "),
                                          toolbuzz_row("two", "AI writing"),
                                          toolbuzz_row("blank", " \t")])
        descriptions, records, manifest = enterprise_inputs()
        result = build_dataset(raw, descriptions, records, manifest)
        examples = result["examples"]
        self.assertEqual(len(examples), 3)
        self.assertEqual([x["source"] for x in examples], ["enterprise", "aitoolbuzz", "aitoolbuzz"])
        ent = examples[0]
        self.assertEqual(ent["label"], "non_ai")
        self.assertEqual(ent["source_record_ids"], ["enterprise-row:1", "enterprise-row:2"])
        self.assertEqual(len([x for x in examples if x["source"] == "enterprise"]), 1)
        self.assertEqual([x["description_text"] for x in examples[1:]], [" AI writing ", "AI writing"])
        self.assertEqual(examples[1]["label"], "ai")
        self.assertNotEqual(examples[1]["description_sha256"], examples[2]["description_sha256"])
        self.assertEqual(result["summary"]["excluded_by_source_and_reason"]["aitoolbuzz:empty_description"], 1)
        self.assertEqual(result["exclusions"][0]["source_record_id"], "aitoolbuzz-row:00003")
        self.assertEqual(result["summary"]["feature_allowlist"], ["description_text"])

    def test_non_pinned_cutoff_is_rejected(self):
        descriptions, records, manifest = enterprise_inputs()
        with self.assertRaisesRegex(ValueError, "pinned"):
            build_dataset(b"", descriptions, records, manifest, cutoff="HEAD")

    def test_csv_rejects_wrong_schema_and_width(self):
        with self.assertRaisesRegex(ValueError, "schema mismatch"):
            read_toolbuzz(csv_bytes(("Name",), []))
        malformed = (",".join(TOOLBUZZ_FIELDS) + "\n" + "too,few\n").encode()
        with self.assertRaisesRegex(ValueError, "row width mismatch"):
            read_toolbuzz(malformed)

    def test_malformed_csv_and_enterprise_hashes_fail_closed(self):
        with self.assertRaisesRegex(ValueError, "invalid AIToolBuzz CSV"):
            read_toolbuzz(b'\"unterminated')
        raw = csv_bytes(TOOLBUZZ_FIELDS, [toolbuzz_row("x", "description")])
        descriptions, records, manifest = enterprise_inputs()
        with self.assertRaisesRegex(ValueError, "checksum mismatch"):
            build_dataset(raw, descriptions + b" ", records, manifest)
        truncated_records = csv_bytes(["source_record_number", "product_group_id", "product_name", "vendor_name",
                                        "taxonomy_category", "taxonomy_sub_category", "product_description",
                                        "description_sha256", "ai_status", "trusted_eligible"],
                                       [["1", "g1", "One", "Vendor", "Cat A", "Sub", "Useful scheduling software.",
                                         sha(b"Useful scheduling software."), "non_ai", "True"],
                                        ["3", "g2", "Weak", "Vendor", "Cat", "", "weak", sha(b"weak"),
                                         "ai", "False"]])
        tampered_manifest = json.dumps({"source_cutoff": CUTOFF, "finalized_rows": 3, "weak_or_forced_rows": 1,
                                        "artifacts": {"enterprise_descriptions.json": sha(descriptions),
                                                     "enterprise_records.csv": sha(truncated_records)}}).encode()
        with self.assertRaisesRegex(ValueError, "membership count mismatch"):
            build_dataset(raw, descriptions, truncated_records, tampered_manifest)

    def test_write_refuses_existing_output_and_build_is_reproducible(self):
        with tempfile.TemporaryDirectory() as tmp:
            # Exercise deterministic data construction from byte-identical inputs.
            raw = csv_bytes(TOOLBUZZ_FIELDS, [toolbuzz_row("x", "description")])
            descriptions, records, manifest = enterprise_inputs()
            left = build_dataset(raw, descriptions, records, manifest)
            right = build_dataset(raw, descriptions, records, manifest)
            self.assertEqual(left, right)
            out = Path(tmp) / "exists"
            out.mkdir()
            with self.assertRaises(FileExistsError):
                write_dataset(out)
            self.assertEqual(list(out.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
