import unittest

from app.pipeline.risk import RiskFacts, assess


class RiskRubricTest(unittest.TestCase):
    def check(self, facts, tier, flagged, flag_reasons=None):
        assessment = assess(RiskFacts(*facts))
        self.assertEqual(assessment.tier, tier)
        self.assertEqual(assessment.investigation_flag, flagged)
        if flag_reasons is not None:
            self.assertEqual(assessment.flag_reasons, flag_reasons)
        return assessment

    def test_high_unapproved_and_trains_on_customer_data(self):
        assessment = self.check(("unapproved", "yes", "no"), "High", True,
                                ["high_tier", "unapproved_tool", "customer_data_training_permitted",
                                 "admin_controls_absent"])
        self.assertEqual(assessment.reason_codes, ["unapproved_tool", "customer_data_training_permitted"])

    def test_high_does_not_need_the_admin_fact(self):
        self.check(("unapproved", "yes", "unknown"), "High", True)

    def test_lower_needs_all_three_safe_facts(self):
        assessment = self.check(("approved", "no", "yes"), "Lower", False, [])
        self.assertEqual(assessment.unknown_facts, [])
        self.check(("approved", "no", "unknown"), "Medium", False)
        self.check(("approved", "unknown", "yes"), "Medium", False)

    def test_medium_for_other_cases_with_a_usable_fact(self):
        assessment = self.check(("unapproved", "unknown", "unknown"), "Medium", True, ["unapproved_tool"])
        self.assertEqual(assessment.reason_codes, ["other_classifiable_case", "unapproved_tool"])
        self.assertEqual(assessment.unknown_facts, ["training_on_customer_data", "admin_controls_available"])
        self.check(("unknown", "unknown", "no"), "Medium", True, ["admin_controls_absent"])
        self.check(("approved", "no", "no"), "Medium", True, ["admin_controls_absent"])

    def test_all_unknown_is_unresolved_not_medium(self):
        assessment = self.check(("unknown", "unknown", "unknown"), "unresolved", True,
                                ["insufficient_evidence_for_tier"])
        self.assertEqual(assessment.reason_codes, ["all_rubric_facts_unknown"])

    def test_unknown_is_never_treated_as_false(self):
        # Unapproved with unknown training must not be called High (or Lower).
        self.check(("unapproved", "unknown", "yes"), "Medium", True)

    def test_conditional_training_counts_as_unknown(self):
        self.check(("approved", "conditional", "yes"), "Medium", False)
        self.check(("unknown", "conditional", "unknown"), "unresolved", True)

    def test_invalid_fact_values_are_rejected(self):
        with self.assertRaises(ValueError):
            assess(RiskFacts("maybe", "no", "yes"))

    def test_synthetic_fixture_tools(self):
        # Facts from scenario_tool_metadata.csv and the tiers Katy's fixture expects.
        cases = {
            "ChatGPT": (("approved", "no", "yes"), "Lower", False),
            "Cursor": (("unapproved", "unknown", "unknown"), "Medium", True),
            "MeetOscar": (("unapproved", "yes", "no"), "High", True),
            "Magic Inspector": (("approved", "no", "yes"), "Lower", False),
            "Amazon Comprehend": (("approved", "unknown", "yes"), "Medium", False),
            "Playbooks": (("unapproved", "yes", "no"), "High", True),
            "Open Canvas AI": (("unknown", "unknown", "unknown"), "unresolved", True),
        }
        for tool, (facts, tier, flagged) in cases.items():
            with self.subTest(tool=tool):
                self.check(facts, tier, flagged)


if __name__ == "__main__":
    unittest.main()
