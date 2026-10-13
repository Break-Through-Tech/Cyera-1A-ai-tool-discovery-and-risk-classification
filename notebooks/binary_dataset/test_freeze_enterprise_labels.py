import hashlib
import tempfile
import unittest
from pathlib import Path

from freeze_enterprise_labels import CUTOFF, _label_valid, _same_annotation, build_freeze, write_freeze


class EnterpriseFreezeTests(unittest.TestCase):
    def test_cutoff_reconciles_finalized_exports_and_retained_source(self):
        frozen = build_freeze()
        summary = frozen["summary"]
        self.assertEqual(summary["source_cutoff"], CUTOFF)
        self.assertEqual((summary["source_records"], summary["source_distinct_descriptions"]), (1438, 1391))
        self.assertEqual((summary["finalized_distinct_descriptions"], summary["finalized_rows"], summary["finalized_groups"]), (560, 577, 571))
        self.assertEqual((summary["unlabelled_distinct_descriptions"], summary["unlabelled_rows"]), (831, 861))
        self.assertEqual(summary["duplicate_exports_not_recounters"], 0)
        self.assertEqual(sum(summary["supported_binary_counts"].values()), 456)
        for batch in frozen["provenance"]:
            stages = {x["stage"]: x["model_id"] for x in batch["model_rubric_provenance"] if "stage" in x}
            self.assertTrue({"labeler", "blind"} <= stages.keys(), batch["label_export"])
            self.assertTrue(all(stages.values()), batch["label_export"])
        self.assertEqual(summary["weak_or_forced_descriptions"], 104)
        self.assertEqual(summary["weak_or_forced_rows"], 106)
        self.assertEqual(len({r["source_record_number"] for r in frozen["record_rows"]}), 577)
        self.assertTrue(all(r["trusted_eligible"] == (r["evidence_strength"] == "supported") for r in frozen["record_rows"]))

    def test_conflicting_finalized_annotation_fields_are_not_deduplicated(self):
        first = {"annotation_id": "batch-a", "description_sha256": "a" * 64,
                 "ai_status": "ai", "ai_type": "ai_native", "evidence_strength": "supported",
                 "forced_decision": False, "ai_type_evidence_strength": "supported",
                 "ai_type_forced_decision": False, "rationale": "Binary rationale",
                 "ai_type_rationale": "Subtype rationale", "evidence_spans": ["AI function"],
                 "ai_type_evidence_spans": ["core AI function"], "product_description": "Exact text"}
        same = {**first, "annotation_id": "batch-b"}
        self.assertTrue(_same_annotation(first, same))
        for field, value in (("ai_type", "ai_enabled"), ("ai_type_evidence_strength", "weak"),
                             ("ai_type_forced_decision", True), ("rationale", "different binary rationale"),
                             ("ai_type_rationale", "different subtype rationale"),
                             ("evidence_spans", ["different quote"]),
                             ("ai_type_evidence_spans", ["different subtype quote"]),
                             ("ai_status", "non_ai"), ("evidence_strength", "weak"),
                             ("forced_decision", True), ("product_description", "different text")):
            with self.subTest(field=field):
                self.assertFalse(_same_annotation(first, {**same, field: value}))

    def test_binary_label_requires_exact_schema_and_valid_audit_fields(self):
        text = "Concrete reporting functionality"
        label = {"annotation_id": "a", "description_sha256": hashlib.sha256(text.encode()).hexdigest(),
                 "ai_status": "non_ai", "ai_type": None, "evidence_strength": "supported",
                 "forced_decision": False, "ai_type_evidence_strength": None,
                 "ai_type_forced_decision": None, "rationale": "Describes reporting functions.",
                 "ai_type_rationale": None, "evidence_spans": ["reporting functionality"],
                 "ai_type_evidence_spans": None, "product_description": text}
        _label_valid(label, text)
        bad_labels = [dict(label, evidence_spans=["not a quotation"]),
                      dict(label, description_sha256="0" * 64),
                      dict(label, forced_decision=True),
                      dict(label, rationale=42),
                      dict(label, ai_status=[]),
                      dict(label, evidence_strength=[]),
                      dict(label, annotation_id=42),
                      dict(label, evidence_spans=[42]),
                      dict(label, evidence_spans=["   "]),
                      dict(label, unexpected="extra"),
                      {k: v for k, v in label.items() if k != "rationale"},
                      {k: v for k, v in label.items() if k != "ai_type_evidence_spans"},
                      {k: v for k, v in label.items() if k != "ai_type"}]
        for bad in bad_labels:
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                _label_valid(bad, text)
        ai = {**label, "ai_status": "ai", "ai_type": "ai_native",
              "ai_type_evidence_strength": "supported", "ai_type_forced_decision": False,
              "ai_type_rationale": "AI is core functionality.",
              "evidence_spans": ["reporting functionality"],
              "ai_type_evidence_spans": ["reporting functionality"]}
        _label_valid(ai, text)
        with self.assertRaisesRegex(ValueError, "ai_type_rationale"):
            _label_valid(dict(ai, ai_type_rationale=42), text)
        with self.assertRaisesRegex(ValueError, "subtype metadata"):
            _label_valid(dict(ai, ai_type=[]), text)

    def test_generated_output_is_reproducible_and_never_overwritten(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "v1"
            first = write_freeze(out)
            second = write_freeze(Path(tmp) / "repeat")
            self.assertEqual(first["artifacts"], second["artifacts"])
            before = {p.name: p.read_bytes() for p in out.iterdir()}
            with self.assertRaises(FileExistsError):
                write_freeze(out)
            self.assertEqual(before, {p.name: p.read_bytes() for p in out.iterdir()})
            alias = Path(tmp) / "input-alias"
            alias.symlink_to(out / "manifest.json")
            with self.assertRaisesRegex(ValueError, "symlink"):
                write_freeze(alias)

    def test_weak_subtype_does_not_disqualify_supported_binary_label(self):
        text = "AI-assisted scheduling"
        label = {"annotation_id": "a", "description_sha256": hashlib.sha256(text.encode()).hexdigest(),
                 "ai_status": "ai", "evidence_strength": "supported", "forced_decision": False,
                 "rationale": "Text describes AI-assisted scheduling.",
                 "evidence_spans": ["AI-assisted scheduling"], "ai_type": "ai_enabled",
                 "ai_type_evidence_strength": "weak", "ai_type_forced_decision": True,
                 "ai_type_rationale": "Subtype remains uncertain.",
                 "ai_type_evidence_spans": ["AI-assisted scheduling"]}
        _label_valid(label, text)
        self.assertEqual(label["evidence_strength"], "supported")


if __name__ == "__main__":
    unittest.main()
