import csv
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

import label_v3 as v3


class LabelV3Tests(unittest.TestCase):
    def fixture(self, root, descriptions=None, select=True, reconciliation_prompt=False):
        descriptions = descriptions or ["Useful reporting functions", "Useful reporting functions", "Generates text with a neural network"]
        raw = root / "raw.csv"
        raw.write_text("raw snapshot\n", encoding="utf-8")
        cleaned = root / "cleaned.csv"
        rows = []
        for i, text in enumerate(descriptions, 1):
            rows.append({"source_record_number": str(i), "product_group_id": f"g{1 if i in (1, 3) else i}",
                         "product_name": f"Product {i}", "vendor_name": f"Vendor {i}",
                         "taxonomy_category": "Software", "taxonomy_sub_category": "Tools",
                         "product_description": text})
        with cleaned.open("w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=v3.RECORD_FIELDS, lineterminator="\n")
            writer.writeheader(); writer.writerows(rows)
        report = root / "report.json"
        report.write_text(json.dumps({"source": {"sha256": v3.file_hash(raw)},
                                      "output": {"sha256": v3.file_hash(cleaned)},
                                      "retained_records": len(rows),
                                      "retained_product_groups": len({r["product_group_id"] for r in rows}),
                                      "input_records": len(rows), "excluded_records": 0}), encoding="utf-8")
        rubric, p1, p2 = (root / name for name in ("rubric.md", "prompt-labeler.md", "prompt-blind.md"))
        rubric.write_text("rubric", encoding="utf-8")
        p1.write_text("label prompt", encoding="utf-8")
        p2.write_text("blind prompt", encoding="utf-8")
        run = root / "run"
        inputs = {"raw": raw, "cleaned": cleaned, "cleaning_report": report,
                  "rubric": rubric, "prompt_labeler": p1, "prompt_blind": p2}
        if reconciliation_prompt:
            p3 = root / "prompt-reconciliation.md"
            p3.write_text("verifier reconciliation prompt", encoding="utf-8")
            inputs["prompt_reconciliation"] = p3
        v3.freeze_run(run, inputs, expected=None)
        packets, joins = v3.prepare_packets(run)
        if select:
            v3.select_descriptions(run, [{"annotation_id": p["annotation_id"],
                                          "source_record_references": p["source_record_references"]}
                                         for p in packets], expected=None)
        return run, packets, joins

    def result(self, packet, status="non_ai", strength="supported", subtype=None, subtype_strength=None):
        text = packet["description"]
        ai = status == "ai"
        quote = text[:min(len(text), 12)]
        result = {"annotation_id": packet["annotation_id"], "description_sha256": packet["description_sha256"],
                  "ai_status": status, "ai_type": subtype if ai else None,
                  "evidence_strength": strength, "forced_decision": strength == "weak",
                  "ai_type_evidence_strength": (subtype_strength or "supported") if ai else None,
                  "ai_type_forced_decision": ((subtype_strength or "supported") == "weak") if ai else None,
                  "rationale": "Describes concrete functionality.", "ai_type_rationale": "The described offering depends on the stated AI capability." if ai else None,
                  "evidence_spans": [quote], "ai_type_evidence_spans": [quote] if ai else None}
        return result

    def receipts_and_save(self, run, packets, stage, records):
        prompt = hashlib.sha256(("label prompt" if stage == "labeler" else "blind prompt").encode()).hexdigest()
        v3.assign_stage(run, stage, [p["annotation_id"] for p in packets], prompt, "test-model", "batch-1")
        for record in records:
            v3.save_checkpoint(run, stage, record["annotation_id"], record)

    def test_freeze_dedup_packets_exact_text_and_join_propagation(self):
        with tempfile.TemporaryDirectory() as tmp:
            run, packets, joins = self.fixture(Path(tmp))
            self.assertEqual(len(packets), 2)
            repeated_text_join = next(j for j in joins if len(j["rows"]) == 2)
            self.assertEqual({r["product_group_id"] for r in repeated_text_join["rows"]}, {"g1", "g2"})
            repeated_packet = next(p for p in packets if p["annotation_id"] == repeated_text_join["annotation_id"])
            self.assertEqual(repeated_packet["description"], repeated_text_join["rows"][0]["product_description"])
            self.assertEqual(len({j["annotation_id"] for j in joins}), 2)
            self.assertEqual(len({p["description"] for p in packets}), 2)
            self.assertNotIn("product_name", packets[0])
            self.assertEqual({k: v3._json(run / "manifest.json")["counts"][k]
                              for k in ("records", "product_groups", "distinct_descriptions")},
                             {"records": 3, "product_groups": 2, "distinct_descriptions": 2})

    def test_explicit_selection_requires_exact_reference_groups(self):
        with tempfile.TemporaryDirectory() as tmp:
            run, packets, _ = self.fixture(Path(tmp))
            with self.assertRaisesRegex(ValueError, "immutable"):
                v3.select_descriptions(run, [], expected=None)
            with tempfile.TemporaryDirectory() as tmp2:
                run2, packets2, _ = self.fixture(Path(tmp2), select=False)
                # An incomplete group cannot be selected by citing only one duplicate row.
                repeated = next(p for p in packets2 if len(p["source_record_references"]) == 2)
                other = [p for p in packets2 if p is not repeated][0]
                with self.assertRaisesRegex(ValueError, "exact-text description group"):
                    v3.select_descriptions(run2, [{"annotation_id": repeated["annotation_id"],
                                                   "source_record_references": repeated["source_record_references"][:1]},
                                                  {"annotation_id": other["annotation_id"],
                                                   "source_record_references": other["source_record_references"]}], expected=None)

    def test_freeze_checks_report_hash_count_and_new_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); run, _, _ = self.fixture(root)
            with self.assertRaises(FileExistsError):
                v3.freeze_run(run, expected=None)
            (run / "inputs/cleaned.csv").write_text("tampered", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "input tampered"):
                v3.prepare_packets(run)

    def test_validate_wrong_hash_quotes_duplicate_missing_extra_and_flags(self):
        packet = {"annotation_id": "a", "description_sha256": "d", "description": "Exact text"}
        good = self.result(packet)
        for mutate, message in ((lambda x: x.update(description_sha256="wrong"), "hash mismatch"),
                                (lambda x: x.update(evidence_spans=["paraphrase"]), "quotation"),
                                (lambda x: x.update(evidence_spans=["   "]), "quotation"),
                                (lambda x: x.update(forced_decision=1), "JSON boolean"),
                                (lambda x: x.update(evidence_strength="weak"), "inconsistent")):
            bad = dict(good); mutate(bad)
            with self.subTest(message=message), self.assertRaisesRegex(ValueError, message):
                v3.validate_handoff([bad], [packet], ["a"], "labeler")
        with self.assertRaisesRegex(ValueError, "coverage mismatch"):
            v3.validate_handoff([], [packet], ["a"], "labeler")
        with self.assertRaisesRegex(ValueError, "coverage mismatch"):
            v3.validate_handoff([good, dict(good, annotation_id="extra")], [packet], ["a"], "labeler")
        with self.assertRaisesRegex(ValueError, "duplicate"):
            v3.validate_handoff([good, good], [packet], ["a"], "labeler")

    def test_subtype_null_enums_booleans_and_uncertainty_independent(self):
        packet = {"annotation_id": "a", "description_sha256": "d", "description": "AI neural capability"}
        good = self.result(packet, "ai", subtype="ai_native")
        for patch, error in (({"ai_type": None}, "subtype"), ({"ai_type": "other"}, "subtype"),
                             ({"ai_type_forced_decision": 0}, "subtype weak/forced"),
                             ({"ai_type_evidence_strength": "weak"}, "subtype weak/forced")):
            with self.subTest(error=error), self.assertRaisesRegex(ValueError, error):
                v3.validate_handoff([dict(good, **patch)], [packet], ["a"], "labeler")
        weak_subtype = dict(good, ai_type_evidence_strength="weak", ai_type_forced_decision=True)
        self.assertEqual(v3.validate_handoff([weak_subtype], [packet], ["a"], "labeler"), [weak_subtype])
        bad_negative = self.result(packet)
        bad_negative["ai_type"] = "ai_native"
        with self.assertRaisesRegex(ValueError, "non_ai subtype"):
            v3.validate_handoff([bad_negative], [packet], ["a"], "labeler")

    def test_routing_for_conflict_weak_forced_and_subtype_uncertainty(self):
        p = {"annotation_id": "a", "description_sha256": "d", "description": "plain evidence"}
        a, b = self.result(p), self.result(p)
        self.assertEqual(v3.compare([a], [b]), [])
        b["ai_status"] = "ai"; b["ai_type"] = "ai_enabled"; b["ai_type_evidence_strength"] = "supported"; b["ai_type_forced_decision"] = False; b["ai_type_rationale"] = "Includes AI feature."; b["ai_type_evidence_spans"] = ["plain evidence"]
        self.assertEqual(v3.compare([a], [b]), ["a"])
        b = self.result(p); a["evidence_strength"] = "weak"; a["forced_decision"] = True
        self.assertEqual(v3.compare([a], [b]), ["a"])
        a = self.result(p, "ai", subtype="ai_native", subtype_strength="weak")
        b = self.result(p, "ai", subtype="ai_native")
        self.assertEqual(v3.compare([a], [b]), ["a"])

    def test_reconciliation_explicit_response_and_finalization_exports(self):
        with tempfile.TemporaryDirectory() as tmp:
            run, packets, _ = self.fixture(Path(tmp))
            label = [self.result(p, "non_ai") for p in packets]
            blind = [self.result(p, "ai", subtype="ai_enabled") if i == 0 else self.result(p, "non_ai") for i, p in enumerate(packets)]
            self.receipts_and_save(run, packets, "labeler", label)
            self.receipts_and_save(run, packets, "blind", blind)
            route = v3.compare(label, blind)
            reconcile = [dict(self.result(packets[0], "non_ai"), conflict_response="Reviewed both proposals; conflict addressed from original description.")]
            v3.assign_stage(run, "reconciliation", route, hashlib.sha256(b"blind prompt").hexdigest(), "test-model", "batch-1")
            v3.save_checkpoint(run, "reconciliation", route[0], reconcile[0])
            report = v3.finalize_run(run, route)
            self.assertEqual(report["selected_records"], 3)
            self.assertIn("selected calibration only", report["coverage_claim"])
            self.assertTrue((run / "review_ledger.json").exists())
            with (run / "non_ai_candidates.csv").open(encoding="utf-8") as stream:
                self.assertEqual(len(list(csv.DictReader(stream))), 3)
            with self.assertRaisesRegex(ValueError, "immutable"):
                v3.finalize_run(run, route)
            (run / "record_labels.json").write_text("tampered", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "export tampered"):
                v3.finalize_run(run, route)

    def test_supported_negative_export_excludes_weak_negative(self):
        with tempfile.TemporaryDirectory() as tmp:
            run, packets, _ = self.fixture(Path(tmp))
            weak_id = next(p["annotation_id"] for p in packets if len(p["source_record_references"]) == 2)
            label = [self.result(p, "non_ai", "weak") if p["annotation_id"] == weak_id else self.result(p, "non_ai") for p in packets]
            blind = [dict(x) for x in label]
            self.receipts_and_save(run, packets, "labeler", label)
            self.receipts_and_save(run, packets, "blind", blind)
            route = v3.compare(label, blind)
            v3.assign_stage(run, "reconciliation", route, hashlib.sha256(b"blind prompt").hexdigest(), "test-model", "batch-1")
            for aid in route:
                result = next(r for r in label if r["annotation_id"] == aid)
                v3.save_checkpoint(run, "reconciliation", aid,
                                   dict(result, conflict_response="Rechecked the original description and retained the weak judgment."))
            report = v3.finalize_run(run, route)
            self.assertEqual(report["binary_weak_count"], 1)
            with (run / "non_ai_candidates.csv").open(encoding="utf-8") as stream:
                candidates = list(csv.DictReader(stream))
            self.assertEqual(len(candidates), 1)
            self.assertEqual(candidates[0]["evidence_strength"], "supported")

    def test_weak_negative_excluded_and_resume_checkpoint_tamper_detected(self):
        with tempfile.TemporaryDirectory() as tmp:
            run, packets, _ = self.fixture(Path(tmp))
            label = [self.result(p, "non_ai", "weak") if i == 0 else self.result(p, "non_ai") for i, p in enumerate(packets)]
            blind = [dict(x) for x in label]
            self.receipts_and_save(run, packets, "labeler", label)
            self.receipts_and_save(run, packets, "blind", blind)
            with self.assertRaisesRegex(ValueError, "checkpoint tampered"):
                path = next((run / "stages/labeler").glob("*.json")); path.write_text("{}", encoding="utf-8")
                v3.load_stage(run, "labeler")

    def test_prepare_packets_preserves_existing_pinned_packets(self):
        with tempfile.TemporaryDirectory() as tmp:
            run, packets, _ = self.fixture(Path(tmp))
            before = (run / "description_packets.json").read_bytes(), (run / "parent_join_map.json").read_bytes()
            try:
                returned, joins = v3.prepare_packets(run)
            except ValueError:
                return
            self.assertEqual(returned, packets)
            self.assertEqual((run / "description_packets.json").read_bytes(), before[0])
            self.assertEqual((run / "parent_join_map.json").read_bytes(), before[1])
            self.assertEqual({p["annotation_id"] for p in returned}, {p["annotation_id"] for p in packets})

    def test_parent_semantic_route_superset_finalizes_and_cannot_omit_required(self):
        with tempfile.TemporaryDirectory() as tmp:
            run, packets, _ = self.fixture(Path(tmp))
            label = [self.result(p, "non_ai") for p in packets]
            blind = [dict(item) for item in label]
            self.receipts_and_save(run, packets, "labeler", label)
            self.receipts_and_save(run, packets, "blind", blind)
            parent_route = [packets[0]["annotation_id"]]
            v3.assign_stage(run, "reconciliation", parent_route, hashlib.sha256(b"blind prompt").hexdigest(), "test-model", "batch-1")
            v3.save_checkpoint(run, "reconciliation", parent_route[0],
                               dict(label[0], conflict_response="Parent semantic concern reviewed against the original text."))
            with self.assertRaisesRegex(ValueError, "duplicate IDs"):
                v3.finalize_run(run, parent_route + parent_route)
            with self.assertRaisesRegex(ValueError, "unknown IDs"):
                v3.finalize_run(run, ["unknown-annotation"])
            report = v3.finalize_run(run, parent_route)
            self.assertEqual(report["required_reconciliation_count"], 0)
            self.assertEqual(report["parent_reconciliation_count"], 1)

        with tempfile.TemporaryDirectory() as tmp:
            run, packets, _ = self.fixture(Path(tmp))
            label = [self.result(p, "non_ai") for p in packets]
            blind = [dict(item) for item in label]
            blind[0] = dict(blind[0], ai_status="ai", ai_type="ai_enabled",
                            ai_type_evidence_strength="supported", ai_type_forced_decision=False,
                            ai_type_rationale="Text indicates AI.", ai_type_evidence_spans=[blind[0]["evidence_spans"][0]])
            self.receipts_and_save(run, packets, "labeler", label)
            self.receipts_and_save(run, packets, "blind", blind)
            required = v3.compare(label, blind)
            v3.assign_stage(run, "reconciliation", required, hashlib.sha256(b"blind prompt").hexdigest(), "test-model", "batch-1")
            for aid in required:
                item = next(x for x in label if x["annotation_id"] == aid)
                v3.save_checkpoint(run, "reconciliation", aid,
                                   dict(item, conflict_response="Required conflict addressed."))
            with self.assertRaisesRegex(ValueError, "cannot omit required"):
                v3.finalize_run(run, [])

    def test_load_stage_rejects_unregistered_checkpoint_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            run, packets, _ = self.fixture(Path(tmp))
            items = [self.result(p) for p in packets]
            ids = [p["annotation_id"] for p in packets]
            v3.assign_stage(run, "labeler", ids, hashlib.sha256(b"label prompt").hexdigest(), "test-model", "batch-1")
            folder = run / "stages/labeler"
            folder.mkdir(parents=True)
            for item in items:
                (folder / f"{item['annotation_id']}.json").write_text(json.dumps(item), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "unregistered checkpoint"):
                v3.load_stage(run, "labeler")

    def test_reconciliation_receipt_provenance_is_checked(self):
        with tempfile.TemporaryDirectory() as tmp:
            run, packets, _ = self.fixture(Path(tmp))
            label = [self.result(p) for p in packets]
            blind = [self.result(p, "ai", subtype="ai_enabled") if i == 0 else self.result(p) for i, p in enumerate(packets)]
            self.receipts_and_save(run, packets, "labeler", label)
            self.receipts_and_save(run, packets, "blind", blind)
            route = v3.compare(label, blind)
            v3.assign_stage(run, "reconciliation", route, hashlib.sha256(b"blind prompt").hexdigest(), "test-model", "batch-1")
            for aid in route:
                item = next(x for x in label if x["annotation_id"] == aid)
                v3.save_checkpoint(run, "reconciliation", aid, dict(item, conflict_response="Conflict addressed."))
            manifest_path = run / "manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["stages"]["reconciliation"]["model_id"] = ""
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "invalid reconciliation provenance"):
                v3.finalize_run(run, route)

    def test_stage_prompts_are_role_bound_on_assignment_and_finalization(self):
        with tempfile.TemporaryDirectory() as tmp:
            run, packets, _ = self.fixture(Path(tmp))
            ids = [p["annotation_id"] for p in packets]
            label_hash = hashlib.sha256(b"label prompt").hexdigest()
            blind_hash = hashlib.sha256(b"blind prompt").hexdigest()
            for stage, wrong_hash in (("labeler", blind_hash), ("blind", label_hash),
                                      ("reconciliation", label_hash)):
                with self.subTest(stage=stage), self.assertRaisesRegex(ValueError, "prompt"):
                    v3.assign_stage(run, stage, ids, wrong_hash, "test-model", "batch-1")
        for stage in ("labeler", "blind", "reconciliation"):
            with self.subTest(tampered_stage=stage), tempfile.TemporaryDirectory() as tmp:
                run, packets, _ = self.fixture(Path(tmp))
                items = [self.result(p) for p in packets]
                self.receipts_and_save(run, packets, "labeler", items)
                self.receipts_and_save(run, packets, "blind", items)
                route = [packets[0]["annotation_id"]]
                v3.assign_stage(run, "reconciliation", route, blind_hash, "test-model", "batch-1")
                v3.save_checkpoint(run, "reconciliation", route[0],
                                   dict(items[0], conflict_response="Parent concern checked against text."))
                manifest_path = run / "manifest.json"
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                manifest["stages"][stage]["prompt_sha256"] = blind_hash if stage == "labeler" else label_hash
                manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
                with self.assertRaisesRegex(ValueError, "provenance"):
                    v3.finalize_run(run, route)

    def test_distinct_frozen_verifier_followup_prompt_is_required_when_present(self):
        with tempfile.TemporaryDirectory() as tmp:
            run, packets, _ = self.fixture(Path(tmp), reconciliation_prompt=True)
            items = [self.result(p) for p in packets]
            self.receipts_and_save(run, packets, "labeler", items)
            self.receipts_and_save(run, packets, "blind", items)
            route = [packets[0]["annotation_id"]]
            with self.assertRaisesRegex(ValueError, "prompt"):
                v3.assign_stage(run, "reconciliation", route, hashlib.sha256(b"blind prompt").hexdigest(),
                                "test-model", "batch-1")
            v3.assign_stage(run, "reconciliation", route,
                            hashlib.sha256(b"verifier reconciliation prompt").hexdigest(), "test-model", "batch-1")
            v3.save_checkpoint(run, "reconciliation", route[0],
                               dict(items[0], conflict_response="Parent concern checked against text."))
            self.assertEqual(v3.finalize_run(run, route)["reconciliation_count"], 1)

    def test_wrong_reconciliation_routing_and_missing_stage_block(self):
        with tempfile.TemporaryDirectory() as tmp:
            run, packets, _ = self.fixture(Path(tmp))
            records = [self.result(p, "non_ai") for p in packets]
            self.receipts_and_save(run, packets, "labeler", records)
            self.receipts_and_save(run, packets, "blind", records)
            with self.assertRaisesRegex(ValueError, "invalid reconciliation provenance"):
                v3.finalize_run(run, [packets[0]["annotation_id"]])


if __name__ == "__main__":
    unittest.main()
