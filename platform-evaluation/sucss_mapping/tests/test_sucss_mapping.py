"""Tests for the SUCSS spec parser and duty matcher.

Run from platform-evaluation/:  python -m unittest sucss_mapping/tests/test_sucss_mapping.py
Fixtures are synthetic pages that copy the SUCSS ViewSeries.aspx markup with invented wording,
so no SUCSS specification text is stored in the repository.
"""
import csv
import json
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
PKG = HERE.parent
sys.path.insert(0, str(PKG))

import matcher as mt  # noqa: E402
from parse_specs import class_records, clean, iso_date, parse_file, parse_series  # noqa: E402

FIX = HERE / 'fixtures'


class ParserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.path = FIX / 'series_synthetic.html'
        cls.page = cls.path.read_bytes().decode('utf-8')
        cls.rec = parse_file(cls.path, 9001)

    def test_header_and_dates(self):
        r = self.rec
        self.assertTrue(r['valid'])
        self.assertEqual(r['series_title'], 'Widget Calibration')
        self.assertEqual(r['promotional_line'], '7')
        self.assertEqual([c['class_code'] for c in r['classes']], ['9901', '9902'])
        self.assertEqual(r['classes'][0]['spec_effective_date_iso'], '2022-07-01')
        self.assertEqual(r['classes'][1]['spec_effective_date_iso'], '2011-03-01')
        self.assertIsNone(r['classes'][1]['exam_effective_date_iso'])

    def test_duties_and_spans_round_trip(self):
        lv = self.rec['levels']
        self.assertEqual([len(x['duties']) for x in lv], [3, 3])
        self.assertEqual(lv[1]['duties'][0]['text'], 'supervises widget calibrators & trains staff;')
        self.assertEqual(lv[1]['duties'][2]['text'], 'audits calibration ledgers.')  # inner tags stripped
        for level in lv:
            for d in level['duties'] + [level['level_description']]:
                s, e = d['span']
                self.assertEqual(clean(self.page[s:e]), d['text'])

    def test_maq_credentials_and_ksas(self):
        mq = self.rec['maq']
        self.assertEqual(mq[0]['class_code'], '9901')
        self.assertIn('One year of synthetic experience.', mq[0]['credentials']['text'])
        self.assertIn('Nested option & detail', mq[0]['credentials']['text'])
        self.assertEqual([k['text'] for k in mq[0]['ksas']], ['Precision (ability to read gauges)', 'Record keeping'])
        self.assertEqual(mq[1]['ksas'], [])          # "none" KSA marker
        s, e = mq[0]['credentials']['span']
        self.assertEqual(clean(self.page[s:e]), mq[0]['credentials']['text'])

    def test_class_records_flatten(self):
        recs = {c['class_code']: c for c in class_records(self.rec)}
        self.assertEqual(set(recs), {'9901', '9902'})
        self.assertEqual(recs['9901']['class_title'], 'Widget Calibrator I')
        self.assertEqual(len(recs['9902']['duties']), 3)
        self.assertEqual(len(recs['9901']['ksas']), 2)

    def test_invalid_page(self):
        r = parse_file(FIX / 'series_invalid_synthetic.html', 1)
        self.assertFalse(r['valid'])
        self.assertEqual(class_records(r), [])

    def test_parser_is_deterministic(self):
        a = json.dumps(parse_series(self.page, 9001), sort_keys=True)
        b = json.dumps(parse_series(self.page, 9001), sort_keys=True)
        self.assertEqual(a, b)

    def test_iso_date(self):
        self.assertEqual(iso_date('7/1/2022'), '2022-07-01')
        self.assertIsNone(iso_date(''))
        self.assertIsNone(iso_date('2022-07-01'))


OCC = [
    {'onetsoc_code': '99-0001.00', 'title': 'Widget Calibrators', 'description': 'Calibrate widgets and gauges.'},
    {'onetsoc_code': '99-0002.00', 'title': 'Ledger Clerks', 'description': 'Keep ledgers and records.'},
    {'onetsoc_code': '99-0003.00', 'title': 'Bakers', 'description': 'Bake bread.'},
]
TASKS = [
    {'onetsoc_code': '99-0001.00', 'task_id': 1, 'task': 'Calibrate widgets using precision gauges.'},
    {'onetsoc_code': '99-0001.00', 'task_id': 2, 'task': 'Train new calibrators.'},
    {'onetsoc_code': '99-0002.00', 'task_id': 3, 'task': 'Record readings in ledgers.'},
    {'onetsoc_code': '99-0003.00', 'task_id': 4, 'task': 'Mix dough and bake bread.'},
]
ALTS = [{'onetsoc_code': '99-0001.00', 'alternate_title': 'Widget Calibration Technician'}]


class MatcherTests(unittest.TestCase):
    def units(self):
        rec = parse_file(FIX / 'series_synthetic.html', 9001)
        c = [x for x in class_records(rec) if x['class_code'] == '9901'][0]
        return c['class_title'], [{'kind': 'duty', 'ref': f"D{d['index']}", 'text': d['text']} for d in c['duties']]

    def test_ranking_and_evidence(self):
        title, units = self.units()
        cands = mt.Matcher(OCC, TASKS, ALTS).score_class(title, units)
        self.assertEqual(cands[0]['onetsoc_code'], '99-0001.00')
        self.assertEqual(cands[0]['n_sucss_units'], 2)          # boilerplate duty dropped
        ev = cands[0]['evidence'][0]
        self.assertEqual((ev['sucss_ref'], ev['onet_ref']), ('D0', '1'))
        self.assertTrue(all(0 <= c['evidence_index'] <= 100 for c in cands))

    def test_deterministic_across_instances(self):
        title, units = self.units()
        a = mt.Matcher(OCC, TASKS, ALTS).score_class(title, units)
        b = mt.Matcher(list(reversed(OCC)), list(reversed(TASKS)), ALTS).score_class(title, list(units))
        self.assertEqual(json.dumps(a, sort_keys=True), json.dumps(b, sort_keys=True))

    def test_abstain_rules(self):
        weak = [{'evidence_index': 20.0, 'duty_coverage': 0.05, 'title_similarity': 0.2}]
        self.assertEqual(mt.abstain_reason(weak, True), 'low_evidence_index')
        self.assertEqual(mt.abstain_reason(weak, False), 'no_spec_text_and_weak_title')
        ok = [{'evidence_index': 60.0, 'duty_coverage': 0.3, 'title_similarity': 0.9}]
        self.assertIsNone(mt.abstain_reason(ok, True))

    def test_boilerplate_and_stem(self):
        self.assertTrue(mt.is_boilerplate('performs other related duties as assigned.'))
        self.assertTrue(mt.is_boilerplate('Performs work related to the lower level in this series.'))
        self.assertFalse(mt.is_boilerplate('prepares payroll'))
        self.assertEqual(mt.stem('reconciles'), mt.stem('reconcile'))
        self.assertEqual(mt.stem('supervising'), mt.stem('supervises'))
        self.assertEqual(mt.clean_title('Accountant III'), 'Accountant')


class CommittedOutputTests(unittest.TestCase):
    """If build outputs exist, check they carry no SUCSS duty text (spans/IDs only)."""

    def test_no_sucss_text_in_committed_outputs(self):
        local = PKG / 'local' / 'spec_sections.jsonl'
        queue = PKG / 'outputs' / 'review_queue.csv'
        if not (local.exists() and queue.exists()):
            self.skipTest('build outputs not present')
        published = queue.read_text(encoding='utf-8')
        texts = set()
        for line in local.read_text(encoding='utf-8').splitlines():
            rec = json.loads(line)
            texts.update(d['text'] for d in rec['duties'] if len(d['text']) > 60)
        leaked = [t for t in texts if t in published]
        self.assertEqual(leaked[:3], [])

    def test_gold_labels_marked_provisional(self):
        gold = PKG / 'gold' / 'provisional_gold_labels.csv'
        if not gold.exists():
            self.skipTest('no gold file')
        with gold.open(encoding='utf-8') as f:
            rows = list(csv.DictReader(f))
        self.assertEqual(len(rows), 60)
        self.assertTrue(all(r['label_status'] == 'provisional_agent_label — requires HR analyst review' for r in rows))


if __name__ == '__main__':
    unittest.main()
