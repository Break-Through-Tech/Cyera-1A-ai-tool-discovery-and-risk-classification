import copy
import json
import unittest
from html.parser import HTMLParser

import render_review


class DescriptionText(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.capture = False
        self.text = []

    def handle_starttag(self, tag, attrs):
        if tag == 'div' and dict(attrs).get('class') == 'description':
            self.capture = True

    def handle_endtag(self, tag):
        if tag == 'div':
            self.capture = False

    def handle_data(self, data):
        if self.capture:
            self.text.append(data)


class ReviewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = json.loads(render_review.DATA_PATH.read_text())

    def test_actual_counts_flags_and_text(self):
        output = render_review.render(self.data)
        self.assertEqual(self.data['counts'], render_review.EXPECTED)
        self.assertEqual(output.count('class="case"'), 20)
        self.assertEqual(output.count('data-uncertain="true"'), 4)
        self.assertEqual(output.count('data-reconciled="true"'), 4)
        self.assertEqual(output.count('data-negative="true"'), 16)
        for case in self.data['cases']:
            parser = DescriptionText()
            parser.feed(render_review.render({**self.data, 'cases': [case]}))
            self.assertEqual(''.join(parser.text), case['description'])
            for row in case['source_rows']:
                self.assertIn(f'Record {row["source_record_number"]}', output)
        self.assertIn('Haiku 5.5 · labeler', output)
        self.assertIn('Luna 5.6 · blind verifier', output)
        self.assertIn('AI detection and subtype performance are not tested', output)

    def test_html_escaping_preserves_unicode_whitespace(self):
        data = copy.deepcopy(self.data)
        data['cases'] = data['cases'][:1]
        case = data['cases'][0]
        case['description'] = '<script>alert("x")</script>&\nnext\u00a0line'
        case['source_rows'][0]['product_name'] = '<script>name</script>'
        output = render_review.render(data)
        self.assertNotIn('<script>alert', output)
        self.assertNotIn('<script>name', output)
        parser = DescriptionText()
        parser.feed(output)
        self.assertEqual(''.join(parser.text), case['description'])

    def test_synthetic_subtype_weakness_does_not_weaken_binary(self):
        case = copy.deepcopy(self.data['cases'][0])
        case['final'].update(ai_status='ai', evidence_strength='supported', forced_decision=False,
                             ai_type='ai_native', ai_type_evidence_strength='weak',
                             ai_type_forced_decision=True, ai_type_rationale='Core dependency unclear.',
                             ai_type_evidence_spans=['synthetic'])
        output = render_review.render({**self.data, 'cases': [case]})
        self.assertIn('data-uncertain="true"', output)
        self.assertIn('data-negative="false"', output)
        self.assertIn('Binary AI is supported; subtype excluded', output)
        self.assertNotIn('Excluded from trusted binary and negative pools', output)


if __name__ == '__main__':
    unittest.main()
