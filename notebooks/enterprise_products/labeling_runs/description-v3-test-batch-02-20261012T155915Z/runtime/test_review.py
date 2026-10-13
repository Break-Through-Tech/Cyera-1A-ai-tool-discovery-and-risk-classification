import copy
import html.parser
import json
import pathlib
import unittest

import render_review

RUN = pathlib.Path(__file__).resolve().parent.parent


class TextCapture(html.parser.HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.capture = False
        self.description = []
        self.provenance = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "div" and "description" in attrs.get("class", "").split():
            self.capture = True
        if tag == "span" and "provenance" in attrs.get("class", "").split():
            self.provenance.append([])

    def handle_endtag(self, tag):
        if tag == "div" and self.capture:
            self.capture = False

    def handle_data(self, data):
        if self.capture:
            self.description.append(data)
        if self.provenance and not self.capture:
            self.provenance[-1].append(data)


class ReviewRendererTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = json.loads((RUN / "REVIEW_DATA.json").read_text(encoding="utf-8"))

    def test_real_batch_counts_order_and_source_row_coverage(self):
        data = self.data
        self.assertEqual(data["counts"], render_review.EXPECTED)
        self.assertEqual(len(data["cases"]), 20)
        self.assertEqual(sum(len(c["source_rows"]) for c in data["cases"]), 31)
        output = render_review.render(data)
        positions = [output.index(f'data-annotation-id="{c["annotation_id"]}"') for c in data["cases"]]
        self.assertEqual(positions, sorted(positions))
        self.assertEqual(output.count('class="case"'), 20)
        self.assertIn('<h2>Record 1 · Cloud Secure Agent</h2>', output)
        self.assertIn('.quote-audit p{white-space:pre-wrap}', output)
        self.assertEqual(sum(output.count(f'<li><span>Record {row["source_record_number"]}</span>')
                             for c in data["cases"] for row in c["source_rows"]), 31)
        ea = next(c for c in data["cases"] if len(c["source_rows"]) == 7)
        for row in ea["source_rows"]:
            self.assertIn(f'Record {row["source_record_number"]}', output)

    def test_escaping_round_trips_synthetic_description_and_name(self):
        data = copy.deepcopy(self.data)
        data["cases"] = data["cases"][:1]
        case = data["cases"][0]
        case["description"] = '<script>& "safe"\nnext\u00a0line'
        case["source_rows"][0]["product_name"] = '<script>name</script>'
        output = render_review.render(data)
        self.assertNotIn('<script>& "safe"', output)
        parser = TextCapture()
        parser.feed(output)
        self.assertEqual("".join(parser.description), case["description"])
        self.assertIn("&lt;script&gt;name&lt;/script&gt;", output)
        self.assertNotIn('<script>name</script>', output)

    def test_original_descriptions_round_trip_unicode_nbsp_and_newlines(self):
        for case in self.data["cases"]:
            parser = TextCapture()
            parser.feed(render_review.render({**self.data, "cases": [case]}))
            self.assertEqual("".join(parser.description), case["description"])

    def test_binary_and_subtype_flags_and_pool_eligibility_are_separate(self):
        data = copy.deepcopy(self.data)
        ai = next(c for c in data["cases"] if c["final"]["ai_status"] == "ai")
        ai["final"]["ai_type_evidence_strength"] = "weak"
        ai["final"]["ai_type_forced_decision"] = True
        ai_html = render_review.render({**data, "cases": [ai]})
        self.assertIn('data-uncertain="true"', ai_html)
        self.assertIn('data-negative="false"', ai_html)
        self.assertIn("Binary AI is supported; subtype excluded", ai_html)
        self.assertIn("Weak subtype", ai_html)
        self.assertNotIn("Excluded from trusted binary and negative pools", ai_html)

        negative = next(c for c in self.data["cases"] if c["final"]["ai_status"] == "non_ai" and c["final"]["evidence_strength"] == "supported")
        negative_html = render_review.render({**self.data, "cases": [negative]})
        self.assertIn('data-negative="true"', negative_html)
        self.assertIn("Eligible for the supported-negative pool", negative_html)
        weak = copy.deepcopy(negative)
        weak["final"]["evidence_strength"] = "weak"
        weak_html = render_review.render({**self.data, "cases": [weak]})
        self.assertIn('data-uncertain="true"', weak_html)
        self.assertIn('data-negative="false"', weak_html)
        self.assertIn("Excluded from trusted binary and negative pools", weak_html)


if __name__ == "__main__":
    unittest.main()
